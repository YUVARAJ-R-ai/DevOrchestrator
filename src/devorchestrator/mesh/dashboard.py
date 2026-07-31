from __future__ import annotations

import time

from rich.console import Console, Group
from rich.live import Live
from rich.table import Table

from devorchestrator.contracts import DevActivity, Mesh


def _sessions_table(mesh: Mesh) -> Table:
    """Active Claude Code sessions right now — the live source of truth (#57/#59).

    ``active_sessions`` is not on the frozen ``Mesh`` protocol, so read it
    defensively: a mesh without it (e.g. an older fake) just shows no sessions.
    """
    table = Table(title="Active sessions (live)", expand=True)
    table.add_column("Dev", style="cyan")
    table.add_column("Branch")
    table.add_column("Kind")
    table.add_column("State")
    table.add_column("Last seen")

    active = getattr(mesh, "active_sessions", lambda: [])() or []
    if not active:
        table.add_row("[dim]— no active sessions —[/]", "", "", "", "")
    for s in active:
        table.add_row(s.dev, s.branch, s.kind, f"[green]{s.state}[/]", s.last_seen)
    return table


def _activity_table(mesh: Mesh) -> Table:
    statuses: list[DevActivity] = []
    for module in mesh.list_modules():
        statuses.extend(mesh.who_is_touching(module))

    table = Table(title="Recent module activity", expand=True)
    table.add_column("Dev", style="cyan")
    table.add_column("Module")
    table.add_column("Branch")
    table.add_column("Event")
    table.add_column("Timestamp")
    for s in statuses:
        table.add_row(s.dev, s.module, s.branch, s.event_type, s.ts)
    return table


def _decisions_table(mesh: Mesh) -> Table:
    table = Table(title="Recent decisions", expand=True)
    table.add_column("Dev", style="cyan")
    table.add_column("Decision")
    table.add_column("Timestamp")
    for d in mesh.recent_decisions():
        table.add_row(d.dev, d.description, d.ts or "")
    return table


def build_dashboard(mesh: Mesh) -> Group:
    """The full team view: live sessions on top, then module activity + decisions.

    Returns a renderable (not printed) so ``--watch`` can refresh it in place.
    """
    return Group(_sessions_table(mesh), _activity_table(mesh), _decisions_table(mesh))


def render_dashboard(mesh: Mesh, console: Console | None = None) -> None:
    """One-shot render of the team dashboard."""
    (console or Console()).print(build_dashboard(mesh))


def render_dashboard_live(
    mesh: Mesh, console: Console | None = None, *, interval: float = 3.0
) -> None:
    """Auto-refreshing dashboard (``devorchestrator mesh --watch``).

    Rebuilds the view every ``interval`` seconds until Ctrl-C. This is the
    glanceable single-source-of-truth view — who's in a session right now.
    """
    console = console or Console()
    with Live(build_dashboard(mesh), console=console, screen=True, refresh_per_second=4) as live:
        try:
            while True:
                time.sleep(interval)
                live.update(build_dashboard(mesh))
        except KeyboardInterrupt:
            pass
    console.print("[dim]stopped watching.[/]")


__all__ = ["render_dashboard", "render_dashboard_live", "build_dashboard"]
