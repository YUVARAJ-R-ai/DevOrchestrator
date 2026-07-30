from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from devorchestrator.contracts import CheckResult, CheckRunner, CheckStatus

_Runner = Callable[
    [list[str], str | None, dict[str, Any]],
    subprocess.CompletedProcess | Any,
]


def _run_tool(
    tool: str,
    args: list[str],
    cwd: str,
    runner: _Runner = subprocess.run,
) -> CheckResult:
    start = time.monotonic()
    try:
        proc = runner(
            [tool, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            env=None,
        )
        status = CheckStatus.passed if proc.returncode == 0 else CheckStatus.failed
        output = (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError:
        status = CheckStatus.skipped
        output = f"{tool} not found — install it to run this check."
    except Exception as exc:
        status = CheckStatus.failed
        output = str(exc)

    duration = time.monotonic() - start
    return CheckResult(
        tool=tool, status=status, output=output.strip(), duration_s=round(duration, 2),
    )


class SubprocessCheckRunner(CheckRunner):
    def __init__(
        self,
        cwd: str | None = None,
        *,
        all_checks: bool = False,
        runner: _Runner = subprocess.run,
    ) -> None:
        self._cwd = cwd or Path.cwd()
        self._all_checks = all_checks
        self._runner = runner

    def run_all(self) -> list[CheckResult]:
        results: list[CheckResult] = []

        ruff = _run_tool("ruff", ["check", "."], self._cwd, self._runner)
        results.append(ruff)
        if not ruff.passed and not self._all_checks:
            return results

        pytest = _run_tool("pytest", [], self._cwd, self._runner)
        results.append(pytest)
        if not pytest.passed and not self._all_checks:
            return results

        return results

    @staticmethod
    def render(results: list[CheckResult], console: Console | None = None) -> None:
        console = console or Console()
        table = Table(title="Quality Gates", show_header=True)
        table.add_column("Tool", style="cyan")
        table.add_column("Status")
        table.add_column("Duration")
        table.add_column("Summary")

        for r in results:
            icon = "✅" if r.passed else ("⏭️" if r.status is CheckStatus.skipped else "❌")
            status_str = f"{icon} {r.status.value}"
            summary = r.output[:60] if r.output else ""
            table.add_row(r.tool, status_str, f"{r.duration_s}s", summary)

        console.print(table)
        failed = [r for r in results if not r.passed]
        if failed:
            for r in failed:
                console.print(f"\n[red]── {r.tool} log ──[/]")
                for line in r.output.split("\n"):
                    console.print(f"  {line}")


__all__ = ["SubprocessCheckRunner"]
