"""The orchestration backbone — the SDLC loop expressed against `contracts`.

This is Lane A's ``pipeline.py``. It runs the loop from ``docs/research.md`` (task
→ branch → research → artifact → implement → checks → PR) **against the frozen
`contracts.py` Protocols** for every swappable adapter (board / git / session /
checks / mesh / notifier). Those boundaries are dependency-injected, so:

- unit tests drive the whole loop with in-memory fakes (see tests/test_pipeline.py),
- :func:`build_pipeline` swaps in the real Lane B/C/D adapters with **zero
  changes** to the orchestration logic below.

One deliberate exception to "no cross-lane imports": prompt text and artifact
parsing are not swappable adapters — there is exactly one artifact format, and
Lane C owns the schema (``prompts/``), the writer (``sessions/research.py``) and
the reader (``sessions/artifact.py``). ``start``/``prepare_pr`` import those
directly instead of keeping a second copy that can drift out of step.

The pipeline is deliberately **UI-free**: human-facing progress/warnings go through
an injected ``on_event`` callback (the CLI wires it to a Rich console; tests capture
it). Rich rendering lives in the CLI and in ``review.py``, not here.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from .config import Config
from .contracts import (
    Artifact,
    BoardAdapter,
    BranchRef,
    CheckRunner,
    GitAdapter,
    Issue,
    Mesh,
    Notifier,
    PipelineContext,
)

# A selector turns the fetched issues into the one the dev chose (or None to abort).
# Lane B's selector.py provides the real Rich picker; tests pass a lambda.
Selector = Callable[[list[Issue]], "Issue | None"]

# An AgentSession per contracts: .run(prompt) sends work to a tmux pane, .is_alive().
# Typed loosely here to avoid importing the Protocol name into signatures twice.


class PipelineError(Exception):
    """Base class for pipeline control-flow errors."""


class PipelineAborted(PipelineError):
    """Raised when the human declines to continue (no task picked, conflict declined)."""


class LanePending(PipelineError):
    """Raised by :func:`build_pipeline` when a lane's adapter module isn't built yet.

    Carries which component is missing so the CLI can print an honest
    "waiting on Lane X" message instead of a traceback.
    """

    def __init__(self, component: str, where: str) -> None:
        self.component = component
        self.where = where
        super().__init__(f"{component} adapter not available yet ({where})")


class Pipeline:
    """Runs one developer's task through the SDLC loop.

    All collaborators are injected and typed as `contracts` Protocols; the pipeline
    only ever calls the small documented surface of each.
    """

    def __init__(
        self,
        config: Config,
        *,
        board: BoardAdapter,
        git: GitAdapter,
        research,  # contracts.AgentSession
        impl,  # contracts.AgentSession
        checks: CheckRunner,
        mesh: Mesh | None = None,
        notifier: Notifier | None = None,
        describe_pr: Callable[[PipelineContext], str] | None = None,
        workdir: Path | str = ".orchestrator",
        on_event: Callable[[str], None] | None = None,
        local_git: bool = False,
    ) -> None:
        self.config = config
        self.board = board
        self.git = git
        self.research = research
        self.impl = impl
        self.checks = checks
        self.mesh = mesh
        self.notifier = notifier
        self._describe_pr = describe_pr or _default_pr_description
        self.workdir = Path(workdir)
        self.local_git = local_git
        self._on_event = on_event or (lambda _msg: None)

    # -- public loop ------------------------------------------------------

    def start(self, select: Selector) -> PipelineContext:
        """Fetch tasks, let the human pick, branch, research, then implement.

        Returns the populated :class:`PipelineContext`. Raises
        :class:`PipelineAborted` if no task is chosen.
        """
        issues = self.board.fetch_issues()
        if not issues:
            raise PipelineAborted("no open tasks assigned to you on the board.")

        issue = select(issues)
        if issue is None:
            raise PipelineAborted("no task selected.")
        self._event(f"selected {issue.id}: {issue.title}")

        branch = self.git.create_branch(issue, base="dev")
        if self.local_git:
            self._checkout_local(branch)
        self._emit("task_started", module=_primary_module(branch), payload={
            "issue_id": issue.id, "title": issue.title, "branch": branch.name,
        })
        ctx = PipelineContext(issue=issue, branch=branch)

        # Research session writes the artifact; we read it back.
        # Prompt text and artifact parsing come from Lane C, not from local
        # copies: prompts/research.md carries the artifact schema, grounding
        # rules and lane guardrails, and sessions/artifact.py is the reader that
        # matches that schema. Imports are function-local so this module still
        # imports cleanly if sessions/ is absent.
        from .sessions.artifact import load_artifact
        from .sessions.research import build_research_prompt

        artifact_path = self._artifact_path(branch)
        prompt_file = build_research_prompt(issue, branch.name, root=self.workdir)
        self.research.run(prompt_file.read_text(encoding="utf-8"))
        ctx.artifact = load_artifact(
            branch.name, issue_id=issue.id, root=self.workdir
        ) or Artifact(path=str(artifact_path), issue_id=issue.id, branch=branch.name)

        # Now that modules are known, warn on any in-flight overlap (non-blocking).
        self._warn_on_conflicts(ctx.artifact)
        self._emit("artifact_generated", module=_primary_module(branch), payload={
            "branch": branch.name,
            "artifact_path": str(artifact_path),
            "modules_affected": list(ctx.artifact.modules_affected),
        })

        # Implementation session works through the artifact.
        from .sessions.impl import build_impl_prompt

        prompt_file = build_impl_prompt(branch.name, root=self.workdir)
        self.impl.run(prompt_file.read_text(encoding="utf-8"))
        self._event("implementation session finished")
        if self.local_git:
            self._commit_and_push(branch, issue)
        return ctx

    def prepare_pr(self, ctx: PipelineContext, *, autofix: bool = True) -> PipelineContext:
        """Run quality gates (autofix on failure), then open the PR.

        Raises :class:`PipelineError` if checks still fail after the retry budget.
        """
        if ctx.branch is None:
            raise PipelineError("prepare_pr called before a branch exists.")

        from .sessions.impl import build_autofix_prompt

        ctx.checks = self.checks.run_all()
        # Counts up rather than down: build_autofix_prompt renders "attempt N of
        # M" into the prompt, so the agent knows how much budget is left.
        max_attempts = self.config.autofix_retries if autofix else 0
        attempt = 1
        while _any_failed(ctx.checks) and attempt <= max_attempts:
            failed = [c for c in ctx.checks if not c.passed]
            self._event(
                f"checks failed ({_names(failed)}); autofix attempt {attempt}/{max_attempts}"
            )
            prompt_file = build_autofix_prompt(
                ctx.branch.name, ctx.checks,
                attempt=attempt, max_attempts=max_attempts, root=self.workdir,
            )
            self.impl.run(prompt_file.read_text(encoding="utf-8"))
            ctx.checks = self.checks.run_all()
            attempt += 1

        if _any_failed(ctx.checks):
            still_failing = _names([c for c in ctx.checks if not c.passed])
            raise PipelineError(f"checks still failing after autofix: {still_failing}")

        body = self._describe_pr(ctx)
        pr = self.git.open_pr(ctx.branch, title=ctx.issue.title, body=body)
        ctx.pull_request = pr
        self._emit("pr_opened", module=_primary_module(ctx.branch), payload={
            "branch": ctx.branch.name, "pr_url": pr.url, "pr_number": pr.number,
        })
        self._notify(f"PR ready: {ctx.issue.title} — {pr.url}")
        self._event(f"opened PR #{pr.number}: {pr.url}")
        return ctx

    # -- internals --------------------------------------------------------

    def _checkout_local(self, branch: BranchRef) -> None:
        """Fetch and check out the branch git.create_branch() just made on the server.

        create_branch only creates a ref via the git server's API — nothing else
        checks out a local working copy, so without this the research/impl
        sessions would edit files on whatever branch happened to be checked out
        before start() ran, not the new one.
        """
        subprocess.run(["git", "fetch", "origin", branch.name], check=True)
        result = subprocess.run(
            ["git", "checkout", "-B", branch.name, f"origin/{branch.name}"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise PipelineError(f"could not check out {branch.name} locally: {result.stderr}")

    def _commit_and_push(self, branch: BranchRef, issue: Issue) -> None:
        """Commit whatever the impl session changed and push it to ``branch``.

        Nothing else in the loop commits or pushes — without this, open_pr()
        would open a PR with zero commits (identical to base), since
        create_branch only creates an empty ref.
        """
        status = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        )
        if not status.stdout.strip():
            self._event("nothing to commit — implementation session made no changes")
            return

        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(
            ["git", "commit", "-m", f"issue #{issue.id}: {issue.title}"], check=True
        )
        subprocess.run(["git", "push", "-u", "origin", branch.name], check=True)
        self._event(f"committed and pushed to {branch.name}")

    def _artifact_path(self, branch: BranchRef) -> Path:
        return self.workdir / branch.name / "artifact.md"

    def _warn_on_conflicts(self, artifact: Artifact) -> None:
        if self.mesh is None:
            return
        for module in artifact.modules_affected:
            for activity in self.mesh.who_is_touching(module):
                if activity.dev != self.config.name:
                    self._event(
                        f"⚠ conflict: {activity.dev} is in {module} "
                        f"({activity.branch}) since {activity.ts}"
                    )

    def _emit(self, event_type: str, *, module: str, payload: dict) -> None:
        if self.mesh is not None:
            self.mesh.emit(event_type, module, payload)

    def _notify(self, message: str) -> None:
        if self.notifier is not None:
            self.notifier.notify(message)

    def _event(self, message: str) -> None:
        self._on_event(message)


# ---------------------------------------------------------------------------
# Pure helpers (prompt templates, parsing) — no side effects, easy to test
# ---------------------------------------------------------------------------


def _default_pr_description(ctx: PipelineContext) -> str:
    """Fallback PR body when no `describe_pr` (Lane D brain) is injected."""
    lines = [f"## {ctx.issue.title}", "", ctx.issue.description or "_No description._", ""]
    if ctx.checks:
        lines.append("### Checks")
        lines += [f"- {'✅' if c.passed else '❌'} {c.tool}" for c in ctx.checks]
    return "\n".join(lines)


# _research_prompt / _impl_prompt / _fix_prompt / _parse_modules used to live
# here. They were written before Lane C existed and are now deleted rather than
# kept as a second implementation: prompts/ + sessions/artifact.py are the
# canonical ones, and the duplicate parser disagreed about what a "module" is
# (full path vs. top-level package), which the mesh keys conflict detection on.


def _primary_module(branch: BranchRef) -> str:
    """A coarse module label for mesh events keyed off the branch."""
    return branch.name


def _any_failed(checks: list) -> bool:
    return any(not c.passed for c in checks)


def _names(checks: list) -> str:
    return ", ".join(c.tool for c in checks)


# ---------------------------------------------------------------------------
# Factory — the Wave-3 integration seam
# ---------------------------------------------------------------------------

# (component, module that must exist, human label). build_pipeline reports the
# first missing one so the CLI can say exactly which lane it's waiting on.
_REQUIRED_ADAPTERS: list[tuple[str, str, str]] = [
    ("board", "devorchestrator.integrations.github_board", "Lane B: integrations/github_board.py"),
    ("git", "devorchestrator.integrations.github_git", "Lane B: integrations/github_git.py"),
    ("sessions", "devorchestrator.sessions.tmux_runner", "Lane C: sessions/tmux_runner.py"),
    ("checks", "devorchestrator.checks.runner", "Lane D: checks/runner.py"),
]


def build_pipeline(config: Config, *, workdir: Path | str = ".orchestrator",
                   on_event: Callable[[str], None] | None = None) -> Pipeline:
    """Construct a Pipeline wired to the real adapters for ``config``.

    Until Lane B/C/D land, this raises :class:`LanePending` for the first missing
    adapter. Once every adapter module exists, constructs the real board/git/
    session/check/mesh/notifier objects from ``config`` and returns a working
    ``Pipeline`` — the same construction ``scripts/demo.sh`` did by hand while
    this function was still a stub (see docs/DEMO.md).
    """
    import importlib.util
    import os

    from .config import BoardType, GitType

    for component, module, where in _REQUIRED_ADAPTERS:
        try:
            spec = importlib.util.find_spec(module)
        except ModuleNotFoundError:
            spec = None  # parent package (the lane) doesn't exist yet
        if spec is None:
            raise LanePending(component, where)

    # Only a GitHub board/git adapter exists in this repo (Plane/Azure deferred
    # post-hackathon — docs/product-backlog.md Horizon H1); a config targeting
    # those reports the same "adapter not available yet" as a missing module.
    if config.board.type is not BoardType.github:
        raise LanePending(
            "board",
            f"Lane B: only board.type=github is implemented (got {config.board.type.value!r})",
        )
    if config.git.type is not GitType.github:
        raise LanePending(
            "git", f"Lane B: only git.type=github is implemented (got {config.git.type.value!r})"
        )

    from .checks.runner import SubprocessCheckRunner
    from .integrations.github_board import GithubBoard
    from .integrations.github_git import GithubGit
    from .pr_description import generate_pr_description
    from .sessions.tmux_runner import ClaudeSession, SessionKind

    board = GithubBoard(
        url=config.board.url,
        token=os.environ[config.board.token_env],
        dev_name=config.name,
        project_number=config.board.project_number,
    )
    git = GithubGit(
        url=config.git.url,
        token=os.environ[config.git.token_env],
    )
    research = ClaudeSession(SessionKind.research, agent=config.agent.value)
    impl = ClaudeSession(SessionKind.impl, agent=config.agent.value)
    checks = SubprocessCheckRunner()

    mesh = None
    mesh_key = os.environ.get(config.mesh.supabase_key_env, "")
    if config.mesh.supabase_url and mesh_key:
        from .mesh.store import SupabaseMesh, create_supabase_client

        mesh = SupabaseMesh(create_supabase_client(config.mesh.supabase_url, mesh_key))

    notifier = config.notify.build_notifier() if config.notify is not None else None

    return Pipeline(
        config,
        board=board,
        git=git,
        research=research,
        impl=impl,
        checks=checks,
        mesh=mesh,
        notifier=notifier,
        # config= is what lets generate_pr_description reach the brain; without it
        # it silently returns the mechanical description no matter how the brain
        # is configured (see test_describe_pr_forwards_config_to_the_brain).
        describe_pr=lambda ctx: generate_pr_description(
            ctx.branch.name, base=ctx.branch.base, config=config
        ),
        workdir=workdir,
        on_event=on_event,
        # Required, not optional: create_branch() only makes a remote ref via the
        # GitHub API. Without local_git the sessions edit whatever branch was
        # already checked out, nothing commits, and open_pr() opens an empty PR.
        # A merge silently dropped this once (7ebf5e2) — test_build_pipeline_
        # enables_local_git guards it now.
        local_git=True,
    )
