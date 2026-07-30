"""Parse, watch, render, and gate the artifact (issues #8, #10).

The artifact is the moment the loop becomes reviewable: research has finished,
implementation has not started, and a human can still change the plan cheaply.
This module makes that moment legible.

:class:`devorchestrator.contracts.Artifact` is a frozen value object carrying
``path``/``raw``/``modules_affected`` — deliberately thin, because ``raw`` is
authoritative and the implementation session reads the file directly. The richer
section-by-section view needed to *render* and *gate* the plan is Lane C's own
concern, so it lives here as :class:`ParsedArtifact`, which converts to the
contract type via :meth:`ParsedArtifact.to_contract`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from devorchestrator import contracts
from devorchestrator.sessions.tmux_runner import SessionState, SessionStatus, artifact_path

__all__ = [
    "FileChange",
    "ParsedArtifact",
    "SubTask",
    "await_artifact",
    "human_gate",
    "load_artifact",
    "render_artifact",
    "render_progress",
    "wait_for_artifact",
]

console = Console()

DEFAULT_TIMEOUT_S = 1800.0
POLL_INTERVAL_S = 1.0

#: A research session streams the artifact out over several writes. Requiring
#: the file to stop changing for this many consecutive polls means a half-written
#: plan is never rendered — or worse, implemented.
STABLE_POLLS = 2


@dataclass(slots=True)
class SubTask:
    text: str
    done: bool = False


@dataclass(slots=True)
class FileChange:
    path: str
    note: str = ""

    @property
    def action(self) -> str:
        """Best-effort create/modify classification from the note text."""
        return "create" if "new file" in self.note.lower() else "modify"


# Headings the research prompt is told to emit, mapped to the field they fill.
# Parsing is heading-driven so a session that adds prose sections cannot break us.
_SECTION_FIELDS: dict[str, str] = {
    "context": "context",
    "sub-tasks": "subtasks",
    "subtasks": "subtasks",
    "files to create / modify": "files",
    "files to create/modify": "files",
    "files": "files",
    "acceptance criteria": "acceptance_criteria",
    "implementation notes": "notes",
    "notes": "notes",
}

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
_CHECKBOX_RE = re.compile(r"^[-*]\s*\[( |x|X)\]\s*(.+)$")
_BULLET_RE = re.compile(r"^[-*]\s+(.+)$")
# `path` — note  /  **path** — note  /  bare path
_FILE_RE = re.compile(r"^[`*]*([^`*\s]+)[`*]*\s*(?:[—–-]\s*(.*))?$")


@dataclass(slots=True)
class ParsedArtifact:
    """Lane C's structured view of ``artifact.md``.

    Tolerant by design — a research session is a language model, so unknown
    sections are ignored and a malformed one degrades to empty rather than
    raising. :attr:`is_usable` is the real quality gate.
    """

    raw: str = ""
    path: Path | None = None
    title: str = ""
    issue_id: str = ""
    branch: str = ""
    context: list[str] = field(default_factory=list)
    subtasks: list[SubTask] = field(default_factory=list)
    files: list[FileChange] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # -- parsing -----------------------------------------------------------

    @classmethod
    def from_markdown(cls, text: str, *, path: Path | None = None) -> ParsedArtifact:
        art = cls(raw=text, path=path)
        current: str | None = None

        for line in text.splitlines():
            stripped = line.strip()

            heading = _HEADING_RE.match(stripped)
            if heading:
                level, name = len(heading.group(1)), heading.group(2).strip()
                if level == 1:
                    art.title = re.sub(r"^artifact:\s*", "", name, flags=re.I).strip()
                    current = None
                else:
                    current = _SECTION_FIELDS.get(name.lower().strip())
                continue

            # Metadata line: _Issue: 42 | Branch: feature/... | Generated: ..._
            if stripped.startswith("_") and "|" in stripped:
                art._absorb_meta(stripped.strip("_"))
                continue

            if not stripped or current is None:
                continue
            art._absorb_line(current, stripped)

        return art

    @classmethod
    def from_file(cls, path: Path) -> ParsedArtifact:
        return cls.from_markdown(Path(path).read_text(encoding="utf-8"), path=Path(path))

    def _absorb_meta(self, meta: str) -> None:
        for part in meta.split("|"):
            if ":" not in part:
                continue
            key, _, value = part.partition(":")
            key, value = key.strip().lower(), value.strip()
            if key in ("issue", "task") and not self.issue_id:
                self.issue_id = value.lstrip("#")
            elif key == "branch" and not self.branch:
                self.branch = value

    def _absorb_line(self, section: str, line: str) -> None:
        checkbox = _CHECKBOX_RE.match(line)
        bullet = _BULLET_RE.match(line)

        if section == "subtasks":
            if checkbox:
                self.subtasks.append(SubTask(checkbox.group(2), checkbox.group(1) in "xX"))
            elif bullet:
                self.subtasks.append(SubTask(bullet.group(1)))
        elif section == "acceptance_criteria":
            if checkbox:
                self.acceptance_criteria.append(checkbox.group(2))
            elif bullet:
                self.acceptance_criteria.append(bullet.group(1))
        elif section == "files":
            content = checkbox.group(2) if checkbox else (bullet.group(1) if bullet else None)
            if content:
                match = _FILE_RE.match(content.strip())
                if match:
                    self.files.append(FileChange(match.group(1), (match.group(2) or "").strip()))
        elif section == "context":
            if bullet:
                self.context.append(bullet.group(1))
            elif not checkbox:
                self.context.append(line)
        elif section == "notes":
            self.notes.append(bullet.group(1) if bullet else line)

    # -- quality -----------------------------------------------------------

    @property
    def is_usable(self) -> bool:
        """Enough substance to hand to an implementation session."""
        return bool(self.subtasks) and bool(self.raw.strip())

    @property
    def touched_modules(self) -> tuple[str, ...]:
        """Top-level module per planned file — the mesh's conflict unit."""
        seen: list[str] = []
        for change in self.files:
            parts = Path(change.path).parts
            module = parts[1] if len(parts) > 1 and parts[0] in ("src", "tests") else parts[0]
            if module and module not in seen:
                seen.append(module)
        return tuple(seen)

    @property
    def progress(self) -> tuple[int, int]:
        """(completed, total) sub-tasks — impl sessions check boxes off."""
        return sum(1 for task in self.subtasks if task.done), len(self.subtasks)

    # -- contract boundary -------------------------------------------------

    def to_contract(
        self, *, issue_id: str | None = None, branch: str | None = None
    ) -> contracts.Artifact:
        """Convert to the frozen contract type other lanes consume."""
        return contracts.Artifact(
            path=str(self.path or ""),
            issue_id=issue_id or self.issue_id,
            branch=branch or self.branch,
            raw=self.raw,
            modules_affected=self.touched_modules,
        )


