"""Drive the whole Spine loop with in-memory fakes (no real lanes needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from devorchestrator.contracts import DevActivity
from devorchestrator.pipeline import (
    LanePending,
    Pipeline,
    PipelineAborted,
    PipelineError,
    build_pipeline,
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
    # research wrote the artifact; the pipeline read + parsed its module list
    assert "src/devorchestrator/widget.py" in ctx.artifact.modules_affected
    assert "tests/test_widget.py" in ctx.artifact.modules_affected
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
        "src/devorchestrator/widget.py": [
            DevActivity(dev="alice", module="src/devorchestrator/widget.py",
                        branch="feature/other", event_type="task_started", ts="t0")
        ]
    }
    pipe, _, _ = _pipeline(tmp_path, branch, issue, mesh=FakeMesh(touching), events=events)
    pipe.start(select=lambda issues: issues[0])
    assert any("conflict" in e and "alice" in e for e in events)


def test_no_conflict_warning_for_self(tmp_path, branch, issue):
    events: list[str] = []
    touching = {
        "src/devorchestrator/widget.py": [
            DevActivity(dev="tester", module="src/devorchestrator/widget.py",
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


def test_build_pipeline_reports_lane_pending():
    with pytest.raises(LanePending) as exc:
        build_pipeline(make_config())
    assert exc.value.component == "board"
    assert "Lane B" in exc.value.where
