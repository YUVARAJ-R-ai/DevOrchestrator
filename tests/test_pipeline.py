"""Drive the whole Spine loop with in-memory fakes (no real lanes needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from devorchestrator.contracts import BranchRef, DevActivity, Issue, PipelineContext
from devorchestrator.pipeline import (
    LanePending,
    Pipeline,
    PipelineAborted,
    PipelineError,
    build_pipeline,
    context_path,
    load_pipeline_context,
)
from tests.conftest import (
    ARTIFACT_BODY,
    FakeBoard,
    FakeChecks,
    FakeGit,
    FakeMesh,
    FakeNotifier,
    FakeSession,
    failing,
    make_config,
    passing,
)


def _pipeline(tmp_path: Path, branch, issue, *, checks=None, mesh=None, notifier=None, events=None):
    workdir = tmp_path / ".orchestrator"
    artifact_path = workdir / branch.name / "artifact.md"
    research = FakeSession(write_path=artifact_path, content=ARTIFACT_BODY)
    impl = FakeSession()
    return Pipeline(
        make_config(),
        board=FakeBoard([issue]),
        git=FakeGit(branch),
        research=research,
        impl=impl,
        checks=checks or FakeChecks([[passing()]]),
        mesh=mesh,
        notifier=notifier,
        workdir=workdir,
        on_event=(events.append if events is not None else None),
    ), research, impl


def test_start_happy_path(tmp_path, branch, issue):
    mesh = FakeMesh()
    pipe, research, impl = _pipeline(tmp_path, branch, issue, mesh=mesh)
    ctx = pipe.start(select=lambda issues: issues[0])

    assert ctx.issue.id == "9"
    assert ctx.branch is branch
    # research wrote the artifact; sessions.artifact.load_artifact parsed it.
    # modules_affected is the *top-level module* per planned file, not the full
    # path — that granularity is what the mesh keys conflict detection on.
    assert "devorchestrator" in ctx.artifact.modules_affected
    assert "test_widget.py" in ctx.artifact.modules_affected
    # research ran before impl
    assert len(research.prompts) == 1
    assert len(impl.prompts) == 1
    # both key mesh events emitted
    kinds = [e[0] for e in mesh.events]
    assert kinds == ["task_started", "artifact_generated"]


def test_start_aborts_without_selection(tmp_path, branch, issue):
    pipe, _, _ = _pipeline(tmp_path, branch, issue)
    with pytest.raises(PipelineAborted, match="no task selected"):
        pipe.start(select=lambda issues: None)


def test_start_aborts_with_no_issues(tmp_path, branch):
    workdir = tmp_path / ".orchestrator"
    pipe = Pipeline(
        make_config(),
        board=FakeBoard([]),
        git=FakeGit(branch),
        research=FakeSession(),
        impl=FakeSession(),
        checks=FakeChecks([[passing()]]),
        workdir=workdir,
    )
    with pytest.raises(PipelineAborted, match="no open tasks"):
        pipe.start(select=lambda issues: issues[0])


def test_conflict_warning_emitted(tmp_path, branch, issue):
    events: list[str] = []
    touching = {
        "devorchestrator": [
            DevActivity(dev="alice", module="devorchestrator",
                        branch="feature/other", event_type="task_started", ts="t0")
        ]
    }
    pipe, _, _ = _pipeline(tmp_path, branch, issue, mesh=FakeMesh(touching), events=events)
    pipe.start(select=lambda issues: issues[0])
    assert any("conflict" in e and "alice" in e for e in events)


def test_no_conflict_warning_for_self(tmp_path, branch, issue):
    events: list[str] = []
    touching = {
        "devorchestrator": [
            DevActivity(dev="tester", module="devorchestrator",
                        branch="feature/mine", event_type="task_started", ts="t0")
        ]
    }
    pipe, _, _ = _pipeline(tmp_path, branch, issue, mesh=FakeMesh(touching), events=events)
    pipe.start(select=lambda issues: issues[0])
    assert not any("conflict" in e for e in events)


def test_prepare_pr_opens_pr_when_checks_pass(tmp_path, branch, issue):
    mesh, notifier = FakeMesh(), FakeNotifier()
    pipe, _, impl = _pipeline(tmp_path, branch, issue, mesh=mesh, notifier=notifier,
                              checks=FakeChecks([[passing("ruff"), passing("pytest")]]))
    ctx = pipe.start(select=lambda issues: issues[0])
    ctx = pipe.prepare_pr(ctx)

    assert ctx.pull_request is not None
    assert ctx.pull_request.number == 7
    assert len(impl.prompts) == 1  # no autofix retry needed
    assert any(e[0] == "pr_opened" for e in mesh.events)
    assert any("PR ready" in m for m in notifier.messages)


def test_prepare_pr_autofix_then_success(tmp_path, branch, issue):
    # first check batch fails, second passes → exactly one fix re-invocation
    checks = FakeChecks([[failing("pytest")], [passing("pytest")]])
    pipe, _, impl = _pipeline(tmp_path, branch, issue, checks=checks)
    ctx = pipe.start(select=lambda issues: issues[0])
    ctx = pipe.prepare_pr(ctx, autofix=True)

    assert ctx.pull_request is not None
    assert len(impl.prompts) == 2  # 1 implement + 1 fix
    assert checks.calls == 2


def test_prepare_pr_raises_when_never_green(tmp_path, branch, issue):
    checks = FakeChecks([[failing("pytest")]])  # always fails
    pipe, _, impl = _pipeline(tmp_path, branch, issue, checks=checks)
    ctx = pipe.start(select=lambda issues: issues[0])
    with pytest.raises(PipelineError, match="still failing"):
        pipe.prepare_pr(ctx, autofix=True)
    # 1 implement + autofix_retries (default 2) fix attempts
    assert len(impl.prompts) == 3


def test_prepare_pr_no_autofix_raises_immediately(tmp_path, branch, issue):
    checks = FakeChecks([[failing("pytest")]])
    pipe, _, impl = _pipeline(tmp_path, branch, issue, checks=checks)
    ctx = pipe.start(select=lambda issues: issues[0])
    with pytest.raises(PipelineError):
        pipe.prepare_pr(ctx, autofix=False)
    assert len(impl.prompts) == 1  # implement only, no fix attempts
    assert checks.calls == 1


def test_start_persists_context_for_pr(tmp_path, branch, issue):
    """`devorchestrator pr` is a separate process — start() must leave it the issue."""
    workdir = tmp_path / ".orchestrator"
    pipe, _, _ = _pipeline(tmp_path, branch, issue)
    pipe.start(select=lambda issues: issues[0])

    assert context_path(branch.name, root=workdir).is_file()

    restored = load_pipeline_context(branch.name, root=workdir)
    assert restored is not None
    assert restored.issue.id == issue.id
    assert restored.issue.title == issue.title
    assert restored.branch.name == branch.name
    assert restored.branch.base == branch.base
    # artifact is re-read from disk, not from the json — an artifact edited
    # between `start` and `pr` should be the one that gets used
    assert restored.artifact is not None
    assert "devorchestrator" in restored.artifact.modules_affected


def test_load_pipeline_context_returns_none_when_absent(tmp_path):
    """Missing context is a normal case (user ran `pr` first) — None, not a crash."""
    assert load_pipeline_context("feature/nope", root=tmp_path / ".orchestrator") is None


def test_load_pipeline_context_returns_none_on_corrupt_json(tmp_path):
    workdir = tmp_path / ".orchestrator"
    path = context_path("feature/x", root=workdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    assert load_pipeline_context("feature/x", root=workdir) is None


def test_build_pipeline_reports_lane_pending():
    with pytest.raises(LanePending) as exc:
        build_pipeline(make_config())
    assert exc.value.component == "board"
    assert "Lane B" in exc.value.where


def test_build_pipeline_constructs_real_adapters_for_github(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The only adapter that exists is GitHub; a github-typed config should wire it for real."""
    from devorchestrator.checks.runner import SubprocessCheckRunner
    from devorchestrator.integrations.github_board import GithubBoard
    from devorchestrator.integrations.github_git import GithubGit
    from devorchestrator.sessions.tmux_runner import ClaudeSession

    monkeypatch.setenv("BOARD_TOKEN", "t")
    monkeypatch.setenv("GIT_TOKEN", "t")
    config = make_config(
        board={"type": "github", "url": "https://github.com/acme/repo", "token_env": "BOARD_TOKEN"},
        git={"type": "github", "url": "https://github.com/acme/repo", "token_env": "GIT_TOKEN"},
    )

    pipeline = build_pipeline(config)

    assert isinstance(pipeline.board, GithubBoard)
    assert isinstance(pipeline.git, GithubGit)
    assert isinstance(pipeline.research, ClaudeSession)
    assert isinstance(pipeline.impl, ClaudeSession)
    assert isinstance(pipeline.checks, SubprocessCheckRunner)
    assert pipeline.mesh is None  # no SUPABASE_SERVICE_KEY set


