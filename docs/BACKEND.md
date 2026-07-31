# Backend Reference

> Concise map of the whole backend: the spine, the stack, and every external API we actually call.
> Written against `dev` — verified against the code, not the design docs.
> Companion to [spine.md](spine.md) (deep Lane A reference) and [MCP.md](MCP.md).

---

## 1 · Shape of the system

There is no HTTP server. **DevOrchestrator is a CLI that orchestrates other people's APIs.** It exposes exactly one network listener — the optional MCP server — and everything else is outbound calls.

```
                    ┌──────────────────────────────────────┐
   devorchestrator  │            THE SPINE                 │
   <command>  ─────▶│  cli.py → pipeline.py / review.py    │
                    │  config.py · contracts.py (frozen)   │
                    └───┬──────┬──────┬──────┬──────┬──────┘
                        │      │      │      │      │
              ┌─────────┘      │      │      │      └─────────┐
              ▼                ▼      ▼      ▼                ▼
        integrations/     sessions/  checks/  mesh/       notify.py
        GitHub REST       claude CLI  ruff    Supabase    webhook
        GitHub GraphQL    in tmux     pytest  Postgres    (MM/Teams)
                               │
                               └── brain.py → SiliconFlow (OpenAI-compatible)
```

**Dependency rule:** lanes talk only through `contracts.py`. Nothing imports another lane's internals. The spine holds `Protocol` references, never concrete classes — which is why every adapter is swappable and every test can inject a fake.

---

## 2 · Stack

| Layer | Choice | Why |
|:--|:--|:--|
| Language | **Python 3.12+** | `StrEnum`, `slots=True` dataclasses, modern typing |
| Config | **Pydantic v2** (`extra="forbid"`) | Typos in yaml fail loud instead of silently defaulting |
| CLI | **Typer** + **Rich** | Terminal is the product surface, not an afterthought |
| HTTP | **httpx** (sync `Client`) | One client per adapter, injectable for tests |
| Agent runtime | **`claude` CLI** in **libtmux** panes | Pro subscription, no API key; the watchable pane *is* the feature |
| Shared memory | **Supabase / Postgres** | Hosted, queryable, multi-writer. Replaced the original SQLite plan |
| Brain | **OpenAI SDK** → SiliconFlow | Only for text transformation; never touches the repo |
| Gates | **ruff**, **pytest** as subprocesses | Not gitleaks — that was planned, never wired |
| MCP | **FastMCP** | Exposes the mesh as tools to any agent |
| Packaging | **uv** | Lock drift is now guarded by `tests/test_packaging.py` |

---

## 3 · The Spine

Four files. Everything else is an adapter behind a Protocol.

### `contracts.py` — the frozen coordination surface

Written once in Wave 1, frozen after. `@dataclass(frozen=True, slots=True)` for data, `typing.Protocol` for interfaces — structural typing, so no lane inherits from anything.

**Value objects:** `Issue` · `BranchRef` · `Artifact` · `CheckResult` · `PullRequest` · `Decision` · `DevActivity`
**Mutable:** `PipelineContext` — the one thing that accumulates across a run
**Protocols:** `BoardAdapter` · `GitAdapter` · `AgentSession` · `CheckRunner` · `Mesh` · `Notifier`

> `Issue.branch_slug()` lives here because branch naming is a cross-lane contract, not Lane B trivia.

> [!NOTE]
> **Two drifts for the spine owner to rule on** (both real, neither breaking anything today):
>
> 1. **`SessionActivity` is defined in `mesh/store.py`, not here** — yet it's returned by mesh reads and consumed by `mesh/dashboard.py` and the MCP server. A cross-lane value object living inside one lane's implementation is precisely what `contracts.py` exists to prevent.
> 2. **The `Mesh` protocol has fallen behind its implementation.** It declares `emit` / `who_is_touching` / `recent_decisions` / `list_modules`; `SupabaseMesh` also ships `healthy`, `register_dev`, `team_roster`, `active_sessions`, `session_history`. Callers using the extras are typed against a protocol that doesn't describe them, so a second `Mesh` implementation would satisfy the contract and still break the dashboard.
>
> Its docstring also still says *"(SQLite)"*, from before the Supabase pivot.

