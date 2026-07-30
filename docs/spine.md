# Spine architecture (Lane A) — full reference

_Owner: harsha (`Haise-727`) · Companion to [TEAM-WORKFLOW.md](TEAM-WORKFLOW.md); the
loop this implements is described narratively in [research.md](research.md)._

> **Who this doc is for:** anyone implementing a Lane B (`integrations/`), Lane C
> (`sessions/`), or Lane D (`checks/`, `mesh/`, `notify.py`, `pr_description.py`)
> module — including an AI coding session picking up one of those issues cold. It
> tells you exactly which methods to implement, what they receive and must return,
> and how your class gets discovered and wired in. It is intentionally long and
> code-heavy rather than summarized, so a fresh session (human or AI) can work from
> this file alone without re-reading all of `contracts.py`/`pipeline.py`/`review.py`
> first — every signature quoted here is copied verbatim from source.

---

## 1. Overview

The **Spine** is the architectural backbone every other lane plugs into. It owns:

| File | Role | Status |
|------|------|--------|
| `contracts.py` | **Frozen** shared types + adapter Protocols — the *only* cross-lane surface | done |
| `config.py` | Strict Pydantic schema + fail-loud loader for `devOrchestrator.yaml` | done |
| `pipeline.py` | The SDLC loop orchestration (task → branch → research → implement → checks → PR) | done, Wave-3 pending |
| `review.py` | The TL approval gate (`AI → Human` boundary) | done, Wave-3 pending |
| `cli.py` | Command dispatch (`init/start/pr/review/status/mesh/decision`) | done |
| `pyproject.toml`, `devOrchestrator.yaml.template` | Packaging + shareable config | done |

**The one idea that makes the whole thing work:** `pipeline.py` and `review.py`
**never import another lane's module.** They only know about the `Protocol` classes
defined in `contracts.py`, and receive concrete implementations by **constructor
injection**:

```python
Pipeline(config, board=…, git=…, research=…, impl=…, checks=…, mesh=…, notifier=…)
             │
             └── calls only the small documented method surface of each Protocol
```

This is why the whole Spine could be built and fully unit-tested *before* any other
lane's code existed — `tests/conftest.py` provides in-memory fakes that satisfy the
Protocols structurally (no inheritance, no imports of real lanes), and
`tests/test_pipeline.py` / `tests/test_review.py` drive the entire loop against them.
It's also why your adapter, once written, doesn't require touching `pipeline.py` or
`review.py` at all — it just needs to satisfy the right Protocol's shape.

---

## 2. `contracts.py` — full reference

This file is **frozen**: per the golden rule in `TEAM-WORKFLOW.md`, if you need a new
shared type, ask the Spine owner (harsha) to add it — don't edit this file yourself.
Two exceptions have happened so far and are both already in: the review-flow
`GitAdapter` methods (added in the `spine-review-contract-flow` work) and nothing
else. Everything below is current as of that state.

### Enums

```python
class Priority(StrEnum):      # normalized task priority; adapters map onto these
    urgent = "urgent"; high = "high"; medium = "medium"; low = "low"; none = "none"

class IssueState(StrEnum):    # normalized board state, aligned to board columns
    backlog = "backlog"; ready = "ready"; in_progress = "in_progress"
    in_review = "in_review"; done = "done"

class CheckStatus(StrEnum):
    passed = "passed"; failed = "failed"; skipped = "skipped"

class MergeStrategy(StrEnum):
    merge = "merge"; squash = "squash"; rebase = "rebase"
```

### Value objects

