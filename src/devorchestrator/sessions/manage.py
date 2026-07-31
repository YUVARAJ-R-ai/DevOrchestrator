"""Find, attach to, and clean up orchestrator tmux sessions (issue #60).

Every run leaves a ``do-{branch}`` tmux session behind. With ``remain-on-exit``
keeping finished panes on screen — which is the point, the dev came to read the
output — nothing ever tears them down, so they pile up across tasks until
someone runs ``tmux kill-session`` by hand. That manual cleanup is the workflow
annoyance this module removes.

**Raw ``tmux`` rather than libtmux.** ``tmux_runner`` uses libtmux to *drive*
panes, but everything here only inspects and kills sessions. Shelling out means
``devorchestrator sessions`` works with just the tmux binary, before anyone
installs the optional ``[agent]`` extra, and sidesteps the libtmux API drift the
runner already works around in ``_set_remain_on_exit``.

Nothing here raises on a missing or broken tmux: no tmux simply means no
sessions to manage, which is the correct answer in headless environments.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from devorchestrator.sessions.tmux_runner import ORCHESTRATOR_DIR

__all__ = [
    "SessionInfo",
    "attach_session",
    "kill_session",
    "list_sessions",
    "reap_stale_sessions",
]

#: Every session this tool creates is named ``do-{sanitized-branch}``. The
#: prefix is what keeps us from ever touching a developer's own tmux sessions.
SESSION_PREFIX = "do-"


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """One ``do-*`` tmux session as reported by tmux."""

    name: str
    windows: int = 0
    panes: int = 0
    dead_panes: int = 0
    attached: bool = False
    branch: str | None = None

    @property
    def stale(self) -> bool:
        """Every pane has exited and nobody is watching it.

        Both halves matter: a session whose panes are all dead is finished work,
        but killing one a developer is currently attached to would yank the
        output out from under them mid-read.
        """
        return self.panes > 0 and self.dead_panes == self.panes and not self.attached


def _tmux(*args: str, timeout: float = 10.0) -> tuple[int, str]:
    """Run a tmux command. Returns ``(returncode, stdout)``; never raises."""
    if not shutil.which("tmux"):
        return 1, ""
    try:
        result = subprocess.run(
            ["tmux", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return result.returncode, result.stdout


def _branch_index(root: Path | None = None) -> dict[str, str]:
    """Map ``do-*`` session name → real branch name.

    The session name replaces ``/`` and ``.`` with ``-``, so it cannot be
    reversed. ``work_dir`` drops a ``.do-branch`` marker for exactly this
    reason; read those back to show a real branch in the listing.
    """
    base = root or ORCHESTRATOR_DIR
    index: dict[str, str] = {}
    try:
        markers = list(base.glob("*/*/.do-branch")) + list(base.glob("*/.do-branch"))
    except OSError:
        return index
    for marker in markers:
        try:
            branch = marker.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if branch:
            sanitized = branch.replace("/", "-").replace(".", "-").replace(":", "-")
            index[f"{SESSION_PREFIX}{sanitized}"] = branch
    return index


def list_sessions(*, root: Path | None = None) -> list[SessionInfo]:
    """Every live ``do-*`` tmux session, with pane counts. ``[]`` if tmux is absent."""
    code, out = _tmux(
        "list-sessions", "-F", "#{session_name}\t#{session_windows}\t#{session_attached}"
    )
    if code != 0:
        return []

    index = _branch_index(root)
    sessions: list[SessionInfo] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or not parts[0].startswith(SESSION_PREFIX):
            continue
        name = parts[0]
        panes, dead = _pane_counts(name)
        sessions.append(
            SessionInfo(
                name=name,
                windows=int(parts[1]) if parts[1].isdigit() else 0,
                panes=panes,
                dead_panes=dead,
                attached=parts[2] == "1",
                branch=index.get(name),
            )
        )
    return sessions


def _pane_counts(session: str) -> tuple[int, int]:
    """``(total_panes, dead_panes)`` for a session."""
    code, out = _tmux("list-panes", "-s", "-t", session, "-F", "#{pane_dead}")
    if code != 0:
        return 0, 0
    flags = out.split()
    return len(flags), sum(1 for f in flags if f == "1")


def kill_session(name: str) -> bool:
    """Kill one session. True if tmux reported success."""
    if not name.startswith(SESSION_PREFIX):
        # Refuse anything outside our namespace — this function is reachable
        # from a CLI flag, and a typo must not kill a dev's own tmux session.
        return False
    code, _ = _tmux("kill-session", "-t", name)
    return code == 0


def reap_stale_sessions(*, root: Path | None = None) -> list[str]:
    """Kill every finished, unattached ``do-*`` session. Returns the names killed.

    Called at the start of a run so a dev never has to clean up by hand. Safe to
    call unconditionally: sessions still running, and any session someone is
    attached to, are left alone.
    """
    killed: list[str] = []
    for info in list_sessions(root=root):
        if info.stale and kill_session(info.name):
            killed.append(info.name)
    return killed


def attach_session(name: str) -> int:
    """Attach the current terminal to a session, replacing this process.

    Uses ``execvp`` rather than ``subprocess``: attaching hands the terminal to
    tmux for as long as the dev watches, and leaving a parent Python process
    parked underneath it only creates a second thing to Ctrl-C on the way out.

    Returns non-zero if attaching was not possible; on success it does not
    return at all.
    """
    tmux = shutil.which("tmux")
    if not tmux:
        return 1
    if not os.isatty(0):
        # No terminal to give tmux — happens under CI and inside pytest.
        return 1
    os.execvp(tmux, ["tmux", "attach-session", "-t", name])  # noqa: S606 — name is namespaced
    return 0  # unreachable when exec succeeds
