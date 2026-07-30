# Lane D — Mesh + Gates: Implementation Guide

**Owner:** tharun (ConTresillo) · **Issues:** #11, #12, #13, #14

Your code is the **quality & memory layer** of the AI-native SDLC loop. Without it: broken code reaches PRs (no gates), nothing is remembered (no mesh), and the demo's "observability" story doesn't exist.

---

## File ownership (from TEAM-WORKFLOW.md)

```
src/devorchestrator/
├── checks/
│   ├── __init__.py      ← create
│   ├── runner.py        ← #11 — quality gate runner
│   └── autofix.py       ← #12 — self-heal on check failure
├── mesh/
│   ├── __init__.py      ← create
│   ├── store.py         ← #13 — SQLite context mesh
│   └── dashboard.py     ← #14 — Rich team dashboard
├── notify.py            ← #14 — Mattermost/Teams notifier
└── pr_description.py    ← #13 — AI-generated PR descriptions
```

You **never** touch: `cli.py`, `config.py`, `contracts.py`, `pipeline.py`, `review.py`, `integrations/`, `sessions/`, `prompts/` — those belong to other lanes.

---

## What each issue builds

### #11 — Quality gate runner (`runner.py`)

| Aspect | Detail |
|--------|--------|
| **What** | Runs `ruff check .` → `pytest` as subprocesses after implementation |
| **Returns** | `list[CheckResult]` per tool (passed/failed, output, duration) |
| **Stop rule** | First failure stops execution; `--all-checks` flag runs everything |
| **Contracts** | `CheckResult`, `CheckStatus`, `CheckRunner` protocol — all exist in `contracts.py` |
| **Deps** | None — pure `subprocess.run()` + Rich output |
| **Verification** | $ ruff check src/ tests/ → $ pytest tests/ |

### #12 — `--autofix` (`autofix.py`)

| Aspect | Detail |
|--------|--------|
| **What** | On check failure: builds fix prompt → re-invokes AI impl session (max 2 retries) |
| **Terminal** | Narrates: "checks failed → fixing → re-running" |
| **Deps** | #11 (check runner) + Lane C's `sessions/impl.py` (#19) |
| **Stub tip** | If Lane C's impl spawner isn't ready, stub the re-invoke with a log message |

### #13 — SQLite context mesh + PR desc (`store.py`, `pr_description.py`)

| Aspect | Detail |
|--------|--------|
| **Mesh schema** | `SQLite (WAL)` — tables `events(id, dev, module, event_type, payload JSON, ts)` + `devs(name, role, last_seen)` |
| **Writer** | `mesh.emit(event_type, module, payload)` called at key pipeline moments |
| **Readers** | `who_is_touching(module)`, `recent_decisions()`, `team_status()` |
| **PR desc** | `pr_description.py` — reads `git log origin/dev..HEAD` + artifact → calls `brain.complete()` → structured PR description |
| **Contracts** | `Mesh` protocol, `DevActivity`, `Decision`, `Artifact`, `PipelineContext` — all exist |
| **Brain dep** | `openai>=1.30` (optional dep; install with `uv sync --group brain`) |

### #14 — Mesh dashboard + notify (`dashboard.py`, `notify.py`)

| Aspect | Detail |
|--------|--------|
| **Dashboard** | `devorchestrator mesh` → Rich table: dev \| module \| branch \| event_type \| started |
| **Conflicts** | Highlight modules with 2+ active devs in yellow |
| **Escalation** | Show AI→AI resolved (autofix) vs escalated-to-human (review gate) counts |
| **Notifier** | `notify.py` — Mattermost/Teams webhook via `httpx`, implementing `Notifier` protocol |
| **Deps** | #13 (mesh store must exist to query) |

---

## Build order (by dependency)

```
#11 ──────→ #12        (runner → autofix)
   (independent)
#13 ──────→ #14        (store → dashboard)
```

**Recommended order:** #11 → #13 → #12 → #14

- #11 and #13 are **parallelizable** — no shared files, no deps on each other
- #12 needs #11's check output + Lane C's impl spawner (may take time → stub it)
- #14 needs #13's mesh store complete

---

## How it fits the demo

> *"An issue becomes a reviewed, merged PR with zero human coding — four AI companions do the work, and every decision is observable in the mesh."*

Your components are the **"every decision is observable"** part:

1. Lane B picks a task & creates a branch
2. Lane C researches & implements (you watch in tmux)
3. **Your #11** checks the result (`ruff` → `pytest`)
4. **Your #12** auto-fixes if broken (AI→AI escalation, no human needed)
5. **Your #13** records everything in the mesh + writes PR description
6. **Your #14** renders the team dashboard with the full trail

---

## Where to start

### #11 — implementation checklist

- [ ] Create `src/devorchestrator/checks/__init__.py`
- [ ] Create `src/devorchestrator/checks/runner.py`
  - Run `ruff check .` via `subprocess.run()`
  - If passed → run `pytest` via `subprocess.run()`
  - Parse stdout/stderr + exit code → `CheckResult`
- [ ] Add Rich panel: tool | ✅/❌ | duration | summary
  - On failure: "see full log at `.orchestrator/{branch}/checks.log`"
- [ ] Wire `pr` command in `cli.py` to invoke runner
- [ ] Run `ruff check src/ tests/` and `pytest tests/` to verify

### #13 — implementation checklist

- [ ] Create `src/devorchestrator/mesh/__init__.py`
- [ ] Create `src/devorchestrator/mesh/store.py`
  - SQLite WAL mode, `events` table + `devs` table
  - `emit(event_type, module, payload)` — INSERT
  - `who_is_touching(module) → list[DevActivity]`
  - `recent_decisions(limit=10) → list[Decision]`
  - `team_status() → list[DevStatus]`
- [ ] Create `src/devorchestrator/pr_description.py`
  - Read git log: `git log origin/dev..HEAD --oneline`
  - Read artifact: `.orchestrator/{branch}/artifact.md`
  - Call DeepSeek: `brain.complete(prompt)` → structured description
  - Save to `.orchestrator/{branch}/pr-description.md`
- [ ] Wire `decision` command in `cli.py` to call `mesh.emit()`
- [ ] Install `openai>=1.30` (`uv sync --group brain`)