All are `@dataclass(frozen=True, slots=True)` — immutable, cheap to pass around, no
Pydantic (validation lives in `config.py` only; contracts stay dependency-light).
`PipelineContext` is the one exception (see below — it's mutable on purpose).

```python
@dataclass(frozen=True, slots=True)
class Issue:
    """A task fetched from the board. Produced by Lane B's BoardAdapter."""
    id: str
    title: str
    description: str = ""
    priority: Priority = Priority.none
    estimate: int | None = None
    state: IssueState = IssueState.ready
    assignee: str | None = None
    url: str | None = None

    def branch_slug(self) -> str:
        """`feature/issue-<id>-<slug>` body, per TEAM-WORKFLOW.md naming.
        e.g. Issue(id="9", title="Add widget").branch_slug() == "issue-9-add-widget"
        """
```

```python
@dataclass(frozen=True, slots=True)
class BranchRef:
    """A branch created on the git server. Produced by Lane B's GitAdapter."""
    name: str
    issue_id: str
    base: str = "dev"
    url: str | None = None
```

```python
@dataclass(frozen=True, slots=True)
class Artifact:
    """The research spec handed from the research session to implementation.
    Produced by Lane C. `path` + `raw` are always authoritative — the implementation
    session reads the file directly; `modules_affected` is best-effort parsing
    (pipeline.py extracts it from a 'Files to Create/Modify' section) used only for
    mesh conflict detection.
    """
    path: str
    issue_id: str
    branch: str
    raw: str = ""
    modules_affected: tuple[str, ...] = ()
```

```python
@dataclass(frozen=True, slots=True)
class CheckResult:
    """One quality-gate result. Produced by Lane D's CheckRunner."""
    tool: str
    status: CheckStatus
    output: str = ""
    duration_s: float = 0.0

    @property
    def passed(self) -> bool:
        return self.status is CheckStatus.passed
```

```python
@dataclass(frozen=True, slots=True)
class PullRequest:
    """A pull request. Produced by Lane B's GitAdapter.open_pr."""
    number: int
    title: str
    url: str
    branch: str
    base: str = "dev"
```

```python
@dataclass(frozen=True, slots=True)
class Decision:
    """An architectural decision logged to the mesh. Lane D (mesh)."""
    description: str
    dev: str
    affected_modules: tuple[str, ...] = ()
    ts: str | None = None  # ISO-8601; set by the mesh writer
```

```python
@dataclass(frozen=True, slots=True)
class DevActivity:
    """Who is touching what, read from the mesh. Lane D (mesh)."""
    dev: str
    module: str
    branch: str
    event_type: str
    ts: str
```

```python
@dataclass(slots=True)   # NOT frozen — this one accumulates across the loop
class PipelineContext:
    """Mutable state threaded through one run of the pipeline (Lane A owns).
    Each stage fills in its slice; later stages read what earlier ones produced."""
    issue: Issue
    branch: BranchRef | None = None
    artifact: Artifact | None = None
    checks: list[CheckResult] = field(default_factory=list)
    pull_request: PullRequest | None = None
```

### Adapter Protocols — what you implement

These are `typing.Protocol` classes (`@runtime_checkable`) — **structural typing**.
Your class does not need to inherit from anything or import `contracts.py` at all
for `isinstance()` checks to work; it just needs matching method names/signatures.
In practice you'll still import the Protocol for type hints and the value objects it
returns.

**`BoardAdapter`** — Lane B (Plane / Azure Boards):
```python
class BoardAdapter(Protocol):
    def fetch_issues(self) -> list[Issue]: ...
    def move_issue(self, issue_id: str, state: IssueState) -> None: ...
```

**`GitAdapter`** — Lane B (Gitea / Azure Repos). Split into two groups: the first
three drive `pipeline.py` (`start`/`pr`); the review methods drive `review.py`. All
additive — if you're only wiring the pipeline first, implement the first three and
stub the rest (raise `NotImplementedError` or return empty) until review is wired:
```python
class GitAdapter(Protocol):
    def create_branch(self, issue: Issue, base: str = "dev") -> BranchRef: ...
    def open_pr(self, branch: BranchRef, title: str, body: str) -> PullRequest: ...
    def merge_pr(self, pr: PullRequest, strategy: MergeStrategy) -> None: ...

    # -- review flow --
    def list_open_prs(self, assignee: str | None = None) -> list[PullRequest]: ...
    def get_diff(self, pr: PullRequest) -> str: ...
    def get_ci_status(self, pr: PullRequest) -> str: ...
    def comment_pr(self, pr: PullRequest, body: str) -> None: ...
```

**`AgentSession`** — Lane C (a research or implementation session in a tmux pane).
Two instances are needed per pipeline run (one for research, one for implementation)
— `pipeline.py` calls `.run(prompt)` and expects the session to have done its work
(e.g. written the artifact file, or edited the codebase) by the time `.run()` returns:
```python
class AgentSession(Protocol):
    def run(self, prompt: str) -> None: ...
    def is_alive(self) -> bool: ...
```

**`CheckRunner`** — Lane D (ruff / gitleaks / pytest as subprocesses):
```python
class CheckRunner(Protocol):
    def run_all(self) -> list[CheckResult]: ...
```

**`Mesh`** — Lane D (shared context store):
```python
class Mesh(Protocol):
    def emit(self, event_type: str, module: str, payload: dict) -> None: ...
    def who_is_touching(self, module: str) -> list[DevActivity]: ...
    def recent_decisions(self, limit: int = 10) -> list[Decision]: ...
```

**`Notifier`** — Lane D (Mattermost / Teams webhook):
```python
class Notifier(Protocol):
    def notify(self, message: str) -> None: ...
```

`mesh` and `notifier` are **optional** everywhere in `Pipeline`/`ReviewGate`
(`mesh: Mesh | None = None`) — every call site null-checks before using them, so a
partially-wired pipeline (e.g. checks + board + git but no mesh yet) still runs.
`board`, `git`, `research`, `impl`, `checks` are **required**.

---

## 3. `config.py` — schema + loader reference

### Schema (Pydantic v2, `extra="forbid"` everywhere)

```python
class Config(_Strict):
    name: str                          # dev's name; used in mesh + notifications
    role: Role = Role.dev              # dev | tl
    agent: Agent = Agent.claude        # claude | agy

    board: BoardConfig                 # required
    git: GitConfig                     # required
    brain: BrainConfig | None = None   # optional — external LLM for PR descriptions
    notify: NotifyConfig | None = None # optional
    mesh: MeshConfig = MeshConfig()    # optional, defaults shown below

    autofix_retries: int = 2           # >= 0; how many times pipeline.py retries impl on check failure

    @property
    def track(self) -> Track:          # "oss" or "azure", auto-detected from board.type
        ...

class BoardConfig(_Strict):
    type: BoardType       # plane | azure_boards
    url: str
    token_env: str        # name of the env var holding the token — NOT the secret itself

class GitConfig(_Strict):
    type: GitType          # gitea | azure_repos — must agree with board's track
    url: str
    token_env: str

class BrainConfig(_Strict):
    provider: str = "openrouter"
    model: str = "deepseek/deepseek-v4-flash"
    token_env: str

class NotifyConfig(_Strict):
    type: NotifyType       # mattermost | teams
    webhook_env: str

class MeshConfig(_Strict):
    db_path: str = ".orchestrator/mesh.db"
```

**Every field ending in `_env` holds an environment variable *name*, never a
secret value.** The loader resolves the variable and fails loudly if it's unset —
this is why `.env` never needs to be read directly by any lane's code.

### The loader: `load_config(directory=None, *, check_env=True) -> Config`

```python
from devorchestrator.config import load_config, ConfigError

config = load_config(".", check_env=True)   # raises ConfigError on any problem
```

Order of operations, each with a distinct failure mode:
1. **File presence** — `devOrchestrator.yaml` must exist in `directory` (default
   CWD). Missing → `ConfigError` with hint *"copy devOrchestrator.yaml.template..."*
2. **`.env` merge** — `python-dotenv` loads `.env` from the same directory into the
   process environment before anything else runs.
3. **YAML parse** — malformed YAML → `ConfigError` with a whitespace-sensitivity hint.
4. **Empty / non-mapping file** — explicit checks with their own hints (not just a
   generic Pydantic error).
5. **Schema validation** — `Config.model_validate(raw)`; any `ValidationError` is
   reformatted into `    field.path: message` lines, one per offending field.
6. **Track agreement** — `board.type` and `git.type` must be the same family (both
   OSS: `plane`+`gitea`, or both Azure: `azure_boards`+`azure_repos`). Mismatch
   raises with a hint naming exactly which field to change.
7. **Env var presence** (only if `check_env=True`) — every referenced `*_env` /
   `*_webhook_env` must resolve to a non-empty environment variable, or `ConfigError`
   lists all missing ones at once (not one-by-one — a dev fixes `.env` in one pass).

**`ConfigError`** always carries a `.hint` — a one-line, actionable fix. `str(exc)`
already includes it (`f"{message}\n  → {hint}"`), so printing the exception is
enough; no separate hint-formatting logic needed by callers.

`cli.py`'s `_load_or_exit(ctx, *, check_env=True)` is the canonical way commands get
a `Config` — it calls `load_config`, catches `ConfigError`, prints it, and exits with
code 2. **Every command should go through this, not `load_config` directly**, so
error rendering + exit codes stay consistent across the CLI.

---

## 4. `pipeline.py` — walkthrough

`Pipeline` is deliberately **UI-free**. It never touches Rich or prints directly;
human-facing progress goes through an injected `on_event: Callable[[str], None]`
callback (the CLI wires this to `console.print`; tests capture it into a list).

### Construction

```python
Pipeline(
    config,                       # devorchestrator.config.Config
    *,
    board: BoardAdapter,
    git: GitAdapter,
    research,                     # AgentSession — research session
    impl,                         # AgentSession — implementation session
    checks: CheckRunner,
    mesh: Mesh | None = None,
    notifier: Notifier | None = None,
    describe_pr: Callable[[PipelineContext], str] | None = None,   # defaults to a plain-text summary
    workdir: Path | str = ".orchestrator",
    on_event: Callable[[str], None] | None = None,
)
```

### `start(select: Callable[[list[Issue]], Issue | None]) -> PipelineContext`

Step by step:
1. `board.fetch_issues()` — if empty, raise `PipelineAborted("no open tasks...")`.
2. `select(issues)` — the caller's picker (a Rich arrow-key menu from Lane B, or a
   plain lambda in tests). If it returns `None`, raise `PipelineAborted("no task selected.")`.
