# Lane D — Mesh + Gates: Design Decision Log

## Session: Initial Lane D Implementation (Issues #11–#14)

### Decision 1: Supabase over SQLite
- **Context**: Original design (`docs/lane-d-mesh-gates-guide.md`) specified SQLite WAL for the mesh store.
- **Change**: Switched to Supabase/Postgres as the mesh backend.
- **Impact**: `MeshConfig` fields changed from `db_path` to `supabase_url` + `supabase_key_env`; `mesh/store.py` uses `supabase.Client` instead of `sqlite3`; all existing SQLite references removed from config and template.
- **Why**: User explicitly stated "I'm using supabase not sqlite".

### Decision 2: Protocol-based adapter pattern
- **Context**: `contracts.py` defines `CheckRunner`, `Mesh`, `Notifier` as `typing.Protocol`.
- **Implementation**: All concrete classes (`SubprocessCheckRunner`, `SupabaseMesh`, `HttpxNotifier`) satisfy these protocols structurally via `isinstance` checks with `@runtime_checkable`.
- **Why**: Lane boundaries are enforced at the type level — lanes never import each other's internals.

### Decision 3: Subprocess runner with injectable callable
- **Design**: `SubprocessCheckRunner.__init__` accepts `runner: Callable` that defaults to `subprocess.run`, enabling mock injection in tests.
- **Why**: Unit tests verify pass/fail/not-found paths without actually running ruff/pytest.

### Decision 4: Stop-on-first-failure with `--all-checks` override
- **Behavior**: Default mode runs checks sequentially; first failure halts. `--all-checks` flag runs everything regardless.
- **Why**: Fast feedback in the common case (fix one thing at a time), with opt-in full suite available.

### Decision 5: Autofix retry with stub re-invoke
- **Design**: `autofix()` runs checks → retries up to 2× on failure. The "fix" action is currently a log message; the comment `# TODO: swap with Lane C's impl spawner (#19)` marks where to hot-swap.
- **Why**: Architecture supports integration before Lane C's `sessions/impl.py` exists. The fix callback will be injected once that lane lands.

### Decision 6: Mock templates for integration testing
- **File**: `tests/mocks.py` — reusable fake implementations for subprocess, Supabase, httpx, and git.
- **Why**: All integration tests use these instead of real services, making tests fast, deterministic, and network-independent.

### Decision 7: CLI live wiring
- **Changed**: `pr`, `mesh`, `decision` CLI commands from `_stub()` to live implementations that wire up runner/autofix/mesh/dashboard.
- **Why**: End-to-end command flow works immediately on any dev machine with the dependencies installed.

---

## Files created/modified this session

| File | Action | Lane |
|------|--------|------|
| `AGENTS.md` | Updated | spine |
| `.gitignore` | Added `AGENTS.md` | spine |
| `pyproject.toml` | Added `supabase>=2.0` | spine |
| `devOrchestrator.yaml.template` | Updated mesh schema | spine |
| `src/devorchestrator/config.py` | `MeshConfig`: `db_path` → `supabase_url`+`supabase_key_env` | spine |
| `src/devorchestrator/cli.py` | Wired `pr`, `mesh`, `decision` commands | spine |
| `src/devorchestrator/checks/__init__.py` | Created | #11 |
| `src/devorchestrator/checks/runner.py` | Created — SubprocessCheckRunner | #11 |
| `src/devorchestrator/checks/autofix.py` | Created — retry loop | #12 |
| `src/devorchestrator/mesh/__init__.py` | Created | #13 |
| `src/devorchestrator/mesh/store.py` | Created — SupabaseMesh | #13 |
| `src/devorchestrator/mesh/dashboard.py` | Created — Rich table renderer | #14 |
| `src/devorchestrator/pr_description.py` | Created — git log + artifact + PR body | #13 |
| `src/devorchestrator/notify.py` | Created — HttpxNotifier | #14 |
| `tests/__init__.py` | Created (needed for `from tests.mocks import ...`) | test |
| `tests/mocks.py` | Created — mock factories | test |
| `tests/test_checks_runner.py` | Created — 7 tests | #11 |
| `tests/test_autofix.py` | Created — 3 tests | #12 |
| `tests/test_mesh_store.py` | Created — 6 tests | #13 |
| `tests/test_pr_description.py` | Created — 4 tests | #13 |
| `tests/test_dashboard.py` | Created — 2 tests | #14 |
| `tests/test_notify.py` | Created — 3 tests | #14 |
| `tests/test_config.py` | Updated mesh config test | test |
| `C:\Users\tharo\.claude\CLAUDE.md` | Updated global config | infra |