# ---------------------------------------------------------------------------
# Watching
# ---------------------------------------------------------------------------


def wait_for_artifact(
    branch: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
    poll: float = POLL_INTERVAL_S,
    root: Path | None = None,
    session: SessionState | None = None,
    require_usable: bool = True,
) -> ParsedArtifact | None:
    """Block until ``artifact.md`` exists, settles, and parses usefully.

    Returns None on timeout, on an unusable artifact, or as soon as the research
    session is known to have died — waiting out the full timeout for a file a
    dead process will never write is the worst possible demo failure.
    """
    target = artifact_path(branch, root=root)
    deadline = time.monotonic() + timeout
    last_signature: tuple[int, float] | None = None
    stable = 0

    while time.monotonic() < deadline:
        if target.is_file():
            try:
                stat = target.stat()
                signature: tuple[int, float] | None = (stat.st_size, stat.st_mtime)
            except OSError:
                signature = None

            if signature and signature[0] > 0:
                stable = stable + 1 if signature == last_signature else 0
                last_signature = signature
                if stable >= STABLE_POLLS:
                    artifact = ParsedArtifact.from_file(target)
                    artifact.branch = artifact.branch or branch
                    if artifact.is_usable or not require_usable:
                        return artifact
                    console.print(
                        f"[yellow]Artifact at {target} has no sub-tasks — the research "
                        f"session did not produce a usable plan.[/yellow]"
                    )
                    return None

        if session is not None and session.status in (
            SessionStatus.failed,
            SessionStatus.timeout,
        ) and not target.is_file():
            return None

        time.sleep(poll)

    console.print(f"[red]Timed out[/red] waiting for {target} after {timeout:.0f}s")
    return None


def await_artifact(
    branch: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
    root: Path | None = None,
    session: SessionState | None = None,
    render: bool = True,
) -> ParsedArtifact | None:
    """:func:`wait_for_artifact` with a live spinner, then render what arrived."""
    target = artifact_path(branch, root=root)

    if target.is_file() and target.stat().st_size > 0:
        artifact = wait_for_artifact(branch, timeout=timeout, root=root, session=session)
    else:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            progress.add_task("waiting for the research session to write the plan", total=None)
            artifact = wait_for_artifact(branch, timeout=timeout, root=root, session=session)

    if artifact and render:
        render_artifact(artifact)
    return artifact


