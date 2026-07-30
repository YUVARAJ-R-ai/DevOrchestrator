from __future__ import annotations

from rich.console import Console

from devorchestrator.checks.runner import SubprocessCheckRunner
from devorchestrator.contracts import CheckResult, CheckRunner

MAX_RETRIES = 2


def autofix(
    runner: CheckRunner | None = None,
    *,
    max_retries: int = MAX_RETRIES,
    console: Console | None = None,
) -> list[CheckResult]:
    """Run checks, fix failures by logging a re-invoke message, retry up to N times.

    In production the re-invoke will call Lane C's impl spawner. For now it logs
    the intent — the architecture supports hot-swapping the fix callback.
    """
    console = console or Console()
    runner = runner or SubprocessCheckRunner()

    results = runner.run_all()
    failed = [r for r in results if not r.passed]

    for attempt in range(1, max_retries + 1):
        if not failed:
            break

        console.print(f"[yellow]autofix attempt {attempt}/{max_retries}[/]")
        for r in failed:
            console.print(f"  fixing [cyan]{r.tool}[/] failure...")
            # TODO: swap with Lane C's impl spawner (sessions/impl.py #19)
            console.print(f"  [dim]→ re-invoke impl session for {r.tool}[/]")

        results = runner.run_all()
        failed = [r for r in results if not r.passed]

    if failed:
        console.print("[red]autofix exhausted — some checks still failing[/]")
    else:
        console.print("[green]autofix: all checks passed[/]")

    return results


__all__ = ["autofix"]
