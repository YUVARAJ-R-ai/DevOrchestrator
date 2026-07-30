"""Spawn and monitor agent sessions in visible tmux panes (issue #8).

The dev watching the pane is a feature, not overhead — so tmux is the default
runtime. But ``libtmux`` is an optional extra (``pip install devorchestrator[agent]``)
and tmux itself is not on every box, so this module degrades to a plain
subprocess with a tee'd log rather than failing.

:class:`ClaudeSession` is the Lane C implementation of
:class:`devorchestrator.contracts.AgentSession` — ``run(prompt)`` / ``is_alive()``
are the contract; everything else here is Lane C internal.

Completion is detected with an **exit-code sentinel file** (``<cmd>; echo $? > run.exit``)
rather than tmux pane introspection: that is version-agnostic across libtmux
releases and behaves identically headless, which matters because a live demo
cannot afford a runtime-specific surprise.

This module also owns the workspace layout (``.orchestrator/{branch}/…``) that
the rest of Lane C reads and writes.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from rich.console import Console

__all__ = [
    "ClaudeSession",
    "SessionKind",
    "SessionState",
    "SessionStatus",
    "TmuxRunner",
    "artifact_path",
    "prompt_path",
    "tmux_available",
    "work_dir",
]

console = Console()

#: Root for per-branch orchestrator state. Matches ``MeshConfig.db_path``'s
#: default directory in ``config.py``, so all runtime state lives in one place.
ORCHESTRATOR_DIR = Path(".orchestrator")

#: Extra flags passed to ``claude -p``. A non-interactive session must be able
#: to edit files without a human confirming each write, or the loop stalls
#: unseen. Overridable for stricter policy:
#: ``DEVORCH_CLAUDE_ARGS="--permission-mode plan"``.
DEFAULT_CLAUDE_ARGS = ("--permission-mode", "acceptEdits")


class SessionKind(StrEnum):
    research = "research"
    impl = "impl"
    autofix = "autofix"


class SessionStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    timeout = "timeout"


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class SessionState:
    """Lane C's internal record of one agent run.

    Deliberately not a contract type: other lanes only need
    :class:`~devorchestrator.contracts.AgentSession` (`run`/`is_alive`) and the
    :class:`~devorchestrator.contracts.Artifact` that comes out the far end.
    """

    kind: SessionKind
    branch: str
    command: str = ""
    cwd: Path | None = None
    headless: bool = False
    tmux_session: str | None = None
    tmux_window: str | None = None
    status: SessionStatus = SessionStatus.pending
    exit_code: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    log_path: Path | None = None
    error: str | None = None
    _extra: dict = field(default_factory=dict, repr=False)

    @property
    def name(self) -> str:
        """Pane/window label, e.g. ``research-feature/issue-8-tmux``."""
        return f"{self.kind.value}-{self.branch}"

    @property
    def ok(self) -> bool:
        return self.status is SessionStatus.completed and (self.exit_code or 0) == 0

    @property
    def duration_s(self) -> float:
        if self.started_at is None:
            return 0.0
        return ((self.finished_at or _utcnow()) - self.started_at).total_seconds()


# ---------------------------------------------------------------------------
# Workspace layout
# ---------------------------------------------------------------------------


def work_dir(branch: str, *, root: Path | None = None, create: bool = True) -> Path:
    """``.orchestrator/{branch}/`` — artifacts, prompts, and logs for one task."""
    path = (root or ORCHESTRATOR_DIR) / branch
    if create:
        path.mkdir(parents=True, exist_ok=True)
        # Branch names contain slashes, so the directory path alone is lossy.
        # This marker lets `status` recover the branch a work dir belongs to.
        marker = path / ".do-branch"
        if not marker.is_file():
            marker.write_text(branch + "\n", encoding="utf-8")
    return path


def artifact_path(branch: str, *, root: Path | None = None) -> Path:
    """The one path the research and implementation sessions both agree on."""
    return work_dir(branch, root=root) / "artifact.md"


def prompt_path(branch: str, kind: SessionKind, *, root: Path | None = None) -> Path:
    return work_dir(branch, root=root) / f"{kind.value}-prompt.txt"


# ---------------------------------------------------------------------------
# Command construction
# ---------------------------------------------------------------------------


def tmux_available() -> bool:
    """True when both a tmux binary and the optional ``libtmux`` extra exist."""
    if not shutil.which("tmux"):
        return False
    try:
        import libtmux  # noqa: F401
    except ImportError:
        return False
    return True


def _claude_args() -> list[str]:
    override = os.environ.get("DEVORCH_CLAUDE_ARGS")
    return shlex.split(override) if override else list(DEFAULT_CLAUDE_ARGS)


def claude_command(prompt_file: Path, *, binary: str = "claude") -> str:
    """Shell command feeding a prompt *file* to the agent CLI.

    The prompt goes through a file rather than an inline argument: research
    prompts embed the whole artifact schema and would risk the shell's
    argument-length limit.
    """
    args = " ".join(shlex.quote(a) for a in _claude_args())
    return f"{shlex.quote(binary)} -p {args} \"$(cat {shlex.quote(str(prompt_file))})\""


def _tmux_name(branch: str) -> str:
    """tmux rejects ``.`` and ``:`` in names and handles ``/`` awkwardly."""
    return branch.replace("/", "-").replace(".", "-").replace(":", "-")


def _set_remain_on_exit(window) -> None:
    """Keep a finished pane on screen instead of letting it vanish.

    Best-effort across libtmux versions — the option name moved between
    ``set_window_option`` and ``set_option``, and losing it only costs pane
    persistence, never correctness (completion is tracked by sentinel file).
    """
    for attempt in (
        # Modern libtmux first; set_window_option is deprecated but is the only
        # spelling on older releases, and raw tmux works whatever the bindings do.
        lambda: window.set_option("remain-on-exit", "on"),
        lambda: window.set_window_option("remain-on-exit", "on"),
        lambda: window.cmd("set-option", "-w", "remain-on-exit", "on"),
    ):
        try:
            attempt()
            return
        except Exception:  # noqa: BLE001 — try the next spelling
            continue


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class TmuxRunner:
    """Spawns agent runs as named tmux windows the dev can watch live.

    One tmux session per branch (``do-{branch}``), one window per run
    (``research-…``, ``impl-…``), so a dev attaches once and sees the whole
    task's history.
    """

    def __init__(
        self,
        *,
        branch: str,
        cwd: Path | None = None,
        agent: str = "claude",
        force_headless: bool = False,
        root: Path | None = None,
    ) -> None:
        self.branch = branch
        self.cwd = Path(cwd or Path.cwd()).resolve()
        self.agent = agent
        self.root = root
        self.session_name = f"do-{_tmux_name(branch)}"
        self.headless = force_headless or not tmux_available()
        self._server = None
        self._tmux_session = None
        self._processes: dict[SessionKind, subprocess.Popen] = {}

    # -- lifecycle ---------------------------------------------------------

    def spawn(self, kind: SessionKind, command: str) -> SessionState:
        """Start ``command`` and return immediately with a running state."""
        wd = work_dir(self.branch, root=self.root)
        exit_file = wd / f"{kind.value}.exit"
        log_file = wd / f"{kind.value}.log"
        # A leftover sentinel would make the next run look instantly complete.
        exit_file.unlink(missing_ok=True)

        state = SessionState(
            kind=kind,
            branch=self.branch,
            command=command,
            cwd=self.cwd,
            headless=self.headless,
            log_path=log_file,
            status=SessionStatus.running,
            started_at=_utcnow(),
        )

        # Tee output so autofix (#12) and the review gate (#4) can read what the
        # agent actually said, not just its exit code.
        wrapped = (
            f"{{ {command} ; }} 2>&1 | tee {shlex.quote(str(log_file))} ; "
            f"echo ${{PIPESTATUS[0]}} > {shlex.quote(str(exit_file))}"
        )

        try:
            if self.headless:
                self._spawn_headless(wrapped, state)
            else:
                self._spawn_tmux(wrapped, state)
        except Exception as exc:  # noqa: BLE001 — a spawn failure is reported, never raised
            state.status = SessionStatus.failed
            state.error = f"{type(exc).__name__}: {exc}"
            state.finished_at = _utcnow()
            console.print(f"[red]Failed to start {state.name}:[/red] {state.error}")
        return state

    def _spawn_tmux(self, command: str, state: SessionState) -> None:
        import libtmux

        self._server = self._server or libtmux.Server()
        window_name = f"{state.kind.value}-{_tmux_name(self.branch)}"

        if self._tmux_session is None:
            # Reuse the branch's session if it already exists, so research and
            # impl windows accumulate and a dev who attaches sees the whole
            # task. Creating with kill_session=True would discard the research
            # pane the moment implementation starts.
            self._tmux_session = self._attach_or_create(window_name)
            window = self._tmux_session.active_window
            if window.window_name != window_name:
                window = self._new_window(window_name)
        else:
            window = self._new_window(window_name)

        # Panes are exec'd, so they die the instant the agent exits — taking
        # their output, and the whole session, with them. remain-on-exit keeps
        # the finished pane on screen holding its final output, which is the
        # entire point of running visibly.
        _set_remain_on_exit(window)

        # bash -o pipefail so PIPESTATUS is meaningful whatever the login shell.
        window.active_pane.send_keys(f"exec bash -o pipefail -c {shlex.quote(command)}", enter=True)

        state.tmux_session = self.session_name
        state.tmux_window = window_name
        console.print(
            f"[cyan]›[/cyan] {state.name} running in tmux — "
            f"watch it: [bold]tmux attach -t {self.session_name}[/bold]"
        )

    def _attach_or_create(self, window_name: str):
        """Return the branch's tmux session, creating it only if absent."""
        try:
            if self._server.has_session(self.session_name):
                return self._server.sessions.get(session_name=self.session_name)
        except Exception:  # noqa: BLE001 — a lookup failure just means "create it"
            pass
        return self._server.new_session(
            session_name=self.session_name,
            start_directory=str(self.cwd),
            window_name=window_name,
            attach=False,
        )

    def _new_window(self, window_name: str):
        return self._tmux_session.new_window(
            window_name=window_name, start_directory=str(self.cwd), attach=False
        )

    def _spawn_headless(self, command: str, state: SessionState) -> None:
        self._processes[state.kind] = subprocess.Popen(  # noqa: S602 — parts are shlex-quoted
            ["bash", "-o", "pipefail", "-c", command],
            cwd=str(self.cwd),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        console.print(
            f"[cyan]›[/cyan] {state.name} running headless "
            f"[dim](tmux unavailable — output tees to {state.log_path})[/dim]"
        )

    # -- monitoring --------------------------------------------------------

    def exit_code(self, kind: SessionKind) -> int | None:
        """Read the sentinel, tolerating a partially-flushed write."""
        path = work_dir(self.branch, root=self.root) / f"{kind.value}.exit"
        try:
            text = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return None
        return int(text) if text.isdigit() else None

    def is_alive(self, state: SessionState) -> bool:
        if state.status is not SessionStatus.running:
            return False
        if self.exit_code(state.kind) is not None:
            return False
        process = self._processes.get(state.kind)
        if self.headless and process is not None and process.poll() is not None:
            return False
        return True

    def wait(
        self,
        state: SessionState,
        *,
        timeout: float = 1800.0,
        poll: float = 1.0,
        on_tick: Callable[[SessionState], None] | None = None,
    ) -> SessionState:
        """Block until the run writes its exit sentinel, or time out."""
        if state.status is not SessionStatus.running:
            return state

        deadline = time.monotonic() + timeout
        process = self._processes.get(state.kind)

        while time.monotonic() < deadline:
            code = self.exit_code(state.kind)
            if code is not None:
                state.exit_code = code
                state.status = SessionStatus.completed if code == 0 else SessionStatus.failed
                state.finished_at = _utcnow()
                return state

            if self.headless and process is not None and process.poll() is not None:
                # Shell died before writing the sentinel.
                state.exit_code = process.returncode
                state.status = (
                    SessionStatus.completed if not process.returncode else SessionStatus.failed
                )
                state.finished_at = _utcnow()
                return state

            if on_tick:
                on_tick(state)
            time.sleep(poll)

        state.status = SessionStatus.timeout
        state.error = f"no completion after {timeout:.0f}s"
        state.finished_at = _utcnow()
        return state

    def capture(self, state: SessionState, *, lines: int = 60) -> str:
        """Recent output, from the tee'd log — works in both runtimes."""
        if state.log_path and Path(state.log_path).is_file():
            text = Path(state.log_path).read_text(encoding="utf-8", errors="replace")
            return "\n".join(text.splitlines()[-lines:])
        return ""

    def kill(self) -> None:
        """Tear down the tmux session and any headless processes. Never raises."""
        try:
            if self._tmux_session is not None:
                self._tmux_session.kill()
        except Exception:  # noqa: BLE001 — teardown is best-effort
            pass
        for process in self._processes.values():
            if process.poll() is None:
                process.terminate()


class ClaudeSession:
    """Lane C's :class:`~devorchestrator.contracts.AgentSession` implementation.

    The contract is deliberately tiny (``run`` / ``is_alive``) so the pipeline
    can drive a session without knowing about tmux. Everything richer — exit
    codes, timings, captured output — stays on ``.state`` for Lane C's own use.
    """

    def __init__(
        self,
        kind: SessionKind,
        *,
        branch: str,
        cwd: Path | None = None,
        agent: str = "claude",
        headless: bool = False,
        root: Path | None = None,
        runner: TmuxRunner | None = None,
    ) -> None:
        self.kind = kind
        self.branch = branch
        self.root = root
        self.runner = runner or TmuxRunner(
            branch=branch, cwd=cwd, agent=agent, force_headless=headless, root=root
        )
        self.state = SessionState(kind=kind, branch=branch)

    # -- AgentSession protocol --------------------------------------------

    def run(self, prompt: str) -> None:
        """Write ``prompt`` to the workspace and spawn the agent on it."""
        path = prompt_path(self.branch, self.kind, root=self.root)
        path.write_text(prompt, encoding="utf-8")
        self.run_prompt_file(path)

    def is_alive(self) -> bool:
        return self.runner.is_alive(self.state)

    # -- Lane C extras -----------------------------------------------------

    def run_prompt_file(self, path: Path) -> SessionState:
        """Spawn against an already-rendered prompt file."""
        self.state = self.runner.spawn(self.kind, claude_command(path, binary=self.runner.agent))
        return self.state

    def wait(self, *, timeout: float = 1800.0, poll: float = 1.0) -> SessionState:
        self.state = self.runner.wait(self.state, timeout=timeout, poll=poll)
        return self.state

    def capture(self, *, lines: int = 60) -> str:
        return self.runner.capture(self.state, lines=lines)

    def kill(self) -> None:
        self.runner.kill()