def load_artifact(
    branch: str, *, issue_id: str = "", root: Path | None = None
) -> contracts.Artifact | None:
    """Read this branch's artifact as the frozen contract type, if it exists."""
    target = artifact_path(branch, root=root)
    if not target.is_file():
        return None
    return ParsedArtifact.from_file(target).to_contract(issue_id=issue_id, branch=branch)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_artifact(artifact: ParsedArtifact, *, raw: bool = False) -> None:
    """Pretty-print the plan for a human to judge before implementation."""
    if raw:
        console.print(Panel(Markdown(artifact.raw), title="artifact.md", border_style="cyan"))
        return

    blocks: list[object] = []

    if artifact.context:
        blocks.append(Markdown("\n".join(f"- {line}" for line in artifact.context)))

    if artifact.subtasks:
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column(width=3)
        table.add_column(overflow="fold")
        for task in artifact.subtasks:
            mark = "[green]x[/green]" if task.done else "[dim]·[/dim]"
            text = f"[dim strike]{task.text}[/dim strike]" if task.done else task.text
            table.add_row(f"[{mark}]", text)
        blocks.append(_section("Sub-tasks", table))

    if artifact.files:
        table = Table(show_header=True, header_style="dim", box=None, padding=(0, 1))
        table.add_column("File", style="cyan", overflow="fold")
        table.add_column("Change", overflow="fold")
        for change in artifact.files:
            table.add_row(change.path, change.note or f"[dim]{change.action}[/dim]")
        blocks.append(_section("Files to create / modify", table))

    if artifact.acceptance_criteria:
        blocks.append(
            _section(
                "Acceptance criteria",
                Markdown("\n".join(f"- {line}" for line in artifact.acceptance_criteria)),
            )
        )

    if artifact.notes:
        blocks.append(
            _section("Implementation notes", Markdown("\n".join(f"- {n}" for n in artifact.notes)))
        )

    if not blocks:
        render_artifact(artifact, raw=True)  # parsed to nothing — show the file
        return

    done, total = artifact.progress
    subtitle = f"[dim]{total} sub-tasks · {len(artifact.files)} files"
    if artifact.touched_modules:
        subtitle += f" · touches {', '.join(artifact.touched_modules)}"
    if done:
        subtitle += f" · {done} done"
    subtitle += "[/dim]"

    console.print(
        Panel(
            Group(*blocks),
            title=f"[bold cyan]{artifact.title or 'Artifact'}[/bold cyan]",
            subtitle=subtitle,
            border_style="cyan",
            padding=(1, 2),
        )
    )


def _section(title: str, body: object) -> Group:
    return Group(f"\n[bold]{title}[/bold]", body)


def render_progress(artifact: ParsedArtifact, *, title: str = "Progress") -> None:
    """Compact sub-task state — shown after impl and between autofix retries.

    Issue #12's retry loop calls this so the "it fixed itself" beat is visible
    as checkboxes changing, not just a spinner.
    """
    done, total = artifact.progress
    if not total:
        return
    bar = "".join("[green]#[/green]" if t.done else "[dim].[/dim]" for t in artifact.subtasks)
    console.print(f"[bold]{title}[/bold]  {bar}  {done}/{total}")


# ---------------------------------------------------------------------------
# Human gate
# ---------------------------------------------------------------------------


def human_gate(artifact: ParsedArtifact, *, allow_edit: bool = True) -> bool:
    """The optional gate: implement, edit first, or abort.

    Returns True to proceed. Auto-proceeds when stdin is not a TTY so the
    pipeline stays usable in CI and in a scripted demo run.
    """
    if not sys.stdin.isatty():
        console.print("[dim]Non-interactive — proceeding to implementation.[/dim]")
        return True

    options = "[bold]\\[Enter][/bold] implement"
    if allow_edit:
        options += " · [bold]\\[e][/bold] edit the plan first"
    options += " · [bold]\\[q][/bold] abort"

    while True:
        console.print(f"\nResearch complete — review the plan above.\n{options}")
        try:
            choice = input("› ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Aborted.[/yellow]")
            return False

        if choice in ("", "y", "yes"):
            return True
        if choice in ("q", "n", "no"):
            console.print("[yellow]Aborted before implementation.[/yellow]")
            return False
        if choice == "e" and allow_edit:
            edited = _edit(artifact)
            if edited is not None:
                render_artifact(edited)
            continue
        console.print("[dim]Unrecognised — press Enter, e, or q.[/dim]")


def _edit(artifact: ParsedArtifact) -> ParsedArtifact | None:
    """Open the artifact in $EDITOR and re-parse it in place."""
    if artifact.path is None or not Path(artifact.path).is_file():
        console.print("[red]Artifact has no file on disk to edit.[/red]")
        return None

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    try:
        subprocess.call([*editor.split(), str(artifact.path)])  # noqa: S603 — the user's own $EDITOR
    except OSError as exc:
        console.print(f"[red]Could not launch {editor!r}:[/red] {exc}")
        return None

    reparsed = ParsedArtifact.from_file(Path(artifact.path))
    # Mutate in place so the caller's reference reflects the edit.
    artifact.raw = reparsed.raw
    artifact.title = reparsed.title
    artifact.context = reparsed.context
    artifact.subtasks = reparsed.subtasks
    artifact.files = reparsed.files
    artifact.acceptance_criteria = reparsed.acceptance_criteria
    artifact.notes = reparsed.notes

    if not artifact.is_usable:
        console.print(
            "[yellow]Edited artifact has no sub-tasks — implementation would be a no-op.[/yellow]"
        )
    return artifact
