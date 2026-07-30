"""Tests for the TL approval gate (review.py) with in-memory fakes."""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from devorchestrator.contracts import Artifact, MergeStrategy, PullRequest
from devorchestrator.pipeline import LanePending
from devorchestrator.review import ReviewGate, build_review
from tests.conftest import (
    ARTIFACT_BODY,
    FakeGit,
    FakeMesh,
    FakeNotifier,
    failing,
    make_config,
    passing,
)


def _pr() -> PullRequest:
    return PullRequest(
        number=7, title="Add widget", url="http://git/pr/7", branch="feature/issue-9-widget"
    )


def _gate(git: FakeGit | None = None, **over) -> tuple[ReviewGate, FakeGit, FakeMesh, FakeNotifier]:
    git = git or FakeGit(branch=None)  # branch not needed for review-only tests
    mesh, notifier = FakeMesh(), FakeNotifier()
    console = Console(file=io.StringIO(), force_terminal=False)
    gate = ReviewGate(make_config(), git=git, mesh=mesh, notifier=notifier, console=console, **over)
    return gate, git, mesh, notifier


def test_approve_merges_records_and_notifies():
    gate, git, mesh, notifier = _gate()
    pr = _pr()
    decision = gate.approve(pr)

    assert decision.action == "approved"
    assert len(git.merged) == 1
    assert git.merged[0] == (pr, MergeStrategy.squash)
    assert any(e[0] == "pr_merged" for e in mesh.events)
    assert any("Merged" in m for m in notifier.messages)


def test_approve_uses_configured_strategy():
    gate, git, _, _ = _gate(merge_strategy=MergeStrategy.rebase)
    gate.approve(_pr())
    assert git.merged[0][1] == MergeStrategy.rebase


def test_reject_comments_notifies_with_reason():
    gate, git, mesh, notifier = _gate()
    decision = gate.reject(_pr(), reason="needs tests")

    assert decision.action == "rejected"
    assert decision.reason == "needs tests"
    assert not git.merged  # reject never merges
    # posts an on-PR comment carrying the reason
    assert len(git.comments) == 1
    assert "needs tests" in git.comments[0][1]
    assert any(e[0] == "pr_rejected" for e in mesh.events)
    assert any("rejected" in m and "needs tests" in m for m in notifier.messages)


def test_open_prs_returns_git_prs():
    prs = [_pr()]
    gate, _, _, _ = _gate(FakeGit(branch=None, open_prs=prs))
    assert gate.open_prs() == prs


def test_review_pr_fetches_diff_and_ci_then_renders():
    gate, _, _, _ = _gate(FakeGit(branch=None, diff="- a\n+ b\n", ci="green"))
    # should pull diff + CI from git and render without raising
    gate.review_pr(_pr(), checks=[passing("ruff"), failing("pytest")])


def test_render_does_not_raise():
    gate, _, _, _ = _gate()
    artifact = Artifact(
        path="a.md", issue_id="9", branch="feature/issue-9-widget", raw=ARTIFACT_BODY
    )
    # exercise both pass + fail rows and the artifact panel
    gate.render(_pr(), diff="- old\n+ new\n", checks=[passing("ruff"), failing("pytest")],
                artifact=artifact, ci_status="green")


def test_render_without_artifact():
    gate, _, _, _ = _gate()
    gate.render(_pr(), diff="", checks=[passing()], artifact=None)


def test_build_review_reports_lane_pending():
    with pytest.raises(LanePending) as exc:
        build_review(make_config())
    assert exc.value.component == "git"
    assert "Lane B" in exc.value.where
