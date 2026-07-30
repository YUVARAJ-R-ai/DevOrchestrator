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