def test_build_pipeline_enables_local_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """local_git must be on: create_branch() only makes a *remote* ref.

    Without it nothing checks out the new branch, nothing commits, and open_pr()
    opens a PR with zero commits. A merge silently dropped this flag once
    (7ebf5e2), which is why it is asserted rather than assumed.
    """
    monkeypatch.setenv("BOARD_TOKEN", "t")
    monkeypatch.setenv("GIT_TOKEN", "t")
    config = make_config(
        board={"type": "github", "url": "https://github.com/acme/repo", "token_env": "BOARD_TOKEN"},
        git={"type": "github", "url": "https://github.com/acme/repo", "token_env": "GIT_TOKEN"},
    )

    assert build_pipeline(config).local_git is True


def test_describe_pr_forwards_config_to_the_brain(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_pipeline's describe_pr must pass config= through.

    Without it generate_pr_description can't build the brain and silently returns
    the mechanical description however the brain is configured — a failure mode
    with no visible error, which is how a merge (7ebf5e2) undid it unnoticed.
    """
    monkeypatch.setenv("BOARD_TOKEN", "t")
    monkeypatch.setenv("GIT_TOKEN", "t")
    config = make_config(
        board={"type": "github", "url": "https://github.com/acme/repo", "token_env": "BOARD_TOKEN"},
        git={"type": "github", "url": "https://github.com/acme/repo", "token_env": "GIT_TOKEN"},
    )
    seen: dict[str, object] = {}

    def _spy(branch: str, base: str = "dev", *, cwd=None, config=None):
        seen["config"] = config
        return "body"

    # Patch before build_pipeline: it does `from .pr_description import
    # generate_pr_description` at call time and closes over that local name.
    monkeypatch.setattr("devorchestrator.pr_description.generate_pr_description", _spy)
    pipeline = build_pipeline(config)

    ctx = PipelineContext(
        issue=Issue(id="9", title="t"),
        branch=BranchRef(name="feature/issue-9-t", issue_id="9", base="dev"),
    )
    pipeline._describe_pr(ctx)

    assert seen["config"] is config
