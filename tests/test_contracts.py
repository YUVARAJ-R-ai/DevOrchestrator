"""Tests that pin the frozen contract surface (issue #1).

These exist so a change to contracts.py that would break another lane's
assumptions fails here first — the file is meant to be stable after Wave 1.
"""

from __future__ import annotations

import dataclasses

import pytest

from devorchestrator import contracts as c


def test_issue_branch_slug_matches_naming_convention() -> None:
    issue = c.Issue(id="1", title="Scaffold + contracts.py")
    # feature/issue-<N>-<slug>; punctuation collapses to single hyphens
    assert issue.branch_slug() == "issue-1-scaffold-contracts-py"


def test_issue_slug_is_truncated_and_clean() -> None:
    issue = c.Issue(id="42", title="A" * 100)
    slug = issue.branch_slug()
    assert slug.startswith("issue-42-")
    assert not slug.endswith("-")


def test_check_result_passed_property() -> None:
    ok = c.CheckResult(tool="ruff", status=c.CheckStatus.passed)
    bad = c.CheckResult(tool="pytest", status=c.CheckStatus.failed, output="1 failed")
    assert ok.passed is True
    assert bad.passed is False


def test_value_objects_are_frozen() -> None:
    issue = c.Issue(id="1", title="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        issue.title = "y"  # type: ignore[misc]


def test_pipeline_context_accumulates() -> None:
    ctx = c.PipelineContext(issue=c.Issue(id="1", title="x"))
    # mutable on purpose: stages fill their slice as the loop runs
    ctx.checks.append(c.CheckResult(tool="ruff", status=c.CheckStatus.passed))
    assert len(ctx.checks) == 1
    assert ctx.pull_request is None


def test_adapters_are_runtime_checkable_protocols() -> None:
    class FakeBoard:
        def fetch_issues(self) -> list[c.Issue]:
            return []

        def move_issue(self, issue_id: str, state: c.IssueState) -> None:
            pass

    assert isinstance(FakeBoard(), c.BoardAdapter)