### `config.py` — validation that fails loud

```
Config
├── name, role (dev|tl), agent (claude|agy), autofix_retries
├── board:  type, url, token_env, project_number      ← required
├── git:    type, url, token_env, reviewer            ← required
├── brain:  provider, model, token_env                ← optional
├── notify: type, webhook_env                         ← optional
└── mesh:   supabase_url, supabase_key_env            ← optional
```

Two validations worth knowing:

- **Track agreement** — `board.type` and `git.type` must be the same backend family. A `plane` board with a `github` git raises `ConfigError` with a fix hint, rather than failing confusingly deep inside a URL parse.
- **Env var presence** — every `*_env` field is checked to actually exist in the environment. Missing raises `ConfigError`, never a bare `KeyError` at request time.

**Secret loading.** `.env` is read from the config directory with `load_dotenv(..., override=True)` — **the file wins over existing shell exports.** That's deliberate: someone who ran `source .env` while it was still blank ends up with empty vars exported in their shell, and without `override` those stale blanks would shadow the real values forever. If you export a token deliberately and it appears not to take effect, this is why.

### `pipeline.py` — the loop

```python
Pipeline.start(select) -> PipelineContext
```
1. `board.fetch_issues()` → `select()` (human picks) → `PipelineAborted` if none
2. `git.create_branch()` → local checkout → board Status → **In Progress**
3. Research session writes `artifact.md` → `load_artifact()`
4. Conflict warning if another dev is in the same modules (non-blocking)
5. Implementation session → `git add -A` → commit → push
6. `save_pipeline_context()` → `.orchestrator/{branch}/context.json`

```python
Pipeline.prepare_pr(ctx, autofix=True) -> PipelineContext
```
1. `checks.run_all()` → while failing and budget remains, re-invoke the agent with `prompts/autofix.md`
2. Still failing → `PipelineError`
3. `git.open_pr()` with brain-written body → board Status → **In Review** → notify

**Why `start` and `pr` are separate processes:** the human reviews code in between. That's the reason `PipelineContext` is persisted to disk at all.

