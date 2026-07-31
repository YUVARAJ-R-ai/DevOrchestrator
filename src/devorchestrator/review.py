"""The TL approval gate — `AI → Human` boundary of the escalation model.

Lane A's ``review.py`` (backlog #29–31). Renders what a team lead needs to decide
on a PR — the diff, the check results, and the artifact (what was *planned* vs what
was built) — then performs the approve (merge) or reject (comment + notify) action.

Uses the review methods added to the ``GitAdapter`` contract — ``list_open_prs``,
``get_diff``, ``get_ci_status``, ``comment_pr`` — so this gate can fetch everything
it needs itself: :meth:`ReviewGate.open_prs` lists the PRs awaiting the TL and
:meth:`ReviewGate.review_pr` pulls the diff + CI, renders, and is ready for the
CLI to dispatch the keypress. ``render`` still accepts pre-fetched inputs for
tests and callers that already have them.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from .config import Config
from .contracts import (
    Artifact,
    CheckResult,
    GitAdapter,
    MergeStrategy,
    Mesh,
    Notifier,
    PullRequest,
)
from .pipeline import LanePending


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    """The outcome of a review; returned so the CLI can report it uniformly."""

    action: str  # "approved" | "rejected"
    pr: PullRequest
    reason: str = ""


class ReviewGate:
    """Renders a PR for review and executes the approve/reject decision."""

    def __init__(
        self,
        config: Config,
        *,
        git: GitAdapter,
        mesh: Mesh | None = None,
        notifier: Notifier | None = None,
        console: Console | None = None,
        merge_strategy: MergeStrategy = MergeStrategy.squash,
    ) -> None:
        self.config = config
        self.git = git
        self.mesh = mesh
        self.notifier = notifier
        self.console = console or Console()
        self.merge_strategy = merge_strategy

    # -- fetching ---------------------------------------------------------

    def open_prs(self) -> list[PullRequest]:
        """PRs awaiting this reviewer (the TL). Empty list if none.

        Filters on ``git.reviewer`` — the git-host login — not ``config.name``,
        which is a display name. GitHub's requested-reviewer list holds logins,
        so filtering by display name matches nothing. With no reviewer
        configured, every open PR is listed rather than none: an unfiltered list
        is recoverable, an empty one just looks like there is no work.
        """
        return self.git.list_open_prs(assignee=self.config.git.reviewer)

    def review_pr(self, pr: PullRequest, checks: list[CheckResult],
                  artifact: Artifact | None = None) -> None:
        """Fetch the diff + CI for ``pr`` and render the full review view.

        The check results and artifact come from the pipeline run (the CLI holds
        them); the diff and CI status are pulled fresh from the git server here.
        """
        diff = self.git.get_diff(pr)
        ci_status = self.git.get_ci_status(pr)
        self.render(pr, diff=diff, checks=checks, artifact=artifact, ci_status=ci_status)

    # -- presentation -----------------------------------------------------

    def render(
        self,
        pr: PullRequest,
        diff: str,
        checks: list[CheckResult],
        artifact: Artifact | None = None,
        ci_status: str = "unknown",
    ) -> None:
        """Show diff | checks + CI | artifact for one PR.

        A single vertical stack of panels (not a fragile 3-pane split) — per the
        Sprint-2 carry-over note, functionality over layout polish.
        """
        header = f"[bold]#{pr.number}[/] {pr.title}  →  {pr.base}\n[dim]{pr.url}[/]"

        diff_panel = Panel(
            Syntax(diff or "(no diff)", "diff", theme="ansi_dark", word_wrap=True),
            title="diff", border_style="cyan",
        )

        checks_table = Table(title=f"checks · CI: {ci_status}", show_header=True, expand=True)
        checks_table.add_column("tool")
        checks_table.add_column("result")
        checks_table.add_column("time", justify="right")
        for c in checks:
            mark = "[green]✓ pass[/]" if c.passed else "[red]✗ fail[/]"
            checks_table.add_row(c.tool, mark, f"{c.duration_s:.1f}s")

        panels = [Panel(header, border_style="magenta"), diff_panel, checks_table]
        if artifact is not None and artifact.raw:
            panels.append(Panel(Markdown(artifact.raw), title="artifact (planned)",
                                border_style="green"))
        panels.append(Panel("[a] approve & merge   [r] reject   [o] open in browser   [q] quit",
                            border_style="dim"))
        self.console.print(Group(*panels))

    # -- actions ----------------------------------------------------------

    def approve(self, pr: PullRequest) -> ReviewDecision:
        """Merge the PR, delete the source branch, record + notify."""
        self.git.merge_pr(pr, self.merge_strategy)
        self._emit("pr_merged", module=pr.branch, payload={
            "pr_number": pr.number, "pr_url": pr.url, "by": self.config.name,
        })
        self._notify(f"✅ Merged: {pr.title} — {pr.url}")
        return ReviewDecision(action="approved", pr=pr)

    def reject(self, pr: PullRequest, reason: str) -> ReviewDecision:
        """Reject the PR: post the reason as an on-PR comment and notify the dev."""
        self.git.comment_pr(pr, f"Changes requested: {reason}")
        self._emit("pr_rejected", module=pr.branch, payload={
            "pr_number": pr.number, "reason": reason, "by": self.config.name,
        })
        self._notify(f"❌ PR rejected: {reason} — {pr.url}")
        return ReviewDecision(action="rejected", pr=pr, reason=reason)

    # -- internals --------------------------------------------------------

    def _emit(self, event_type: str, *, module: str, payload: dict) -> None:
        if self.mesh is not None:
            self.mesh.emit(event_type, module, payload)

    def _notify(self, message: str) -> None:
        if self.notifier is not None:
            self.notifier.notify(message)


# ---------------------------------------------------------------------------
# Factory — the Wave-3 integration seam (mirrors pipeline.build_pipeline)
# ---------------------------------------------------------------------------

_GIT_ADAPTER = ("git", "devorchestrator.integrations.github_git",
                "Lane B: integrations/github_git.py")


def build_review(config: Config, *, console: Console | None = None) -> ReviewGate:
    """Construct a ReviewGate wired to the real git adapter for ``config``.

    Raises :class:`LanePending` until Lane B's git adapter lands. Once it exists,
    constructs the real git/mesh/notifier objects from ``config`` and returns a
    working ``ReviewGate`` — the same construction ``scripts/demo.sh`` did by
    hand while this function was still a stub (see docs/DEMO.md).
    """
    import importlib.util
    import os

    from .config import GitType, require_env

    component, module, where = _GIT_ADAPTER
    try:
        spec = importlib.util.find_spec(module)
    except ModuleNotFoundError:
        spec = None  # parent package (the lane) doesn't exist yet
    if spec is None:
        raise LanePending(component, where)

    # Only a GitHub git adapter exists in this repo (Plane/Azure deferred
    # post-hackathon — docs/product-backlog.md Horizon H1).
    if config.git.type is not GitType.github:
        raise LanePending(
            "git", f"Lane B: only git.type=github is implemented (got {config.git.type.value!r})"
        )

    from .integrations.github_git import GithubGit

    git = GithubGit(
        url=config.git.url,
        token=require_env("git.token_env", config.git.token_env),
        # Requests review from this login on every PR — without it nothing is
        # ever "awaiting review" and `devorchestrator review` lists nothing.
        reviewer=config.git.reviewer,
    )

    mesh = None
    mesh_key = os.environ.get(config.mesh.supabase_key_env, "")
    if config.mesh.supabase_url and mesh_key:
        from .mesh.store import SupabaseMesh, create_supabase_client

        mesh = SupabaseMesh(create_supabase_client(config.mesh.supabase_url, mesh_key))

    notifier = config.notify.build_notifier() if config.notify is not None else None

    return ReviewGate(config, git=git, mesh=mesh, notifier=notifier, console=console)
