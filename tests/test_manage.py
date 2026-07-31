"""tmux session management: listing, reaping, killing (issue #60).

The pure logic (what counts as stale, what is safe to kill, how a session name
maps back to a branch) is tested with tmux stubbed out, so these run anywhere.
The real-tmux behaviour is covered by the integration tests in
``test_sessions.py``.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from devorchestrator.cli import app
from devorchestrator.sessions import manage
from devorchestrator.sessions.manage import (
    SessionInfo,
    kill_session,
    list_sessions,
    reap_stale_sessions,
)

runner = CliRunner()


@pytest.fixture
def fake_tmux(monkeypatch):
    """Stub ``manage._tmux``. Records kill-session calls for assertions."""

    class Fake:
        def __init__(self) -> None:
            self.sessions: dict[str, tuple[int, bool]] = {}  # name -> (panes, all_dead)
            self.attached: set[str] = set()
            self.killed: list[str] = []
            self.available = True

        def install(self) -> None:
            monkeypatch.setattr(manage, "_tmux", self)
            monkeypatch.setattr(manage.shutil, "which", lambda _: "/usr/bin/tmux")

        def __call__(self, *args: str, timeout: float = 10.0) -> tuple[int, str]:
            if not self.available:
                return 1, ""
            if args[0] == "list-sessions":
                lines = [
                    f"{name}\t1\t{'1' if name in self.attached else '0'}"
                    for name in self.sessions
                ]
                return 0, "\n".join(lines)
            if args[0] == "list-panes":
                name = args[args.index("-t") + 1]
                panes, all_dead = self.sessions.get(name, (0, False))
                return 0, "\n".join(["1" if all_dead else "0"] * panes)
            if args[0] == "kill-session":
                name = args[args.index("-t") + 1]
                self.killed.append(name)
                self.sessions.pop(name, None)
                return 0, ""
            return 1, ""

    fake = Fake()
    fake.install()
    return fake


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def test_only_orchestrator_sessions_are_listed(fake_tmux):
    """A dev's own tmux sessions must never show up, let alone be reapable."""
    fake_tmux.sessions = {"do-feature-issue-60-x": (2, False), "my-own-work": (1, False)}

    names = [s.name for s in list_sessions()]
    assert names == ["do-feature-issue-60-x"]


def test_no_tmux_means_no_sessions(fake_tmux):
    fake_tmux.available = False
    assert list_sessions() == []


def test_branch_is_recovered_from_the_work_dir_marker(tmp_path, fake_tmux):
    """Session names replace '/' with '-', so they cannot be reversed."""
    from devorchestrator.sessions.tmux_runner import work_dir

    work_dir("feature/issue-60-auto-attach", root=tmp_path)
    fake_tmux.sessions = {"do-feature-issue-60-auto-attach": (1, False)}

    assert list_sessions(root=tmp_path)[0].branch == "feature/issue-60-auto-attach"


# ---------------------------------------------------------------------------
# Staleness + reaping
# ---------------------------------------------------------------------------


def test_a_session_with_all_panes_dead_is_stale():
    assert SessionInfo(name="do-x", panes=2, dead_panes=2).stale


def test_a_running_session_is_not_stale():
    assert not SessionInfo(name="do-x", panes=2, dead_panes=1).stale


def test_an_attached_session_is_never_stale():
    """Killing one out from under a dev reading the output is worse than leaving it."""
    assert not SessionInfo(name="do-x", panes=2, dead_panes=2, attached=True).stale


def test_reap_kills_only_the_finished_sessions(fake_tmux):
    fake_tmux.sessions = {
        "do-finished": (2, True),
        "do-running": (2, False),
        "do-watched": (2, True),
    }
    fake_tmux.attached = {"do-watched"}

    assert reap_stale_sessions() == ["do-finished"]
    assert fake_tmux.killed == ["do-finished"]


def test_reap_is_a_no_op_when_nothing_is_finished(fake_tmux):
    fake_tmux.sessions = {"do-running": (1, False)}
    assert reap_stale_sessions() == []
    assert fake_tmux.killed == []


# ---------------------------------------------------------------------------
# Killing
# ---------------------------------------------------------------------------


def test_kill_refuses_names_outside_the_orchestrator_namespace(fake_tmux):
    """Reachable from a CLI flag — a typo must not kill a dev's own session."""
    fake_tmux.sessions = {"my-own-work": (1, False)}

    assert kill_session("my-own-work") is False
    assert fake_tmux.killed == []


def test_kill_removes_an_orchestrator_session(fake_tmux):
    fake_tmux.sessions = {"do-feature-x": (1, True)}
    assert kill_session("do-feature-x") is True
    assert fake_tmux.killed == ["do-feature-x"]


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_sessions_command_lists_running_sessions(fake_tmux):
    fake_tmux.sessions = {"do-feature-issue-60-x": (2, False)}

    result = runner.invoke(app, ["sessions"])
    assert result.exit_code == 0
    assert "do-feature-issue-60-x" in result.stdout


def test_sessions_command_reports_an_empty_list(fake_tmux):
    result = runner.invoke(app, ["sessions"])
    assert result.exit_code == 0
    assert "No orchestrator sessions" in result.stdout


def test_sessions_command_needs_no_config(fake_tmux, tmp_path, monkeypatch):
    """Talks only to tmux — it must work in a workspace with no yaml."""
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["sessions"]).exit_code == 0


def test_sessions_reap_flag_reports_what_it_killed(fake_tmux):
    fake_tmux.sessions = {"do-done": (1, True)}

    result = runner.invoke(app, ["sessions", "--reap"])
    assert result.exit_code == 0
    assert "do-done" in result.stdout


def test_sessions_kill_flag_rejects_a_foreign_session(fake_tmux):
    fake_tmux.sessions = {"someone-elses": (1, False)}

    result = runner.invoke(app, ["sessions", "--kill", "someone-elses"])
    assert result.exit_code == 1
    assert fake_tmux.killed == []
