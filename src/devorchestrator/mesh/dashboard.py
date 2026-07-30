from __future__ import annotations

from rich.console import Console
from rich.table import Table

from devorchestrator.contracts import DevActivity, Mesh


def render_dashboard(mesh: Mesh, console: Console | None = None) -> None:
    """Render a Rich table showing team activity from the mesh."""
    console = console or Console()
    statuses: list[DevActivity] = []
    for module in mesh.list_modules():
        statuses.extend(mesh.who_is_touching(module))

    table = Table(title="Lane D — Team Activity Dashboard")
    table.add_column("Dev", style="cyan")
    table.add_column("Module")
    table.add_column("Branch")
    table.add_column("Event")
    table.add_column("Timestamp")

    for s in statuses:
        table.add_row(s.dev, s.module, s.branch, s.event_type, s.ts)

    console.print(table)


__all__ = ["render_dashboard"]