**Exceptions:** `PipelineError` (base) · `PipelineAborted` (user's fault, actionable) · `LanePending` (adapter module missing)

**Guards:** `_require_clean_tree()` refuses to run on a dirty tree — `git add -A` would otherwise sweep unrelated edits into the commit. `_git()` raises `PipelineError` carrying git's own stderr instead of discarding it.

### `review.py` — the TL gate

`ReviewGate.open_prs()` → `render()` (diff · CI · checks · artifact side by side) → `approve()` / `reject(reason)`. Both outcomes emit to the mesh and notify.

### Wiring: `build_pipeline(config)`

Probes for each adapter module via `importlib.util.find_spec` and raises `LanePending(component, where)` naming the file that's missing. Optional dependencies are constructed only if configured:

| Component | Built when |
|:--|:--|
| board, git | always (GitHub only today; other types raise `LanePending`) |
| sessions | always — `ClaudeSession(research)`, `ClaudeSession(impl)` |
| checks | always — `SubprocessCheckRunner` |
| mesh | `mesh.supabase_url` set **and** key env var present |
| notifier | `notify` block present |
| brain | `brain` block present |

---

## 4 · External APIs — what we call

### 4.1 GitHub REST · `https://api.github.com`

Auth: `Authorization: Bearer $GITHUB_TOKEN`, `Accept: application/vnd.github+json`, 15s timeout.

| Method | Endpoint | Used by |
|:--|:--|:--|
| `GET` | `/repos/{o}/{r}/git/ref/heads/{base}` | `create_branch` — resolve base SHA |
| `POST` | `/repos/{o}/{r}/git/refs` | `create_branch` |
| `PATCH` | `/repos/{o}/{r}/git/refs/heads/{branch}` | `create_branch` — **422 fallback**, resets an existing branch so re-runs are idempotent |
| `POST` | `/repos/{o}/{r}/pulls` | `open_pr` — prepends `Closes #N` |
| `POST` | `/repos/{o}/{r}/pulls/{n}/requested_reviewers` | `open_pr` — best-effort, never fails PR creation |
| `PUT` | `/repos/{o}/{r}/pulls/{n}/merge` | `merge_pr` |
| `GET` | `/repos/{o}/{r}/pulls` `?state=open` | `list_open_prs` |
| `GET` | `/repos/{o}/{r}/pulls/{n}` | `get_ci_status` — resolve head SHA |
| `GET` | `/repos/{o}/{r}/pulls/{n}` + `Accept: application/vnd.github.v3.diff` | `get_diff` — returns `resp.text`, not JSON |
| `GET` | `/repos/{o}/{r}/commits/{sha}/check-runs` | `get_ci_status` |
| `POST` | `/repos/{o}/{r}/issues/{n}/comments` | `comment_pr` — rejection reason |
| `GET` | `/repos/{o}/{r}/issues` `?assignee=&state=open` | `fetch_issues` REST fallback |
| `GET` | `/user` | `init` — token valid at all? |
| `GET` | `/repos/{o}/{r}` | `init` — can the token see this repo? |

### 4.2 GitHub GraphQL · `https://api.github.com/graphql`

Projects v2 only — Priority/Size fields and the Status column aren't in REST.

| Operation | Purpose |
|:--|:--|
| `query($owner,$repo,$number)` → `projectV2.items` | `fetch_issues` with Priority → `Priority`, Size → story points |
| `query` → `projectV2.id` | resolve project node id |
| `query($id)` → `fields` | find the `Status` single-select field and its option ids |
| `query($id)` → `items.content` | map issue number → project item id |
| `mutation updateProjectV2ItemFieldValue` | `move_issue` — drive the Status column |
| *(a probe query)* | `init` — verifies the token carries the `project` scope before you hit it mid-run |

> [!WARNING]
> **This is the #1 setup failure.** Projects v2 needs the `project` scope *in addition to* `repo`. A `repo`-only token passes every REST call and then fails here. `_graphql()` detects `FORBIDDEN` / "not accessible" and raises a message naming the missing scope, rather than surfacing a raw GraphQL error. `init` checks it up front.

### 4.3 Supabase / Postgres — the mesh

Via `supabase-py`, forced to **HTTP/1.1** (`httpx.HTTPTransport()`) because HTTP/2 stream resets were breaking calls.

**Tables** (`mesh/schema.sql`, every row scoped by `project`):

```sql
events(id, project, dev, module, event_type, payload jsonb, ts)
  idx (project, module, ts desc) · (project, event_type, ts desc)

sessions(project, dev, branch, kind, state, last_seen, started_at, finished_at, payload)
  pk (project, dev, branch, kind) · idx (project, last_seen desc) · (state, last_seen desc)

devs(project, name, role, last_seen)   pk (project, name)
```

| Method | Operation |
|:--|:--|
| `emit()` | `insert` into `events`; session events also `upsert` `sessions` |
| `who_is_touching(module)` | `events` where project+module, newest 20 |
| `recent_decisions(limit)` | `events` where `event_type='decision'` |
| `active_sessions(within_seconds=60)` | `sessions` filtered on `last_seen` freshness |
| `session_history(limit)` | `sessions` newest first |
| `register_dev` / `team_roster` | `upsert` / `select` on `devs` |
| `healthy()` | trivial `select` — lets the CLI report honestly |

> **Every read returns `[]` and every write returns `None` on failure**, recording `last_error`. The mesh is observability; it must never break the loop.

### 4.4 Brain — OpenAI-compatible

| Provider | Base URL |
|:--|:--|
| `siliconflow` *(default)* | `https://api.siliconflow.com/v1` |
| `openrouter` | `https://openrouter.ai/api/v1` |

One call: `POST /chat/completions` via `AsyncOpenAI`. 20s timeout, 1 retry, circuit-breaks after 2 consecutive failures. Override the endpoint with `DEVORCH_BRAIN_BASE_URL`.

> [!IMPORTANT]
> **Model ids are provider-specific.** SiliconFlow serves `deepseek-ai/DeepSeek-V4-Flash`; OpenRouter spells the same model `deepseek/deepseek-v4-flash`. Crossing them returns `400 "Model does not exist"` and `complete()` degrades **silently** to a local fallback. That exact bug meant the brain never once produced real output until it was caught — the default was `Nanbeige/Nanbeige2-16B-Chat`, which SiliconFlow doesn't serve at all. `tests/test_brain.py` now pins the default to its provider's namespace.

### 4.5 Notifications

`POST` to the URL in `notify.webhook_env`. Two payload shapes behind one `Notifier`:

| Type | Body |
|:--|:--|
| `mattermost` | `{"text": message}` |
| `teams` | Adaptive Card — `{"type": "message", "attachments": [... AdaptiveCard with a TextBlock]}` |

An unset webhook `warn()`s and skips rather than raising.

### 4.6 MCP server — our only inbound surface

```bash
python -m devorchestrator.mcp [--transport stdio|http|streamable-http|sse] [--host] [--port]
```

`stdio` by default so Claude Code's `.mcp.json` works untouched. Tools: `who_is_touching` · `active_sessions` · `recent_decisions` · `log_decision` · `log_session_event`.

---

## 5 · Local state — `.orchestrator/{branch}/`

| File | Written by | Read by |
|:--|:--|:--|
| `artifact.md` | research session | impl session, `pr`, review gate |
| `context.json` | `save_pipeline_context()` at end of `start` | `pr`, next process |
| `{kind}-prompt.txt` | prompt builders | the agent |
| `{kind}.log` | tee'd pane output | autofix, review, rate-limit detection |
| `{kind}.exit` | `echo $? >` sentinel | completion detection |
| `.do-branch` | `work_dir()` | maps a directory back to its branch |

> Completion is detected by **exit-code sentinel file**, not tmux introspection — version-agnostic across libtmux releases and identical headless.

---

## 6 · Degradation matrix

Everything optional fails soft. This is a design rule, not an accident.

| Missing | Behaviour |
|:--|:--|
| mesh config | loop runs, no events |
| mesh unreachable | writes dropped and counted, session continues |
| brain key / wrong model | mechanical PR description that **says it's a fallback** |
| notify webhook | logged and skipped |
| tmux / libtmux | headless subprocess with tee'd logs |
| board unreachable mid-run | Status move fails loudly but never discards finished work |
| adapter module absent | `LanePending` naming the exact file |

---

## 7 · Known gaps (backend-relevant)

- **No HTTP API of our own.** If a web frontend needs more than the Streamlit panel, it currently imports the package directly — `frontend/app.py` calls `load_config()` and constructs a `SupabaseMesh` in-process. Its "virtual terminal" panel is a **scripted CSS preview**, not a live session; the config and mesh readouts around it are real.
- **`version_check.py` is defined but never called.** `check_python_version((3, 12))` exists and is unit-tested, but nothing in `cli.py` or the demo script invokes it — so the guard it was written for (issue #30) isn't actually guarding anything yet.
- **`agy` / non-Claude agents** — `Agent` enum exists, only `claude` is implemented.
- **Rate limits** — retry with backoff exists (`RateLimited`); account rotation does not.
- **PR bodies are written from commit subject lines, not the diff**, so the brain invents specifics. Fix belongs in `pr_description.py`.

Full list: [GAPS.md](GAPS.md).

---

## 8 · Where to look

| I want to… | File |
|:--|:--|
| add a shared type | `contracts.py` — **frozen**, spine owner only |
| change the loop | `pipeline.py` |
| add a CLI command | `cli.py` |
| support a new board/git backend | `integrations/` — note `registry.py` is a ready seam that `build_pipeline` does **not** call yet; it constructs adapters directly |
| change what runs as a gate | `checks/runner.py` |
| add a mesh event or query | `mesh/store.py` + `mesh/schema.sql` |
| change agent spawning | `sessions/tmux_runner.py` |
| change what the agent is told | `prompts/*.md` |
