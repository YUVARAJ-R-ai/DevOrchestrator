"""The implementation session: execute the artifact (issue #8).

Also exposes :func:`run_autofix`, the Lane C entry point that the quality gate's
``--autofix`` (issue #12) calls to re-invoke the agent with failure context.
That is the AI→AI rung of the escalation model: a routine check failure is
repaired here, and only an unresolved one reaches a human.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from devorchestrator import prompts
from devorchestrator.contracts import CheckResult, CheckStatus
from devorchestrator.sessions.artifact import ParsedArtifact
from devorchestrator.sessions.tmux_runner import (
    ClaudeSession,
    SessionKind,
    SessionState,
    SessionStatus,
    TmuxRunner,
    artifact_path,
    prompt_path,
)

__all__ = ["build_autofix_prompt", "build_impl_prompt", "failing", "run_autofix", "run_impl"]

console = Console()

DEFAULT_TIMEOUT_S = 3600.0

#: Matches the "max 2 retries" in issue #12. Past this the failure is not
#: routine, and escalating to the human is the correct outcome.
MAX_AUTOFIX_ATTEMPTS = 2


def failing(results: list[CheckResult]) -> list[CheckResult]:
    """Only genuinely failed checks.

    ``CheckResult.passed`` is False for *skipped* too, but a skipped optional
    tool is not something to send an agent to repair — that would spawn a fix
    session for a tool that simply is not installed.
    """
    return [r for r in results if r.status is CheckStatus.failed]


def build_impl_prompt(branch: str, *, root: Path | None = None) -> Path:
    text = prompts.render(
        "impl", branch=branch, artifact_path=artifact_path(branch, root=root)
    )
    path = prompt_path(branch, SessionKind.impl, root=root)
    path.write_text(text, encoding="utf-8")
    return path


def build_autofix_prompt(
    branch: str,
    results: list[CheckResult],
    *,
    attempt: int = 1,
    max_attempts: int = MAX_AUTOFIX_ATTEMPTS,
    root: Path | None = None,
) -> Path:
    """Render the repair prompt from the failing checks."""
    failed = failing(results)
    failures = "\n".join(f"- **{r.tool}** — {_headline(r)}" for r in failed) or "- unknown"
    # Keep the tail: the actionable part of ruff/pytest output is at the end,
    # and the whole log is far larger than the prompt needs to be.
    output = (
        "\n\n".join(f"$ {r.tool}\n{_tail(r.output)}" for r in failed) or "(no captured output)"
    )

    text = prompts.render(
        "autofix",
        branch=branch,
        attempt=attempt,
        max_attempts=max_attempts,
        failures=failures,
        check_output=output,
        artifact_path=artifact_path(branch, root=root),
    )
    path = prompt_path(branch, SessionKind.autofix, root=root)
    path.write_text(text, encoding="utf-8")
    return path


def _headline(result: CheckResult) -> str:
    """Last non-empty output line — usually the summary a tool prints."""
    for line in reversed(result.output.splitlines()):
        if line.strip():
            return line.strip()
    return result.status.value


def _tail(text: str, *, lines: int = 60) -> str:
    return "\n".join(text.splitlines()[-lines:])


def run_impl(
    branch: str,
    *,
    headless: bool = False,
    timeout: float = DEFAULT_TIMEOUT_S,
    agent: str = "claude",
    cwd: Path | None = None,
    root: Path | None = None,
    runner: TmuxRunner | None = None,
    wait: bool = True,
) -> SessionState:
    """Spawn an implementation session against this branch's artifact."""
    target = artifact_path(branch, root=root)
    if not target.is_file():
        console.print(f"[red]No artifact at {target}[/red] — run the research session first.")
        return SessionState(
            kind=SessionKind.impl,
            branch=branch,
            status=SessionStatus.failed,
            error=f"missing artifact: {target}",
        )

    artifact = ParsedArtifact.from_file(target)
    _, total = artifact.progress
    prompt_file = build_impl_prompt(branch, root=root)
    session = ClaudeSession(
        SessionKind.impl,
        branch=branch,
        cwd=cwd,
        agent=agent,
        headless=headless,
        root=root,
        runner=runner,
    )

    console.print(
        Panel(
            f"[bold]{artifact.title or branch}[/bold]\n"
            f"{total} sub-task(s) · {len(artifact.files)} file(s) planned",
            title="[bold magenta]Implementation session[/bold magenta]",
            subtitle="[dim]executing the artifact — watch the pane, interrupt any time[/dim]",
            border_style="magenta",
        )
    )

    state = session.run_prompt_file(prompt_file)
    if not wait or state.status is not SessionStatus.running:
        return state

    state = session.wait(timeout=timeout)
    _report_impl(state, session, target)
    return state


def run_autofix(
    branch: str,
    results: list[CheckResult],
    *,
    attempt: int = 1,
    max_attempts: int = MAX_AUTOFIX_ATTEMPTS,
    headless: bool = False,
    timeout: float = DEFAULT_TIMEOUT_S,
    agent: str = "claude",
    cwd: Path | None = None,
    root: Path | None = None,
    runner: TmuxRunner | None = None,
) -> SessionState:
    """Re-invoke the agent with check-failure context (called by issue #12).

    Narrates the repair explicitly — "checks failed → fixing → re-running" is
    the beat the demo is built around, so it is stated rather than left for the
    viewer to infer from a spinner.
    """
    failed = failing(results)
    names = ", ".join(r.tool for r in failed) or "checks"

    console.print(
        Panel(
            f"[red]{names} failed[/red] → [yellow]re-invoking the agent with the failure[/yellow]\n"
            f"[dim]AI→AI repair, attempt {attempt} of {max_attempts} — "
            f"no human interrupted yet[/dim]",
            title="[bold yellow]Autofix[/bold yellow]",
            border_style="yellow",
        )
    )

    prompt_file = build_autofix_prompt(
        branch, results, attempt=attempt, max_attempts=max_attempts, root=root
    )
    session = ClaudeSession(
        SessionKind.autofix,
        branch=branch,
        cwd=cwd,
        agent=agent,
        headless=headless,
        root=root,
        runner=runner,
    )

    state = session.run_prompt_file(prompt_file)
    if state.status is not SessionStatus.running:
        return state

    state = session.wait(timeout=timeout)
    if state.ok:
        console.print("[green]Autofix session finished[/green] — re-running checks")
    else:
        console.print(f"[red]Autofix session failed[/red] (exit {state.exit_code})")
    return state


def _report_impl(state: SessionState, session: ClaudeSession, target: Path) -> None:
    if state.ok:
        if target.is_file():
            done, total = ParsedArtifact.from_file(target).progress
            colour = "green" if total and done == total else "yellow"
            console.print(
                f"[{colour}]Implementation complete[/{colour}] — "
                f"{done}/{total} sub-tasks checked off in {state.duration_s:.0f}s"
            )
            if total and done < total:
                console.print(
                    "[dim]Unchecked sub-tasks remain — see Implementation Notes "
                    "in the artifact for why.[/dim]"
                )
        console.print("[dim]Next: `devorchestrator pr` to run checks and open a PR.[/dim]")
        return

    if state.status is SessionStatus.timeout:
        console.print(f"[red]Implementation timed out[/red] after {state.duration_s:.0f}s")
    else:
        console.print(f"[red]Implementation failed[/red] (exit {state.exit_code})")

    tail = session.capture(lines=20)
    if tail:
        console.print(Panel(tail, title="[dim]last output[/dim]", border_style="red"))
