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
import re
import shlex
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from rich.console import Console

__all__ = [
    "ClaudeSession",
    "RateLimited",
    "SessionFailed",
    "SessionKind",
    "SessionState",
    "SessionStatus",
    "TmuxRunner",
    "artifact_path",
    "is_rate_limited",
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

#: Output signatures that mean "the agent was throttled", not "the work failed"
#: (issue #52). Matched case-insensitively against the tee'd log. Kept broad on
#: purpose: the cost of a false positive is one wasted retry, while the cost of
#: a false negative is losing a long session's work outright.
RATE_LIMIT_PATTERNS = (
    r"rate[ _-]?limit",
    r"usage limit reached",
    r"quota (?:exceeded|exhausted)",
    r"too many requests",
    r"\b429\b",
    r"overloaded_error",
    r"insufficient[_ ]quota",
)

_RATE_LIMIT_RE = re.compile("|".join(RATE_LIMIT_PATTERNS), re.IGNORECASE)

#: Retries after a throttle, and the base for exponential backoff. Three waits
#: of 60s/120s/240s span ~7 minutes, which covers a short rolling-window limit
#: without stalling a demo indefinitely.
DEFAULT_RATE_LIMIT_RETRIES = 3
RATE_LIMIT_BACKOFF_S = 60.0


def is_rate_limited(text: str) -> bool:
    """True when session output carries a throttling signature (issue #52)."""
    return bool(text) and _RATE_LIMIT_RE.search(text) is not None


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
    tmux_pane: str | None = None
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


#: Matches the artifact path every pipeline prompt embeds, e.g.
#: ``.orchestrator/feature/issue-9-widget/artifact.md``.
_ARTIFACT_IN_PROMPT = re.compile(r"(\S+)/artifact\.md")


def _branch_from_prompt(prompt: str) -> str:
    """Recover the branch from the artifact path inside a prompt.

    ``pipeline.py`` constructs sessions before a task is picked, then passes
    prompts that always name ``{workdir}/{branch}/artifact.md``. Rather than
    require Lane A to call :meth:`ClaudeSession.bind`, we read the branch back
    out of the prompt. Branch names are always two components
    (``feature/issue-N-slug``), which is what makes this unambiguous regardless
    of how deep ``workdir`` is.
    """
    match = _ARTIFACT_IN_PROMPT.search(prompt)
    if match:
        parts = [p for p in match.group(1).replace("\\", "/").split("/") if p not in ("", ".")]
        if len(parts) >= 2:
            return "/".join(parts[-2:])
    raise SessionFailed(
        "cannot determine the branch for this session: the prompt names no "
        "'<branch>/artifact.md' path. Call ClaudeSession.bind(branch) first."
    )


def _split_pane(window):
    """Split *window* side-by-side, tolerating libtmux API drift (issue #60).

    ``split_window`` was renamed to ``split`` mid-libtmux-2.x, and the keyword
    for "don't focus it" moved too. Returns ``None`` if no spelling worked, and
    the caller falls back to a separate window — a cramped layout is a far
    better outcome than a session that will not start.
    """
    for attempt in (
        lambda: window.split(attach=False, direction="right"),
        lambda: window.split(attach=False),
        lambda: window.split_window(attach=False, vertical=False),
        lambda: window.split_window(attach=False),
    ):
        try:
            pane = attempt()
        except Exception:  # noqa: BLE001 — try the next spelling
            continue
        if pane is not None:
            return pane
    return None


def _select_layout(window, layout: str = "even-horizontal") -> None:
    """Even out the panes so research and impl get equal width. Best-effort."""
    for attempt in (
        lambda: window.select_layout(layout),
        lambda: window.cmd("select-layout", layout),
    ):
        try:
            attempt()
            return
        except Exception:  # noqa: BLE001 — layout is cosmetic
            continue


def _respawn(pane, command: str) -> bool:
    """Restart a finished pane in place, so repeat runs of one kind reuse it.

    ``remain-on-exit`` leaves a dead pane sitting there holding its last output;
    ``send_keys`` to it does nothing. Without this, every autofix attempt would
    split another pane and the layout would shred after two retries.
    """
    try:
        pane.cmd("respawn-pane", "-k", command)
    except Exception:  # noqa: BLE001 — caller falls back to a fresh split
        return False
    return True


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
        self._window = None
        self._panes: dict[SessionKind, object] = {}
        #: True only when *this* runner created the tmux session. Decides whether
        #: the window's starting pane is free to take or already belongs to
        #: someone else — see :meth:`_pane_for`.
        self._created_session = False
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
        # One window per task, panes split inside it (issue #60): research left,
        # impl right, both visible at once. Previously each kind opened its own
        # window, so watching the agent work meant cycling windows to find the
        # live one — and you could never see the plan and its execution together.
        window_name = _tmux_name(self.branch)

        if self._tmux_session is None:
            # Reuse the branch's session if it already exists, so a dev who
            # attaches sees the whole task. Creating with kill_session=True
            # would discard the research pane the moment implementation starts.
            self._tmux_session = self._attach_or_create(window_name)
        window = self._task_window(window_name)

        # Panes are exec'd, so they die the instant the agent exits — taking
        # their output, and the whole session, with them. remain-on-exit keeps
        # the finished pane on screen holding its final output, which is the
        # entire point of running visibly.
        _set_remain_on_exit(window)

        # bash -o pipefail so PIPESTATUS is meaningful whatever the login shell.
        shell_command = f"exec bash -o pipefail -c {shlex.quote(command)}"
        pane = self._pane_for(state.kind, window, shell_command)

        state.tmux_session = self.session_name
        state.tmux_window = window_name
        state.tmux_pane = str(getattr(pane, "pane_index", "") or "")
        console.print(
            f"[cyan]›[/cyan] {state.name} running in tmux — "
            f"watch it: [bold]tmux attach -t {self.session_name}[/bold]"
        )

    def _task_window(self, window_name: str):
        """The single window all of this task's panes live in."""
        if self._window is not None:
            return self._window
        window = self._tmux_session.active_window
        if window.window_name != window_name:
            try:
                window.rename_window(window_name)
            except Exception:  # noqa: BLE001 — the name is only a label
                pass
        self._window = window
        return window

    def _pane_for(self, kind: SessionKind, window, shell_command: str):
        """The pane this kind of session runs in, creating or reusing as needed.

        Three cases, in order: a repeat run of the same kind (autofix retries)
        respawns its existing pane so the layout stays stable; the runner that
        *created* the session takes the pane tmux opened with; anything else
        splits a new one.

        The ``_created_session`` half is load-bearing. ``pipeline.py`` builds a
        separate ``ClaudeSession`` — and so a separate ``TmuxRunner`` — for
        research and for impl. Deciding "am I first?" from this instance's own
        empty ``_panes`` dict makes *both* runners think they are, and the impl
        pane silently overwrites the research pane instead of splitting beside
        it, destroying the plan the dev was reading.
        """
        existing = self._panes.get(kind)
        if existing is not None and _respawn(existing, shell_command):
            return existing

        if not self._panes and self._created_session:
            pane = window.active_pane
        else:
            pane = _split_pane(window)
            if pane is None:
                # No working split spelling — fall back to the pre-#60 layout
                # rather than failing to run the agent at all.
                fallback = self._new_window(f"{kind.value}-{_tmux_name(self.branch)}")
                _set_remain_on_exit(fallback)
                pane = fallback.active_pane
            else:
                _select_layout(window)

        self._panes[kind] = pane
        pane.send_keys(shell_command, enter=True)
        return pane

    def _reap_stale(self) -> None:
        """Kill finished, unattached ``do-*`` sessions. Never raises.

        Imported here rather than at module scope: ``manage`` imports this
        module for the workspace root, so a top-level import would be circular.
        """
        try:
            from devorchestrator.sessions.manage import reap_stale_sessions

            killed = reap_stale_sessions(root=self.root)
        except Exception:  # noqa: BLE001 — cleanup must never block a run
            return
        if killed:
            console.print(f"[dim]reaped {len(killed)} finished tmux session(s)[/dim]")

    def _attach_or_create(self, window_name: str):
        """Return the branch's tmux session, creating it only if absent."""
        try:
            if self._server.has_session(self.session_name):
                return self._server.sessions.get(session_name=self.session_name)
        except Exception:  # noqa: BLE001 — a lookup failure just means "create it"
            pass
        # About to add a session, so clear out finished ones first (issue #60).
        # remain-on-exit means nothing ever cleans itself up, and a week of runs
        # leaves a screenful of dead `do-*` sessions to kill by hand.
        self._reap_stale()
        self._created_session = True
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


class SessionFailed(RuntimeError):
    """An agent session did not complete successfully.

    Raised by :meth:`ClaudeSession.run`. Failing loudly matters: if a research
    session dies and we return quietly, ``pipeline.py`` reads a missing artifact
    as ``raw=""`` and cheerfully hands an empty plan to the implementation
    session. A clear exception is far better than a silent no-op build.
    """


class RateLimited(SessionFailed):
    """The agent was throttled and never recovered within the retry budget (#52).

    Subclasses :class:`SessionFailed` deliberately: every existing caller
    (``pipeline.py``, the CLI) already handles a failed session correctly, and
    none of them should have to learn a new exception to keep working. The
    distinct type exists so a caller that *wants* to tell "we ran out of quota"
    apart from "the agent got it wrong" can, since the remedy differs — wait
    versus fix the prompt. Any partial work (the artifact, any commits) is left
    on disk untouched.
    """


class ClaudeSession:
    """Lane C's :class:`~devorchestrator.contracts.AgentSession` implementation.

    The contract is deliberately tiny (``run`` / ``is_alive``) so the pipeline
    can drive a session without knowing about tmux. Everything richer — exit
    codes, timings, captured output — stays on ``.state`` for Lane C's own use.

    ``branch`` may be omitted and supplied later with :meth:`bind`. ``pipeline.py``
    constructs both sessions in ``build_pipeline`` — before a task is picked, so
    before any branch exists — and only learns the branch inside ``start()``.
    """

    def __init__(
        self,
        kind: SessionKind,
        *,
        branch: str | None = None,
        cwd: Path | None = None,
        agent: str = "claude",
        headless: bool = False,
        root: Path | None = None,
        runner: TmuxRunner | None = None,
        timeout: float = 1800.0,
        mesh=None,  # contracts.Mesh | None — session lifecycle tracking (#56)
        dev: str = "unknown",
        heartbeat_interval: float = 15.0,
        rate_limit_retries: int = DEFAULT_RATE_LIMIT_RETRIES,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.kind = kind
        self.branch = branch
        self.root = root
        self.timeout = timeout
        self._cwd = cwd
        self._agent = agent
        self._headless = headless
        self._mesh = mesh
        self._dev = dev
        self._heartbeat_interval = heartbeat_interval
        #: Count of lifecycle emits the mesh rejected. Surfaced rather than
        #: silently dropped so a wholly unreachable mesh is diagnosable.
        self._mesh_failures = 0
        # Throttle retries (#52) only engage on a matched rate-limit signature,
        # so the default path is unchanged. `sleep` is injectable for tests.
        self.rate_limit_retries = rate_limit_retries
        self._sleep = sleep
        self.runner = runner or (
            TmuxRunner(branch=branch, cwd=cwd, agent=agent, force_headless=headless, root=root)
            if branch is not None
            else None
        )
        self.state = SessionState(kind=kind, branch=branch or "")

    # -- AgentSession protocol --------------------------------------------

    def run(self, prompt: str) -> None:
        """Render the prompt, run the agent, and **block until it finishes**.

        Blocking is required by the contract: ``pipeline.py`` reads the artifact
        file on the line after ``research.run(...)`` returns, so the work must
        be done by then (see docs/spine.md §"AgentSession").

        Retries with backoff if the agent was throttled rather than genuinely
        failing (#52); each attempt reports its own lifecycle to the mesh (#56).

        Raises:
            SessionFailed: on a non-zero exit or a timeout.
            RateLimited: when throttling outlasted the retry budget.
        """
        if self.branch is None:
            self.bind(_branch_from_prompt(prompt))

        path = prompt_path(self.branch, self.kind, root=self.root)
        path.write_text(prompt, encoding="utf-8")

        for attempt in range(1, self.rate_limit_retries + 2):
            state = self._run_once(path)
            if state.ok:
                return

            reason = state.error or f"exit {state.exit_code}"
            tail = self.capture(lines=15)
            throttled = is_rate_limited(tail)
            attempts_left = attempt <= self.rate_limit_retries

            if throttled and attempts_left:
                # Exponential: the point of backing off is to outlast a rolling
                # window, and retrying immediately just burns another attempt.
                backoff = RATE_LIMIT_BACKOFF_S * (2 ** (attempt - 1))
                self._emit_lifecycle("session_rate_limited", {
                    "attempt": attempt, "backoff_s": round(backoff, 1),
                })
                console.print(
                    f"[yellow]{state.name} was rate-limited[/yellow] — retrying in "
                    f"{backoff:.0f}s (attempt {attempt} of {self.rate_limit_retries})"
                )
                self._sleep(backoff)
                continue

            console.print(f"[red]{state.name} failed:[/red] {reason}")
            if tail:
                console.print(f"[dim]{tail}[/dim]")
            if throttled:
                # Distinguishable from an ordinary failure, per #52 — the caller
                # can tell "we were throttled out" from "the work was wrong".
                raise RateLimited(
                    f"{self.kind.value} session still rate-limited after "
                    f"{self.rate_limit_retries} retries"
                )
            raise SessionFailed(f"{self.kind.value} session failed: {reason}")

    def _run_once(self, path: Path) -> SessionState:
        """One spawn-and-wait cycle, bracketed by #56's lifecycle events.

        Session lifecycle tracking reports start/heartbeat/end to the mesh so
        the source of truth reflects live sessions, not just pipeline
        milestones. All mesh calls are best-effort (SupabaseMesh swallows
        errors) so tracking never breaks the run. Emitting per *attempt* rather
        than per call means a throttled retry shows up as its own session in the
        mesh, which is what makes the rate-limit event above readable.
        """
        started = time.monotonic()
        self._emit_lifecycle("session_started", {})
        stop_heartbeat = self._start_heartbeat()
        try:
            self.run_prompt_file(path)
            state = self.wait(timeout=self.timeout)
        finally:
            stop_heartbeat.set()
            self._emit_lifecycle("session_ended", {
                "ok": self.state.ok,
                "duration_s": round(time.monotonic() - started, 1),
                "files_touched": self._files_touched(),
            })
        return state

    # -- session lifecycle tracking (#56) ---------------------------------

    def _emit_lifecycle(self, event_type: str, extra: dict) -> None:
        """Report one lifecycle event. Never raises.

        The swallow is not redundant with ``SupabaseMesh``'s own error handling.
        ``mesh`` is typed as the :class:`~devorchestrator.contracts.Mesh`
        protocol, so it is whatever the caller injected — a different backend, a
        test double, or a client whose transport raises before Supabase's own
        ``try`` is reached. Without this, a dead mesh takes down the session it
        was only supposed to be observing, which is exactly what issue #56's
        "a dead/misconfigured mesh never breaks the session" rules out.
        """
        if self._mesh is None:
            return
        try:
            self._mesh.emit(event_type, self.branch or "unknown", {
                "dev": self._dev, "branch": self.branch, "kind": self.kind.value, **extra,
            })
        except Exception:  # noqa: BLE001 — observability must never break a run
            self._mesh_failures += 1

    def _files_touched(self) -> list[str]:
        """Uncommitted files the session changed, best-effort (empty on any error)."""
        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self._cwd or Path.cwd(), capture_output=True, text=True, timeout=10,
            )
            return [line[3:].strip() for line in proc.stdout.splitlines() if line.strip()]
        except Exception:
            return []

    def _start_heartbeat(self) -> threading.Event:
        """Emit `session_heartbeat` every ``heartbeat_interval`` while the session
        runs, so `active_sessions()` (#57) can tell a live session from a dead one.
        Returns the stop Event the caller sets when the session finishes."""
        stop = threading.Event()
        if self._mesh is None or self._heartbeat_interval <= 0:
            return stop

        def beat() -> None:
            while not stop.wait(self._heartbeat_interval):
                self._emit_lifecycle("session_heartbeat", {
                    "alive": True, "files_touched": self._files_touched(),
                })

        threading.Thread(target=beat, daemon=True).start()
        return stop

    def is_alive(self) -> bool:
        return self.runner is not None and self.runner.is_alive(self.state)

    # -- Lane C extras -----------------------------------------------------

    def bind(self, branch: str) -> None:
        """Attach this session to a branch, building its runner.

        Lets the pipeline construct sessions up front and name the branch once
        the developer has picked a task.
        """
        self.branch = branch
        self.state = SessionState(kind=self.kind, branch=branch)
        if self.runner is None or self.runner.branch != branch:
            self.runner = TmuxRunner(
                branch=branch,
                cwd=self._cwd,
                agent=self._agent,
                force_headless=self._headless,
                root=self.root,
            )

    def run_prompt_file(self, path: Path) -> SessionState:
        """Spawn against an already-rendered prompt file (non-blocking)."""
        if self.runner is None:
            raise SessionFailed("session has no branch — call bind(branch) first")
        self.state = self.runner.spawn(self.kind, claude_command(path, binary=self.runner.agent))
        return self.state

    def wait(self, *, timeout: float | None = None, poll: float = 1.0) -> SessionState:
        if self.runner is None:
            return self.state
        self.state = self.runner.wait(
            self.state, timeout=timeout if timeout is not None else self.timeout, poll=poll
        )
        return self.state

    def capture(self, *, lines: int = 60) -> str:
        return self.runner.capture(self.state, lines=lines) if self.runner else ""

    def kill(self) -> None:
        if self.runner is not None:
            self.runner.kill()
