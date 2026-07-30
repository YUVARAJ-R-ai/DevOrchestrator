"""The research session: read the codebase, write the artifact (issue #8).

This is what makes DevOrchestrator's coordination trustworthy. A chat model
handed only a task description produces a plausible-looking plan; a Claude Code
session with file and search tools produces one grounded in files it actually
opened. The artifact it writes is the contract between "what we decided" and
"what got built".

Consumes :class:`devorchestrator.contracts.Issue`; the artifact it produces is
loaded as :class:`devorchestrator.contracts.Artifact` by :mod:`.artifact`.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from devorchestrator import prompts
from devorchestrator.contracts import Issue
from devorchestrator.sessions.tmux_runner import (
    ClaudeSession,
    SessionKind,
    SessionState,
    SessionStatus,
    TmuxRunner,
    artifact_path,
    prompt_path,
)

__all__ = ["branch_for", "build_research_prompt", "run_research"]

console = Console()

#: Research opens a lot of files; give it room before calling it a timeout.
DEFAULT_TIMEOUT_S = 1800.0


def branch_for(issue: Issue) -> str:
    """``feature/issue-<id>-<slug>``.

    ``Issue.branch_slug()`` (frozen contract) supplies the body; the ``feature/``
    prefix is added here to match ``docs/TEAM-WORKFLOW.md`` and ``/start-task``
    Phase 5.
    """
    return f"feature/{issue.branch_slug()}"


def build_research_prompt(issue: Issue, branch: str, *, root: Path | None = None) -> Path:
    """Render the research prompt to disk and return its path."""
    text = prompts.render(
        "research",
        branch=branch,
        issue_id=issue.id,
        title=issue.title,
        priority=issue.priority.value,
        description=issue.description.strip() or "_No description provided on the issue._",
        artifact_path=artifact_path(branch, root=root),
        artifact_schema=prompts.ARTIFACT_SCHEMA,
    )
    path = prompt_path(branch, SessionKind.research, root=root)
    path.write_text(text, encoding="utf-8")
    return path


def run_research(
    issue: Issue,
    *,
    branch: str | None = None,
    headless: bool = False,
    timeout: float = DEFAULT_TIMEOUT_S,
    agent: str = "claude",
    cwd: Path | None = None,
    root: Path | None = None,
    runner: TmuxRunner | None = None,
    wait: bool = True,
) -> SessionState:
    """Spawn a research session for ``issue`` and wait for it to finish.

    Returns the session state whatever the outcome — the caller inspects
    ``.ok``. Whether a *usable* artifact appeared is a separate question,
    answered by :func:`devorchestrator.sessions.artifact.await_artifact`.
    """
    branch = branch or branch_for(issue)
    target = artifact_path(branch, root=root)
    # A stale artifact would make the watcher return instantly with the old plan.
    target.unlink(missing_ok=True)

    prompt_file = build_research_prompt(issue, branch, root=root)
    session = ClaudeSession(
        SessionKind.research,
        branch=branch,
        cwd=cwd,
        agent=agent,
        headless=headless,
        root=root,
        runner=runner,
    )

    console.print(
        Panel(
            f"[bold]#{issue.id} {issue.title}[/bold]\n"
            f"branch    [cyan]{branch}[/cyan]\n"
            f"artifact  [dim]{target}[/dim]",
            title="[bold blue]Research session[/bold blue]",
            subtitle="[dim]reading the codebase to write the plan[/dim]",
            border_style="blue",
        )
    )

    state = session.run_prompt_file(prompt_file)
    if not wait or state.status is not SessionStatus.running:
        return state

    state = session.wait(timeout=timeout)
    _report(state, session)
    return state


def _report(state: SessionState, session: ClaudeSession) -> None:
    if state.ok:
        console.print(f"[green]Research complete[/green] in {state.duration_s:.0f}s")
        return

    if state.status is SessionStatus.timeout:
        console.print(f"[red]Research timed out[/red] after {state.duration_s:.0f}s")
    else:
        console.print(f"[red]Research failed[/red] (exit {state.exit_code})")

    tail = session.capture(lines=20)
    if tail:
        console.print(Panel(tail, title="[dim]last output[/dim]", border_style="red"))