3. `git.create_branch(issue, base="dev")` → `BranchRef`.
4. Emit mesh event `task_started` with `{issue_id, title, branch}`, keyed by the
   branch name as the "module" (see `_primary_module`).
5. Build the artifact path: `{workdir}/{branch.name}/artifact.md`; create parent dirs.
6. `research.run(prompt)` where `prompt` is built by `_research_prompt(issue, branch, artifact_path)`
   — instructs the session to read the codebase, identify risks, and write the
   artifact with sections *Context, Sub-tasks, Files to Create/Modify, Acceptance
   Criteria, Implementation Notes* (and to list affected file paths so conflict
   detection works).
7. Read the artifact back from disk (`_read_artifact`) — parses `modules_affected`
   out of the raw text (`_parse_modules`: looks for `path/like/this.py`-shaped tokens
   on each line, best-effort, never blocks on failure to parse).
8. **Conflict check** (`_warn_on_conflicts`): for each affected module, call
   `mesh.who_is_touching(module)`; for any activity where `dev != config.name`, emit
   a human-readable warning via `on_event`. **Non-blocking** — it warns, it doesn't stop.
9. Emit mesh event `artifact_generated` with `{branch, artifact_path, modules_affected}`.
10. `impl.run(prompt)` where `prompt` is `_impl_prompt(artifact_path)` — "read the
    artifact, implement every sub-task, check off each as you complete it."
