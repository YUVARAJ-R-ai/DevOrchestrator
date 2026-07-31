"""Rate-limit detection and retry for agent sessions (issue #52).

A throttled agent has not failed — it has been told to wait. Losing a long
research session to a usage limit means losing the artifact and starting over,
so ``ClaudeSession.run`` retries with backoff and only gives up after the budget
is spent.
"""

from __future__ import annotations

import pytest

from devorchestrator.sessions.tmux_runner import (
    ClaudeSession,
    RateLimited,
    SessionFailed,
    SessionKind,
    artifact_path,
    is_rate_limited,
)


class FakeMesh:
    """Records emits. Structurally satisfies the ``Mesh`` protocol's ``emit``."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, event_type: str, module: str, payload: dict) -> None:
        self.events.append((event_type, module, payload))

    def payloads(self, event_type: str) -> list[dict]:
        return [p for t, _, p in self.events if t == event_type]


def fake_agent(tmp_path, body: str, *, name: str = "fake-agent") -> str:
    """An executable stand-in for the ``claude`` binary.

    Has to be a real script on disk: passing a shell one-liner as ``agent`` only
    looks like it works — the runner ``shlex.quote``s the binary, bash reports
    ``command not found``, and the error message *repeats the binary name*. A
    test whose fake agent is named "...usage limit reached" then matches the
    rate-limit detector against bash's complaint instead of any agent output,
    and passes without ever exercising the code under test.
    """
    path = tmp_path / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return str(path)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Claude AI usage limit reached",
        "Error: rate limit exceeded",
        "HTTP 429 Too Many Requests",
        "overloaded_error",
        "quota exceeded for this key",
    ],
)
def test_rate_limit_signatures_are_detected(text):
    assert is_rate_limited(text)


@pytest.mark.parametrize(
    "text",
    ["", "TypeError: undefined is not a function", "pytest: 3 failed", "ruff: F821"],
)
def test_ordinary_failures_are_not_mistaken_for_throttling(text):
    """A false positive costs one wasted retry; misreading a real bug as a
    rate limit would retry the same broken run three times."""
    assert not is_rate_limited(text)


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


def test_a_throttled_session_is_retried_with_backoff(tmp_path):
    slept: list[float] = []
    session = ClaudeSession(
        SessionKind.research,
        branch="feature/issue-52-retry",
        cwd=tmp_path,
        # Prints a throttle signature, then fails — the shape of a real limit.
        agent=fake_agent(tmp_path, 'echo "Claude AI usage limit reached"; exit 1'),
        headless=True,
        root=tmp_path,
        rate_limit_retries=2,
        sleep=slept.append,
    )

    with pytest.raises(RateLimited):
        session.run("a prompt")

    assert slept == [60.0, 120.0], "backoff should double between attempts"
    # Guards the trap described on `fake_agent`: the detector must have matched
    # the agent's own output, not a shell "command not found" that happens to
    # quote a binary named after a rate-limit message.
    log = session.capture()
    assert "Claude AI usage limit reached" in log
    assert "command not found" not in log


def test_rate_limited_is_catchable_as_session_failed():
    """Existing callers only know SessionFailed; they must keep working."""
    assert issubclass(RateLimited, SessionFailed)


def test_a_normal_failure_is_not_retried(tmp_path):
    slept: list[float] = []
    session = ClaudeSession(
        SessionKind.impl,
        branch="feature/issue-52-plain",
        cwd=tmp_path,
        agent="false",
        headless=True,
        root=tmp_path,
        rate_limit_retries=3,
        sleep=slept.append,
    )

    with pytest.raises(SessionFailed) as exc:
        session.run("a prompt")

    assert not isinstance(exc.value, RateLimited)
    assert slept == [], "a real failure must not burn the retry budget"


def test_a_successful_session_never_sleeps(tmp_path):
    slept: list[float] = []
    ClaudeSession(
        SessionKind.research,
        branch="feature/issue-52-ok",
        cwd=tmp_path,
        agent="echo",
        headless=True,
        root=tmp_path,
        sleep=slept.append,
    ).run("a prompt")

    assert slept == []


def test_partial_work_survives_a_rate_limited_run(tmp_path):
    """Acceptance criterion: the artifact is preserved, not discarded."""
    branch = "feature/issue-52-partial"
    artifact = artifact_path(branch, root=tmp_path)
    artifact.write_text("# partial plan the agent got through\n", encoding="utf-8")

    session = ClaudeSession(
        SessionKind.research,
        branch=branch,
        cwd=tmp_path,
        agent=fake_agent(tmp_path, 'echo "rate limit"; exit 1'),
        headless=True,
        root=tmp_path,
        rate_limit_retries=1,
        sleep=lambda _: None,
    )
    with pytest.raises(RateLimited):
        session.run("a prompt")

    assert artifact.is_file()
    assert "partial plan" in artifact.read_text()


# ---------------------------------------------------------------------------
# Mesh reporting — rides on #56's lifecycle emitter
# ---------------------------------------------------------------------------


def test_the_retry_is_reported_to_the_mesh(tmp_path):
    """From the mesh's side a throttled retry is otherwise indistinguishable
    from a session that simply ran long."""
    mesh = FakeMesh()
    session = ClaudeSession(
        SessionKind.research,
        branch="feature/issue-52-mesh",
        cwd=tmp_path,
        agent=fake_agent(tmp_path, 'echo "rate limit"; exit 1'),
        headless=True,
        root=tmp_path,
        mesh=mesh,
        dev="ragav",
        rate_limit_retries=1,
        sleep=lambda _: None,
    )
    with pytest.raises(RateLimited):
        session.run("a prompt")

    limited = mesh.payloads("session_rate_limited")
    assert len(limited) == 1
    assert limited[0]["backoff_s"] == 60.0
    assert limited[0]["dev"] == "ragav"


def test_each_retry_reports_its_own_session_lifecycle(tmp_path):
    """One session_started/ended pair per attempt, so a retried run does not
    look like a single session that mysteriously took twice as long."""
    mesh = FakeMesh()
    session = ClaudeSession(
        SessionKind.research,
        branch="feature/issue-52-pairs",
        cwd=tmp_path,
        agent=fake_agent(tmp_path, 'echo "rate limit"; exit 1'),
        headless=True,
        root=tmp_path,
        mesh=mesh,
        dev="ragav",
        rate_limit_retries=1,
        sleep=lambda _: None,
    )
    with pytest.raises(RateLimited):
        session.run("a prompt")

    assert len(mesh.payloads("session_started")) == 2
    assert len(mesh.payloads("session_ended")) == 2


def test_a_dead_mesh_never_breaks_the_retry_path(tmp_path):
    class BrokenMesh:
        def emit(self, *args, **kwargs):
            raise RuntimeError("mesh is down")

    session = ClaudeSession(
        SessionKind.research,
        branch="feature/issue-52-broken-mesh",
        cwd=tmp_path,
        agent="echo",
        headless=True,
        root=tmp_path,
        mesh=BrokenMesh(),
        dev="ragav",
    )
    session.run("this must still succeed")
    assert session.state.ok
