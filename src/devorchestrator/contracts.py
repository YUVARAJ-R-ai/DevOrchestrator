"""Shared contracts — the one file every lane depends on.

**This is the frozen coordination surface** (see docs/TEAM-WORKFLOW.md). Lanes talk
to each other *only* through the types and Protocols defined here — never by
importing another lane's internals. Lane B calls ``board.fetch_issues() -> list[Issue]``;
it does not care how Plane or GitHub is queried underneath.

Freeze rule: this file is written in Wave 1 and frozen afterward. If a lane needs
a new shared type, the Spine owner adds it here and everyone pulls — nobody edits
this file in parallel.

Design choices:
- **`@dataclass(frozen=True, slots=True)`** for data, not Pydantic: these are
  passed between modules cheaply and should be immutable value objects. Config
  validation (Pydantic) stays in ``config.py``; contracts stay dependency-light.
- **`typing.Protocol`** for the adapter interfaces so any lane's concrete class
  (GiteaGit, AzureRepos, ClaudeSession, …) satisfies the contract structurally,
  with no base class to import and no inheritance coupling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Enumerations (backend-agnostic — Plane/Gitea/Azure map their values onto these)
# ---------------------------------------------------------------------------


class Priority(StrEnum):
    """Normalized task priority. Adapters map their native values onto these."""

    urgent = "urgent"
    high = "high"
    medium = "medium"
    low = "low"
    none = "none"


class IssueState(StrEnum):
    """Normalized board state, aligned to the team's board columns."""

    backlog = "backlog"
    ready = "ready"
    in_progress = "in_progress"
    in_review = "in_review"
    done = "done"


class CheckStatus(StrEnum):
    passed = "passed"
    failed = "failed"
    skipped = "skipped"


class MergeStrategy(StrEnum):
    merge = "merge"
    squash = "squash"
    rebase = "rebase"


# ---------------------------------------------------------------------------
# Value objects passed between lanes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Issue:
    """A task fetched from the board. Produced by Lane B's ``BoardAdapter``."""

    id: str
    title: str
    description: str = ""
    priority: Priority = Priority.none
    estimate: int | None = None
    state: IssueState = IssueState.ready
    assignee: str | None = None
    url: str | None = None

    def branch_slug(self) -> str:
        """`feature/issue-<id>-<slug>` body, per docs/TEAM-WORKFLOW.md naming."""
        slug = "".join(c if c.isalnum() else "-" for c in self.title.lower())
        slug = "-".join(part for part in slug.split("-") if part)[:40].strip("-")
        return f"issue-{self.id}-{slug}"


@dataclass(frozen=True, slots=True)
class BranchRef:
    """A branch created on the git server. Produced by Lane B's ``GitAdapter``."""

    name: str
    issue_id: str
    base: str = "dev"
    url: str | None = None


@dataclass(frozen=True, slots=True)
class Artifact:
    """The research spec handed from the research session to implementation.

    Produced by Lane C. The parsed fields are best-effort; ``path`` + ``raw`` are
    always authoritative (the implementation session reads the file directly).
    """

    path: str
    issue_id: str
    branch: str
    raw: str = ""
    modules_affected: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One quality-gate result. Produced by Lane D's ``CheckRunner``."""

    tool: str
    status: CheckStatus
    output: str = ""
    duration_s: float = 0.0

    @property
    def passed(self) -> bool:
        return self.status is CheckStatus.passed


@dataclass(frozen=True, slots=True)
class PullRequest:
    """A pull request. Produced by Lane B's ``GitAdapter.open_pr``."""

    number: int
    title: str
    url: str
    branch: str
    base: str = "dev"


@dataclass(frozen=True, slots=True)
class Decision:
    """An architectural decision logged to the mesh. Lane D (``mesh``)."""

    description: str
    dev: str
    affected_modules: tuple[str, ...] = ()
    ts: str | None = None  # ISO-8601; set by the mesh writer


@dataclass(frozen=True, slots=True)
class DevActivity:
    """Who is touching what, read from the mesh. Lane D (``mesh``)."""

    dev: str
    module: str
    branch: str
    event_type: str
    ts: str


@dataclass(slots=True)
class PipelineContext:
    """Mutable state threaded through one run of the pipeline (Lane A owns).

    Each stage fills in its slice; later stages read what earlier ones produced.
    Kept mutable (not frozen) precisely because it accumulates across the loop.
    """

    issue: Issue
    branch: BranchRef | None = None
    artifact: Artifact | None = None
    checks: list[CheckResult] = field(default_factory=list)
    pull_request: PullRequest | None = None


# ---------------------------------------------------------------------------
# Adapter Protocols — the interfaces each lane implements
# ---------------------------------------------------------------------------


@runtime_checkable
class BoardAdapter(Protocol):
    """Task board (Plane / Azure Boards). Implemented by Lane B."""

    def fetch_issues(self) -> list[Issue]: ...
    def move_issue(self, issue_id: str, state: IssueState) -> None: ...


@runtime_checkable
class GitAdapter(Protocol):
    """Git server (Gitea / Azure Repos). Implemented by Lane B.

    The first three methods drive `start`/`pr`; the review methods below drive the
    TL approval gate (`review.py`). All are additive — a Lane B adapter that only
    needs the pipeline can implement the first three and stub the rest until review
    is wired.
    """

    def create_branch(self, issue: Issue, base: str = "dev") -> BranchRef: ...
    def open_pr(self, branch: BranchRef, title: str, body: str) -> PullRequest: ...
    def merge_pr(self, pr: PullRequest, strategy: MergeStrategy) -> None: ...

    # -- review flow --
    def list_open_prs(self, assignee: str | None = None) -> list[PullRequest]: ...
    def get_diff(self, pr: PullRequest) -> str: ...
    def get_ci_status(self, pr: PullRequest) -> str: ...
    def comment_pr(self, pr: PullRequest, body: str) -> None: ...


@runtime_checkable
class AgentSession(Protocol):
    """A research or implementation session in a tmux pane. Implemented by Lane C."""

    def run(self, prompt: str) -> None: ...
    def is_alive(self) -> bool: ...


@runtime_checkable
class CheckRunner(Protocol):
    """Quality gates (ruff / gitleaks / pytest). Implemented by Lane D."""

    def run_all(self) -> list[CheckResult]: ...


@runtime_checkable
class Mesh(Protocol):
    """Shared context mesh (SQLite). Implemented by Lane D."""

    def emit(self, event_type: str, module: str, payload: dict) -> None: ...
    def who_is_touching(self, module: str) -> list[DevActivity]: ...
    def recent_decisions(self, limit: int = 10) -> list[Decision]: ...


@runtime_checkable
class Notifier(Protocol):
    """Team notifications (Mattermost / Teams). Implemented by Lane D."""

    def notify(self, message: str) -> None: ...


__all__ = [
    # enums
    "Priority",
    "IssueState",
    "CheckStatus",
    "MergeStrategy",
    # value objects
    "Issue",
    "BranchRef",
    "Artifact",
    "CheckResult",
    "PullRequest",
    "Decision",
    "DevActivity",
    "PipelineContext",
    # protocols
    "BoardAdapter",
    "GitAdapter",
    "AgentSession",
    "CheckRunner",
    "Mesh",
    "Notifier",
]
