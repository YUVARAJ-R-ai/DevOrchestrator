"""Artifact parsing, watching, and contract conversion (issues #8, #10).

``contracts.Artifact`` is a thin frozen value object, so the section-by-section
parsing needed to render and gate the plan lives in Lane C's ``ParsedArtifact``.
These tests pin both, and the conversion between them.
"""

from __future__ import annotations

import threading
import time

import pytest

from devorchestrator import contracts
from devorchestrator.sessions.artifact import (
    ParsedArtifact,
    load_artifact,
    wait_for_artifact,
)
from devorchestrator.sessions.tmux_runner import (
    SessionKind,
    SessionState,
    SessionStatus,
    artifact_path,
)

SAMPLE = """\
# Artifact: Add JWT login endpoint
_Issue: 42 | Branch: feature/issue-42-add-jwt-login | Generated: 2026-07-30_

## Context
- Existing auth pattern: `src/middleware/auth.py` uses sessions
- JWT library already installed: python-jose==3.3.0
- Risk: session store is not thread-safe

## Sub-tasks
- [x] Create User model with email + hashed password
- [ ] Implement JWT generation helper
- [ ] Add POST /auth/login endpoint

## Files to Create / Modify
- `src/models/user.py` — add User model
- `src/routes/auth.py` — new file, login + register
- `tests/test_auth.py` — new file, covers both endpoints

## Acceptance Criteria
- [ ] User receives a JWT on login
- [ ] Protected routes return 401 without a valid token

## Implementation Notes
- Chose stateless JWT over Redis to avoid new infra.
"""


@pytest.fixture
def artifact() -> ParsedArtifact:
    return ParsedArtifact.from_markdown(SAMPLE)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_title_and_metadata(artifact: ParsedArtifact):
    assert artifact.title == "Add JWT login endpoint"
    assert artifact.issue_id == "42"
    assert artifact.branch == "feature/issue-42-add-jwt-login"


def test_sections_parse(artifact: ParsedArtifact):
    assert len(artifact.context) == 3
    assert len(artifact.subtasks) == 3
    assert len(artifact.files) == 3
    assert len(artifact.acceptance_criteria) == 2
    assert len(artifact.notes) == 1


def test_checkbox_state_and_progress(artifact: ParsedArtifact):
    assert artifact.subtasks[0].done is True
    assert artifact.subtasks[1].done is False
    assert artifact.progress == (1, 3)


def test_file_paths_strip_backticks_and_keep_notes(artifact: ParsedArtifact):
    assert artifact.files[0].path == "src/models/user.py"
    assert artifact.files[0].note == "add User model"
    assert artifact.files[0].action == "modify"
    assert artifact.files[1].action == "create"


def test_raw_is_preserved_verbatim(artifact: ParsedArtifact):
    """The impl session reads the file; raw must never be a re-serialization."""
    assert artifact.raw == SAMPLE


def test_usability_gate():
    assert ParsedArtifact.from_markdown(SAMPLE).is_usable
    stub = "# Artifact: Nothing\n\n## Context\n- still thinking\n"
    assert not ParsedArtifact.from_markdown(stub).is_usable


def test_unknown_sections_are_ignored_not_fatal():
    parsed = ParsedArtifact.from_markdown(SAMPLE + "\n## Invented Section\n- surprise\n")
    assert parsed.progress == (1, 3)


def test_bullets_without_checkboxes_still_parse_as_subtasks():
    text = "# Artifact: x\n\n## Sub-tasks\n- do the thing\n- do the other thing\n"
    assert len(ParsedArtifact.from_markdown(text).subtasks) == 2


# ---------------------------------------------------------------------------
# Contract conversion
# ---------------------------------------------------------------------------


def test_to_contract_produces_the_frozen_type(artifact: ParsedArtifact):
    converted = artifact.to_contract()
    assert isinstance(converted, contracts.Artifact)
    assert converted.issue_id == "42"
    assert converted.branch == "feature/issue-42-add-jwt-login"
    assert converted.raw == SAMPLE
    # modules_affected must be a tuple — the contract is frozen/hashable
    assert converted.modules_affected == ("models", "routes", "test_auth.py")
    assert isinstance(converted.modules_affected, tuple)


def test_to_contract_overrides_win(artifact: ParsedArtifact):
    converted = artifact.to_contract(issue_id="99", branch="feature/issue-99-other")
    assert converted.issue_id == "99"
    assert converted.branch == "feature/issue-99-other"


def test_load_artifact_returns_none_when_absent(tmp_path):
    assert load_artifact("feature/issue-1-nope", root=tmp_path) is None


def test_load_artifact_reads_the_contract_type(tmp_path):
    branch = "feature/issue-42-add-jwt-login"
    artifact_path(branch, root=tmp_path).write_text(SAMPLE, encoding="utf-8")

    loaded = load_artifact(branch, issue_id="42", root=tmp_path)
    assert isinstance(loaded, contracts.Artifact)
    assert loaded.path.endswith("artifact.md")
    assert loaded.modules_affected


# ---------------------------------------------------------------------------
# Watcher
# ---------------------------------------------------------------------------


def test_watcher_returns_artifact_once_the_file_settles(tmp_path):
    branch = "feature/issue-42-x"
    target = artifact_path(branch, root=tmp_path)

    def write_later():
        time.sleep(0.15)
        target.write_text(SAMPLE, encoding="utf-8")

    threading.Thread(target=write_later, daemon=True).start()
    result = wait_for_artifact(branch, timeout=10, poll=0.05, root=tmp_path)

    assert result is not None
    assert result.progress == (1, 3)


def test_watcher_times_out_when_nothing_is_written(tmp_path):
    assert wait_for_artifact("feature/issue-1-x", timeout=0.3, poll=0.05, root=tmp_path) is None


def test_watcher_rejects_a_stub_artifact(tmp_path):
    branch = "feature/issue-1-x"
    artifact_path(branch, root=tmp_path).write_text("# Artifact: stub\n", encoding="utf-8")
    assert wait_for_artifact(branch, timeout=2, poll=0.05, root=tmp_path) is None


def test_watcher_accepts_a_stub_when_usability_is_not_required(tmp_path):
    branch = "feature/issue-1-x"
    artifact_path(branch, root=tmp_path).write_text("# Artifact: stub\n", encoding="utf-8")
    assert (
        wait_for_artifact(branch, timeout=2, poll=0.05, root=tmp_path, require_usable=False)
        is not None
    )


def test_watcher_gives_up_early_when_the_session_died(tmp_path):
    """Waiting out a 30-minute timeout for a file nobody will write is the
    worst possible demo failure."""
    dead = SessionState(
        kind=SessionKind.research, branch="feature/issue-1-d", status=SessionStatus.failed
    )
    started = time.monotonic()
    result = wait_for_artifact(
        "feature/issue-1-d", timeout=10, poll=0.05, root=tmp_path, session=dead
    )
    assert result is None
    assert time.monotonic() - started < 2  # returned early, not at the timeout
