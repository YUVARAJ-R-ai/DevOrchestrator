"""The TL approval gate — `AI → Human` boundary of the escalation model.

Lane A's ``review.py`` (backlog #29–31). Renders what a team lead needs to decide
on a PR — the diff, the check results, and the artifact (what was *planned* vs what
was built) — then performs the approve (merge) or reject (comment + notify) action.

**Contract note (frozen `contracts.py` gap):** the review flow needs four methods
the current ``GitAdapter`` Protocol does not yet expose:
``list_open_prs(assignee)``, ``get_diff(pr)``, ``get_ci_status(pr)``, and
``comment_pr(pr, body)``. Until those are added to the frozen contract (Lane A's
call, everyone pulls), this gate takes the diff / checks / artifact as **inputs**
(the CLI or Lane B fetches them) and posts rejection feedback via the ``Notifier``.
Approve uses ``GitAdapter.merge_pr``, which *is* in the contract.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from .config import Config
from .contracts import (
    Artifact,
    CheckResult,
    GitAdapter,
    MergeStrategy,
    Mesh,
    Notifier,
    PullRequest,
)
from .pipeline import LanePending


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    """The outcome of a review; returned so the CLI can report it uniformly."""

    action: str  # "approved" | "rejected"
    pr: PullRequest
    reason: str = ""


class ReviewGate:
    """Renders a PR for review and executes the approve/reject decision."""

    def __init__(
        self,
        config: Config,
        *,
        git: GitAdapter,
        mesh: Mesh | None = None,
        notifier: Notifier | None = None,
        console: Console | None = None,
        merge_strategy: MergeStrategy = MergeStrategy.squash,
    ) -> None:
        self.config = config
        self.git = git
        self.mesh = mesh
        self.notifier = notifier
        self.console = console or Console()
        self.merge_strategy = merge_strategy

    # -- presentation -----------------------------------------------------

    def render(
        self,
        pr: PullRequest,
        diff: str,
        checks: list[CheckResult],
        artifact: Artifact | None = None,
        ci_status: str = "unknown",
    ) -> None:
        """Show diff | checks + CI | artifact for one PR.

        A single vertical stack of panels (not a fragile 3-pane split) — per the
        Sprint-2 carry-over note, functionality over layout polish.
        """
        header = f"[bold]#{pr.number}[/] {pr.title}  →  {pr.base}\n[dim]{pr.url}[/]"

        diff_panel = Panel(
            Syntax(diff or "(no diff)", "diff", theme="ansi_dark", word_wrap=True),
            title="diff", border_style="cyan",
        )

        checks_table = Table(title=f"checks · CI: {ci_status}", show_header=True, expand=True)
        checks_table.add_column("tool")
        checks_table.add_column("result")
        checks_table.add_column("time", justify="right")
        for c in checks:
            mark = "[green]✓ pass[/]" if c.passed else "[red]✗ fail[/]"
            checks_table.add_row(c.tool, mark, f"{c.duration_s:.1f}s")

        panels = [Panel(header, border_style="magenta"), diff_panel, checks_table]
        if artifact is not None and artifact.raw:
            panels.append(Panel(Markdown(artifact.raw), title="artifact (planned)",
                                border_style="green"))
        panels.append(Panel("[a] approve & merge   [r] reject   [o] open in browser   [q] quit",
                            border_style="dim"))
        self.console.print(Group(*panels))

    # -- actions ----------------------------------------------------------

    def approve(self, pr: PullRequest) -> ReviewDecision:
        """Merge the PR, delete the source branch, record + notify."""
        self.git.merge_pr(pr, self.merge_strategy)
        self._emit("pr_merged", module=pr.branch, payload={
            "pr_number": pr.number, "pr_url": pr.url, "by": self.config.name,
        })
        self._notify(f"✅ Merged: {pr.title} — {pr.url}")
        return ReviewDecision(action="approved", pr=pr)

    def reject(self, pr: PullRequest, reason: str) -> ReviewDecision:
        """Reject the PR: notify the dev with the reason.

        (Posting the reason as an on-PR comment needs ``GitAdapter.comment_pr``,
        which is not in the frozen contract yet — see the module docstring.)
        """
        self._emit("pr_rejected", module=pr.branch, payload={
            "pr_number": pr.number, "reason": reason, "by": self.config.name,
        })
        self._notify(f"❌ PR rejected: {reason} — {pr.url}")
        return ReviewDecision(action="rejected", pr=pr, reason=reason)

    # -- internals --------------------------------------------------------

    def _emit(self, event_type: str, *, module: str, payload: dict) -> None:
        if self.mesh is not None:
            self.mesh.emit(event_type, module, payload)

    def _notify(self, message: str) -> None:
        if self.notifier is not None:
            self.notifier.notify(message)


# ---------------------------------------------------------------------------
# Factory — the Wave-3 integration seam (mirrors pipeline.build_pipeline)
# ---------------------------------------------------------------------------

_GIT_ADAPTER = ("git", "devorchestrator.integrations.github_git",
                "Lane B: integrations/github_git.py")


def build_review(config: Config, *, console: Console | None = None) -> ReviewGate:
    """Construct a ReviewGate wired to the real git adapter for ``config``.

    Raises :class:`LanePending` until Lane B's git adapter lands; Wave-3 fills in
    the construction. The ``ReviewGate`` class above does not change.
    """
    import importlib.util

    component, module, where = _GIT_ADAPTER
    try:
        spec = importlib.util.find_spec(module)
    except ModuleNotFoundError:
        spec = None  # parent package (the lane) doesn't exist yet
    if spec is None:
        raise LanePending(component, where)
    # TODO(wave-3): return ReviewGate(config, git=<GiteaGit(config)>, mesh=..., notifier=...)
    raise LanePending("wiring", "Lane A: review.build_review (Wave-3 integration)")
