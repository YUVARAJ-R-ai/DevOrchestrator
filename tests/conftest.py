"""Shared fakes + fixtures for pipeline/review tests.

The fakes implement the `contracts` Protocols *structurally* — they never import
another lane's code, exactly as the real adapters won't need to. This is what lets
the whole Spine be driven end-to-end before Lane B/C/D exist.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from devorchestrator.config import Config
from devorchestrator.contracts import (
    BranchRef,
    CheckResult,
    CheckStatus,
    DevActivity,
    Issue,
    MergeStrategy,
    PullRequest,
)

ARTIFACT_BODY = """\
# Artifact: Test task

## Files to Create/Modify
- `src/devorchestrator/widget.py` — new widget
- `tests/test_widget.py` — tests
"""


def make_config(**over) -> Config:
    data = {
        "name": "tester",
        "board": {"type": "plane", "url": "http://board", "token_env": "B"},
        "git": {"type": "gitea", "url": "http://git", "token_env": "G"},
    }
    data.update(over)
    return Config.model_validate(data)


class FakeBoard:
    def __init__(self, issues: list[Issue]) -> None:
        self._issues = issues
        self.moved: list[tuple[str, str]] = []

    def fetch_issues(self) -> list[Issue]:
        return self._issues

    def move_issue(self, issue_id: str, state) -> None:
        self.moved.append((issue_id, str(state)))


class FakeGit:
    def __init__(self, branch: BranchRef) -> None:
        self._branch = branch
        self.merged: list[tuple[PullRequest, MergeStrategy]] = []
        self.opened: PullRequest | None = None

    def create_branch(self, issue: Issue, base: str = "dev") -> BranchRef:
        return self._branch

    def open_pr(self, branch: BranchRef, title: str, body: str) -> PullRequest:
        self.opened = PullRequest(number=7, title=title, url="http://git/pr/7", branch=branch.name)
        return self.opened

    def merge_pr(self, pr: PullRequest, strategy: MergeStrategy) -> None:
        self.merged.append((pr, strategy))


class FakeSession:
    """Records prompts. Optionally writes an artifact file to simulate research."""

    def __init__(self, write_path: Path | None = None, content: str = "") -> None:
        self.prompts: list[str] = []
        self._write_path = write_path
        self._content = content

    def run(self, prompt: str) -> None:
        self.prompts.append(prompt)
        if self._write_path is not None:
            self._write_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_path.write_text(self._content, encoding="utf-8")

    def is_alive(self) -> bool:
        return False


class FakeChecks:
    """Returns a preset sequence of result batches, one per run_all() call."""

    def __init__(self, batches: list[list[CheckResult]]) -> None:
        self._batches = list(batches)
        self.calls = 0

    def run_all(self) -> list[CheckResult]:
        self.calls += 1
        batch = self._batches[min(self.calls - 1, len(self._batches) - 1)]
        return batch


class FakeMesh:
    def __init__(self, touching: dict[str, list[DevActivity]] | None = None) -> None:
        self.events: list[tuple[str, str, dict]] = []
        self._touching = touching or {}

    def emit(self, event_type: str, module: str, payload: dict) -> None:
        self.events.append((event_type, module, payload))

    def who_is_touching(self, module: str) -> list[DevActivity]:
        return self._touching.get(module, [])

    def recent_decisions(self, limit: int = 10):
        return []


class FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def notify(self, message: str) -> None:
        self.messages.append(message)


def passing(tool: str = "pytest") -> CheckResult:
    return CheckResult(tool=tool, status=CheckStatus.passed, duration_s=0.1)


def failing(tool: str = "pytest", output: str = "1 failed") -> CheckResult:
    return CheckResult(tool=tool, status=CheckStatus.failed, output=output, duration_s=0.1)


@pytest.fixture
def branch() -> BranchRef:
    return BranchRef(name="feature/issue-9-widget", issue_id="9", base="dev")


@pytest.fixture
def issue() -> Issue:
    return Issue(id="9", title="Add widget", description="build the widget")