---

## What's done (✓)

- **#11** — SubprocessCheckRunner: ruff → pytest, `--all-checks` flag, Rich output, protocol-satisfying
- **#12** — autofix: retry loop (max 2), stub re-invoke (ready for Lane C hookup)
- **#13** — SupabaseMesh (emit, who_is_touching, recent_decisions), PR description generator (git log + artifact)
- **#14** — Rich dashboard, HttpxNotifier (Mattermost/Teams webhooks)
- **CLI** — `pr`, `mesh`, `decision` commands wired live
- **Tests** — 41/41 passing, ruff clean
- **Mocks** — reusable mock templates for subprocess, Supabase, httpx, git

## What remains (⬜)

- **Lane C integration** — Replace `autofix` stub with real `impl.spawn(prompt)` from `sessions/impl.py` (#19)
- **Brain integration** — `pr_description.py` currently generates a template; swap with `brain.complete(prompt)` once `openai` client is configured
- **notify.py webhook_url** — Currently reads from env var; the config's `NotifyConfig.webhook_env` is not yet plumbed through `cli.py`
- **Supabase migrations** — The `events` and `devs` table schemas need a migration script for new Supabase projects
- **Distinct module discovery** — `mesh/dashboard.py` uses a hard-coded module list; should query `SELECT DISTINCT module FROM events`
- **Type checking** — `pyproject.toml` has no `[tool.pyright]` or `py.typed`; add once the repo adopts a type checker

---

## Session: P0 — Interoperability wiring + merge to `dev`

### Decision 1: NotifyConfig.build_notifier() factory
- **Context**: `HttpxNotifier` constructor takes `webhook_env: str` and reads the env var internally. The config has `NotifyConfig.webhook_env` but no caller used it to construct a notifier.
- **Implementation**: Added `NotifyConfig.build_notifier() -> HttpxNotifier | None` that reads the env var name from config and returns a configured notifier (or `None` if the env var is unset). Wired into `cli.py`'s `pr` command — team gets a webhook notification on check pass/fail.
- **Why**: Keeps the env-var-name pattern consistent with the rest of the config layer; the pipeline always constructs services from config, never by hand.

### Decision 2: Conflict detector — lightweight, non-blocking
- **Context**: Sprint 3 calls for a conflict detector (#39) that warns when two devs touch the same module. The mesh already has `who_is_touching()`.
- **Implementation**: `mesh/conflict.py` — pure function `warn_on_overlap(mesh, modules, limit) -> list[str]`. Purely advisory (returns warning strings, caller decides). Deduplicates multiple events from the same (dev, module) pair. Wired into `devorchestrator mesh --check <modules>` and auto-triggered after `devorchestrator decision`.
- **Why**: Lightweight and non-blocking matches the sprint spec ("Not a block — prints warning, asks Continue?"). No new DB queries needed beyond what `who_is_touching()` already issues. The `--check` flag makes it usable from any context.
- **Tests**: 5 tests covering empty, single, multi-module, dedup, and limit behavior.

### Decision 3: Merge strategy — fast-forward from feature/mesh-gates into dev
- **Context**: `feature/mesh-gates` has 3 commits ahead of `dev` with no diverging history (dev has 0 commits that the feature branch doesn't). All Lane D code is additive (new files + config schema changes).
- **Implementation**: `git checkout dev && git merge feature/mesh-gates` — clean fast-forward. No merge commit, no conflict resolution needed.
- **Why**: Fast-forward keeps the linear history clean. The schema change (`MeshConfig`: `db_path` → `supabase_url` + `supabase_key_env`) is backward-incompatible, but `dev` never had those fields in production — the only `devOrchestrator.yaml` lives on `feature/mesh-gates`.

## Files created/modified this session

| File | Action | Decision |
|------|--------|----------|
| `src/devorchestrator/config.py` | Added `build_notifier()`, `TYPE_CHECKING` import | #1 |
| `src/devorchestrator/cli.py` | Wired notifier in `pr` command, `--check` on `mesh`, conflict warn in `decision` | #1, #2 |
| `src/devorchestrator/mesh/conflict.py` | Created — `warn_on_overlap()` | #2 |
| `tests/test_conflict.py` | Created — 5 tests | #2 |
| `tests/test_config.py` | Added 2 notifier factory tests | #1 |
| `docs/DECISIONS.md` | Updated this session | #3 |