11. Return the populated `PipelineContext` (`issue`, `branch`, `artifact` all set;
    `checks`/`pull_request` still empty — that's `prepare_pr`'s job).

### `prepare_pr(ctx: PipelineContext, *, autofix: bool = True) -> PipelineContext`

1. `ctx.checks = checks.run_all()`.
2. If any failed and `autofix`, loop up to `config.autofix_retries` times (default
   **2**): build a fix prompt (`_fix_prompt`) embedding each failing tool's name and
   truncated output (first 500 chars), re-run `impl.run(fix_prompt)`, re-run
   `checks.run_all()`. Stops early the moment a batch is all-green.
3. If still failing after the retry budget, raise `PipelineError("checks still
   failing after autofix: <tool names>")` — the CLI/caller decides what to do (today:
   propagate as an unhandled exception; nothing catches it yet since Wave-3 isn't wired).
4. `describe_pr(ctx)` → PR body (defaults to `_default_pr_description`: title +
   description + a checklist of pass/fail per check tool; Lane D's
   `pr_description.generate_pr_description` is meant to replace this via the
   `describe_pr=` constructor argument once wired).
5. `git.open_pr(branch, title=issue.title, body=body)` → `PullRequest`; store on `ctx`.
6. Emit mesh event `pr_opened` with `{branch, pr_url, pr_number}`.
7. `notifier.notify(f"PR ready: {issue.title} — {pr.url}")`.

### Errors you can catch

```python
class PipelineError(Exception): ...          # base class
class PipelineAborted(PipelineError): ...     # human declined / nothing to do
class LanePending(PipelineError):             # a required adapter module isn't built yet
    component: str   # e.g. "board"
    where: str        # e.g. "Lane B: integrations/github_board.py"
```

### The Wave-3 factory: `build_pipeline(config, *, workdir=".orchestrator", on_event=None) -> Pipeline`

This is **the single seam** where concrete adapters get wired in. Today it checks
whether each required adapter module is importable (`importlib.util.find_spec`,
catching `ModuleNotFoundError` — that exception is raised, not returned as `None`,
when the *parent package* doesn't exist yet, e.g. `devorchestrator.integrations`
doesn't exist at all) and raises `LanePending(component, where)` for the first one
missing:

```python
_REQUIRED_ADAPTERS = [
    ("board",    "devorchestrator.integrations.github_board", "Lane B: integrations/github_board.py"),
    ("git",      "devorchestrator.integrations.github_git",   "Lane B: integrations/github_git.py"),
    ("sessions", "devorchestrator.sessions.tmux_runner",       "Lane C: sessions/tmux_runner.py"),
    ("checks",   "devorchestrator.checks.runner",              "Lane D: checks/runner.py"),
]
```

Once all four modules exist, the `# TODO(wave-3)` comment marks where real
construction goes — `Pipeline(config, board=GitHubBoard(config), git=GitHubGit(config),
research=TmuxSession(...), impl=TmuxSession(...), checks=SubprocessCheckRunner(...),
mesh=..., notifier=..., on_event=on_event)`. **The `Pipeline` class itself does not
change** when this lands — only this factory function's body does.

**If you're implementing a Lane B/C adapter:** you don't need to touch this factory
at all to get your own module tested — just make sure your class satisfies the
Protocol shape and your module path matches the ones above (or ask harsha to update
the path list if your module lives somewhere else). The Spine owner does the actual
Wave-3 wiring in `build_pipeline`/`build_review`.

---

## 5. `review.py` — walkthrough

`ReviewGate` is the `AI → Human` boundary — where the escalation model lands.

### Construction
```python
ReviewGate(
    config,
    *,
    git: GitAdapter,
    mesh: Mesh | None = None,
    notifier: Notifier | None = None,
    console: Console | None = None,           # rich.console.Console; defaults to a real one
    merge_strategy: MergeStrategy = MergeStrategy.squash,
)
```

### Fetching
- `open_prs() -> list[PullRequest]` — `git.list_open_prs(assignee=config.name)`,
  i.e. "PRs currently waiting on me as reviewer."
- `review_pr(pr, checks, artifact=None) -> None` — pulls `git.get_diff(pr)` and
  `git.get_ci_status(pr)` fresh from the git server, then calls `render(...)`. The
  check results and artifact are **not** re-fetched here — they come from the
  pipeline run the CLI already has in memory.

### `render(pr, diff, checks, artifact=None, ci_status="unknown") -> None`
Renders a **single vertical stack** of Rich panels (not a fragile 3-pane split —
per the Sprint-2 carry-over note in `docs/sprint-2.md`, functionality over layout
polish): header (`#N title → base`), the diff (`rich.syntax.Syntax`, diff lexer),
a checks table (`tool | ✓/✗ | duration`, titled with the CI status), the artifact
as rendered Markdown if present, and a footer reminding the keybindings
(`[a] approve & merge  [r] reject  [o] open in browser  [q] quit`). Takes its
inputs as plain arguments — it does not fetch anything itself, so it's directly
unit-testable with hand-built fakes (see `tests/test_review.py`).

### Actions
- `approve(pr) -> ReviewDecision` — `git.merge_pr(pr, merge_strategy)`, emits mesh
  event `pr_merged`, notifies `"✅ Merged: {title} — {url}"`.
- `reject(pr, reason) -> ReviewDecision` — `git.comment_pr(pr, f"Changes requested: {reason}")`,
  emits mesh event `pr_rejected`, notifies `"❌ PR rejected: {reason} — {url}"`.

`ReviewDecision` is a small frozen dataclass (`action: "approved"|"rejected"`, `pr`,
`reason=""`) returned so the CLI can report the outcome uniformly regardless of
which branch was taken.

### The Wave-3 factory: `build_review(config, *, console=None) -> ReviewGate`
Same pattern as `build_pipeline`: checks `devorchestrator.integrations.github_git`
is importable, raises `LanePending("git", "Lane B: integrations/github_git.py")`
if not. Once it exists, the `# TODO(wave-3)` marks where `ReviewGate(config, git=GiteaGit(config), mesh=..., notifier=...)`
gets constructed for real.

---

## 6. Building an adapter — copy-paste skeletons

Minimal shape needed to satisfy each Protocol. These are **not** meant to be
production-complete — they're the smallest thing that would type-check and let you
run the pipeline/review flow end-to-end while you fill in the real API calls.

**`BoardAdapter`** (Lane B):
```python
from devorchestrator.contracts import Issue, IssueState

class MyBoard:
    def __init__(self, config): ...

    def fetch_issues(self) -> list[Issue]:
        # GET the board's API, map each item to Issue(id=..., title=..., ...)
        return [...]

    def move_issue(self, issue_id: str, state: IssueState) -> None:
        # PATCH/POST to move the card
        ...
```

**`GitAdapter`** (Lane B):
```python
from devorchestrator.contracts import BranchRef, Issue, MergeStrategy, PullRequest

class MyGit:
    def __init__(self, config): ...

    def create_branch(self, issue: Issue, base: str = "dev") -> BranchRef:
        return BranchRef(name=f"feature/{issue.branch_slug()}", issue_id=issue.id, base=base)

    def open_pr(self, branch: BranchRef, title: str, body: str) -> PullRequest: ...
    def merge_pr(self, pr: PullRequest, strategy: MergeStrategy) -> None: ...

    # review flow — stub these first if only wiring the pipeline for now
    def list_open_prs(self, assignee: str | None = None) -> list[PullRequest]:
        return []

    def get_diff(self, pr: PullRequest) -> str:
        return ""

    def get_ci_status(self, pr: PullRequest) -> str:
        return "unknown"

    def comment_pr(self, pr: PullRequest, body: str) -> None:
        pass
```

**`AgentSession`** (Lane C — one instance for research, another for impl):
```python
class MyTmuxSession:
    def __init__(self, pane_name: str): ...

    def run(self, prompt: str) -> None:
        # send `claude -p "<prompt>"` to the tmux pane; block until the session exits
        ...

    def is_alive(self) -> bool:
        # poll the tmux pane
        ...
```

**`CheckRunner`** (Lane D):
```python
from devorchestrator.contracts import CheckResult, CheckStatus

class MyCheckRunner:
    def run_all(self) -> list[CheckResult]:
        # run ruff/gitleaks/pytest as subprocesses, capture pass/fail + output + timing
        return [CheckResult(tool="ruff", status=CheckStatus.passed, duration_s=0.4), ...]
```

**`Mesh`** (Lane D):
```python
from devorchestrator.contracts import Decision, DevActivity

class MyMesh:
    def emit(self, event_type: str, module: str, payload: dict) -> None: ...
    def who_is_touching(self, module: str) -> list[DevActivity]: ...
    def recent_decisions(self, limit: int = 10) -> list[Decision]: ...
```

**`Notifier`** (Lane D):
```python
class MyNotifier:
    def notify(self, message: str) -> None:
        # POST to a Mattermost/Teams webhook
        ...
```

Once your class satisfies a Protocol's shape, it's a drop-in for the corresponding
`Pipeline`/`ReviewGate` constructor argument — no other Spine code needs to change.
`@runtime_checkable` on each Protocol means you can even sanity-check this yourself:
```python
from devorchestrator.contracts import BoardAdapter
assert isinstance(MyBoard(config), BoardAdapter)   # True if the shape matches
```
(Note: `isinstance` against a `Protocol` only checks method *names* exist, not that
signatures match exactly — it's a smoke check, not a substitute for the real tests.)

---

## 7. Testing patterns

`tests/conftest.py` holds shared fakes + fixtures, all implementing the `contracts`
Protocols **structurally** — no inheritance, no import of real lane code:

| Fake | Satisfies | Notable behavior |
|------|-----------|-------------------|
| `FakeBoard(issues)` | `BoardAdapter` | returns a fixed list; records `move_issue` calls |
| `FakeGit(branch, *, open_prs=None, diff="", ci="unknown")` | `GitAdapter` | records merges/comments; `open_pr` always returns PR #7 |
| `FakeSession(write_path=None, content="")` | `AgentSession` | records every prompt it received; if `write_path` given, writes `content` there on `.run()` — simulates a research session producing an artifact |
| `FakeChecks(batches)` | `CheckRunner` | returns one preset `list[CheckResult]` per call to `run_all()`, in order — lets a test script "fails once, then passes" for autofix scenarios |
| `FakeMesh(touching=None)` | `Mesh` | records every `emit()`; `who_is_touching(module)` returns whatever you seed it with, to test conflict warnings |
| `FakeNotifier()` | `Notifier` | records every message |

Helpers: `make_config(**overrides)` builds a minimal valid `Config` for tests;
`passing(tool="pytest")` / `failing(tool="pytest", output="1 failed")` build
`CheckResult`s quickly. Fixtures `branch` and `issue` give a ready-made
`BranchRef`/`Issue` pair (`issue-9-widget` / `Add widget`).

**Note:** `tests/` is not a Python package (no `tests/__init__.py`) — test modules
import the shared fakes with `from conftest import ...` (not `from .conftest import
...`), since pytest's default rootdir-relative import mode doesn't support relative
imports here.

**Adding a new fake:** if a lane's Protocol needs a fake shape the existing ones
don't cover (e.g. a `Mesh` fake that raises on a specific event type to test error
handling), add it to `conftest.py` next to its siblings rather than duplicating one
inline in a test file — keeps every test file able to reuse it.

Run everything:
```bash
uv run pytest -q       # currently 33 passing
uv run ruff check .    # must stay clean
```

---

## 8. Troubleshooting / FAQ

**"`✗ config error` / `ConfigError`"** — always means something about
`devOrchestrator.yaml` or `.env`. Read the `→ hint` line; it names the exact fix
(missing file, bad YAML, unknown field, track mismatch, or a missing env var). See
§3 for the full list of checks the loader runs, in order.

**"`Spine is wired and ready — waiting on the <component> adapter`"** — this is
`LanePending`, not an error. It means `build_pipeline`/`build_review` looked for a
specific module (named in the message, e.g. `Lane B: integrations/github_git.py`)
and it doesn't exist yet. It resolves itself the moment that lane's module is
merged — no Spine change needed unless the module's path differs from what
`_REQUIRED_ADAPTERS` (in `pipeline.py`) or `_GIT_ADAPTER` (in `review.py`) expects.

**"My PR touches `cli.py`, `config.py`, `contracts.py`, `pipeline.py`, or
`review.py` — is that OK?"** — No, not without coordinating with the Spine owner
first. Per `TEAM-WORKFLOW.md`'s golden rules, these are Lane A files; a lane
independently rewriting them (even to wire in your own real module) breaks the
one-file-one-owner contract and **will** produce hard merge conflicts, because the
Spine may have moved those same functions to dispatch through `pipeline.py`/
`review.py` in the meantime. If your work needs a change here (a new contract type,
a config field, a CLI flag), ask harsha to make it — that keeps this file's history
predictable for everyone pulling `dev`.

**"Do I need `mesh`/`notifier` to test my adapter against the real pipeline?"** —
No. Both are optional (`None` by default) everywhere in `Pipeline`/`ReviewGate`;
every call site null-checks before using them. You can wire just `board`+`git`+
`research`+`impl`+`checks` and get a working `start()`/`prepare_pr()` with no mesh
events or notifications sent.

---

## 9. Try it

```bash
uv sync
uv run devorchestrator --help
cp devOrchestrator.yaml.template devOrchestrator.yaml
uv run devorchestrator init         # validates config + scaffolds .orchestrator/
uv run devorchestrator start        # friendly "waiting on Lane B" until adapters land
uv run pytest -q                     # 33 passing
uv run ruff check .                  # clean
```
