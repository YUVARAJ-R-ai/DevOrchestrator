"""Rich + questionary task selector (backlog #5) — Lane B (integrations).

Renders the fetched issues as a Rich table, then lets the developer pick one
with arrow keys via ``questionary`` — Rich alone can render a table but can't
capture keypresses, so the two are paired: Rich for the preview, questionary
for the interactive pick.
"""

from __future__ import annotations

import questionary
from questionary import Choice
from rich.console import Console
from rich.table import Table

from devorchestrator.contracts import Issue

_PRIORITY_STYLE = {
    "urgent": "bold red",
    "high": "yellow",
    "medium": "cyan",
    "low": "dim",
    "none": "dim",
}


def render_issue_table(issues: list[Issue], console: Console | None = None) -> None:
    """Print the Rich preview table (title · priority · size · assignee)."""
    console = console or Console()
    table = Table(title="Your assigned issues")
    table.add_column("#", style="dim")
    table.add_column("Title")
    table.add_column("Priority")
    table.add_column("Size")
    table.add_column("Assignee")

    for issue in issues:
        style = _PRIORITY_STYLE.get(issue.priority.value, "")
        priority_cell = f"[{style}]{issue.priority.value}[/]" if style else issue.priority.value
        table.add_row(
            issue.id,
            issue.title,
            priority_cell,
            str(issue.estimate) if issue.estimate is not None else "-",
            issue.assignee or "-",
        )
    console.print(table)


def select_issue(issues: list[Issue], console: Console | None = None) -> Issue | None:
    """Show the table, then prompt for an arrow-key pick. Returns ``None`` on quit."""
    if not issues:
        return None

    render_issue_table(issues, console)

    choice = questionary.select(
        "Pick a task to work on:",
        choices=[
            Choice(title=f"#{issue.id}  {issue.title}  [{issue.priority.value}]", value=issue)
            for issue in issues
        ]
        + [Choice(title="q) quit", value=None)],
    ).ask()
    return choice
