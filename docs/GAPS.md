# Known Gaps — DevOrchestrator (as of 2026-07-30, post-Wave-3 + Spine follow-up)

This is an honest inventory of everything that's **not** finished, discovered while verifying the system end-to-end for the hackathon demo. None of these block the demo (the critical one — Wave-3 wiring never existing — is already fixed, see below), but all of them are real and worth knowing before anyone extends this beyond the hackathon.

Severity key: 🔴 would break a real run · 🟡 works but is a known limitation · 🟢 cosmetic / minor

---

## Fixed during this session (for context — no longer gaps)

- 🔴 **`pipeline.build_pipeline()` / `review.build_review()` were unconditional `LanePending` stubs** on every branch, despite issue #3 being closed. `devorchestrator start`/`pr`/`review` could not run at all. **Fixed** (Wave-3 wiring implemented, PR #33).
- 🔴 **`devorchestrator pr` never actually called `git.open_pr()`** — it only ran checks and saved the PR description to a local file. **Fixed** as part of the same wiring.
- 🔴 **Nothing anywhere committed or pushed code, or checked out the created branch locally.** `GithubGit.create_branch()` only creates an empty ref via the GitHub API; the research/impl sessions would have edited files on whatever branch was checked out beforehand, uncommitted, and `open_pr()` would have opened a PR with zero commits. **Fixed** (`Pipeline._checkout_local` / `_commit_and_push`, PR #36).
- 🟡 **A single bad import (`from conftest import ...` instead of `from tests.conftest import ...`) in `test_lane_c_pipeline.py` aborted collection of the entire test suite** — `test_pipeline.py`/`test_review.py` were wrongly assumed broken by the same cause in earlier PRs. **Fixed.**
- 🟡 **`build_pipeline`/`build_review` would misconstruct a `GithubBoard`/`GithubGit` for a non-GitHub config** (e.g. `board.type: plane`), since they unconditionally imported the GitHub adapters regardless of configured type — would have thrown a confusing `ValueError` from URL parsing instead of a clear "not implemented" message. **Fixed** with an explicit type guard.
- 🔴 **`devorchestrator init` never scaffolded anything or tested a real connection** — it just validated a config that had to already exist, despite the README promising "tests all connections, registers in the mesh, done." Confirmed by hand: a fresh checkout with no `devOrchestrator.yaml` failed immediately with "no devOrchestrator.yaml found," and even a valid config never made a single test request to the board/git API. **Fixed**: `init` now interactively scaffolds `devOrchestrator.yaml` (prompting for name/repo URL/project number/mesh) and `.env` (prompting only for whatever token/webhook vars the config actually references, skipping ones already set) if they don't exist, then makes a real `GET /user` + `GET /repos/{owner}/{repo}` call to confirm the GitHub token is valid and can see the configured repo — not just that the field is non-empty.

### Fixed in the follow-up Spine pass (Lane A)

- 🔴 **Three regressions from merge commit `7ebf5e2` ("Merge branch 'main' into dev"), which resolved four files by taking the older side.** All three shipped to `main` via PR #41 before being spotted:
  - `cli.py` lost `CONFIG_FILENAME` from its import while keeping two call sites — **`devorchestrator init` died with `NameError` before printing anything**, and `ruff` failed with 2× F821. The first command a new user runs.
  - `build_pipeline` lost `local_git=True` — no local checkout, no commit, no push, so `open_pr()` opened a PR identical to base. Exactly the bug PR #36 had just fixed.
  - The brain wiring lost `openai` from core deps and `config=` at both `generate_pr_description` call sites — the brain silently never ran, always degrading to the mechanical description with no error to notice.
  **Fixed**, each with a regression test (`test_build_pipeline_enables_local_git`, `test_describe_pr_forwards_config_to_the_brain`) — none of the three had any assertion covering it, which is why a merge could drop them silently.
- 🔴 **`devorchestrator pr`'s `--autofix` did nothing.** It called `checks/autofix.py`, which prints "fixing <tool> failure..." and "→ re-invoke impl session" and then just re-runs the same checks — its own TODO admits the re-invoke was never implemented. So autofix looked like it worked, consumed its retry budget, and changed no code. **Fixed**: `pr` now runs through `Pipeline.prepare_pr`, whose loop actually re-invokes the implementation session with `prompts/autofix.md`.
- 🟡 **`pipeline.py` carried a duplicate prompt set and module parser** predating Lane C's `sessions/`. Not just redundancy: `pipeline._parse_modules` returned full paths (`src/devorchestrator/widget.py`) while `ParsedArtifact.touched_modules` returns top-level modules (`devorchestrator`), and both fed the same `module` key that `mesh.who_is_touching()` keys conflict detection on — so overlap detection compared two different granularities depending on the code path. **Fixed**: the duplicates are deleted; `prompts/` + `sessions/artifact.py` are canonical.
- 🟡 **No persisted `PipelineContext` between `start` and `pr`**, so `pr` reconstructed an approximate issue title from the branch slug by regex. **Fixed**: `start()` writes `.orchestrator/{branch}/context.json`; `pr` loads it and uses the real issue title. The artifact is deliberately re-read from `artifact.md` rather than stored, so an artifact edited between the two commands is the one used.
- 🟡 **`move_issue` was implemented and tested but never called** — the board's Status column never moved on its own. **Fixed**: `in_progress` once the branch exists, `in_review` once the PR is open. Failures are reported and swallowed; an unreachable board must not discard a finished implementation.
- 🟡 **`test_lane_c_pipeline.py`'s fake-agent fixture keyed off `"implement every sub-task"`** — wording from `pipeline.py`'s inline prompt, not from `prompts/impl.md` — so it silently stopped ticking checkboxes the moment the real template was used. **Fixed** to key off `"implementation session"`.

---

## Open gaps

### 🔴 Mesh has no per-project/tenant isolation
`mesh/store.py`'s `events` table is a single flat table (`dev, module, event_type, payload, ts`) with **no project/repo/tenant column**. If two different projects point their `mesh.supabase_url` at the same Supabase instance, their events mix in the same table — `who_is_touching("some/path.py")` would return activity from *both* projects if they share a module path. Today, every team/pod needs its **own separate Supabase project**, not just its own config file, to keep mesh data isolated.

### 🟡 `devs` table exists in `schema.sql` but is never written to
`SupabaseMesh` (`mesh/store.py`) has no method that writes to the `devs` table — `devorchestrator init`'s "register in mesh" only inserts a `dev_joined` row into `events`. The `devs` table is dead schema right now; the dev roster shown anywhere would need to be derived from distinct `dev` values in `events`, not a real roster table.

### 🟡 Account rotation / rate-limit handling doesn't exist
If the `claude` CLI hits a rate limit mid-session, there's no automatic account rotation or retry-with-backoff (this was always Sprint-4/post-MVP scope, never built). A rate limit mid-demo means the session fails; the only mitigation is `docs/DEMO.md`'s fallback plan (pre-recorded backup video).

### 🟡 SiliconFlow brain path is wired but unverified against a live endpoint
The brain (`sessions/brain.py`) was fully built but **never actually called anywhere** — `pr_description.py` produced a purely mechanical description and `openai` wasn't even installed. **Fixed**: `openai` is now a core dep, `generate_pr_description` routes through the brain (SiliconFlow/DeepSeek) with the mechanical description as a hard fallback, and `devorchestrator init` prints the brain status. Config now defaults to `provider: siliconflow`, `model: deepseek-ai/DeepSeek-V3`, `token_env: SILICONFLOW_API_KEY`. **Still unverified**: nobody has run it against a live SiliconFlow key + confirmed the exact model id ("DeepSeek V4 Flash" vs `DeepSeek-V3`) during this session — a wrong model id or missing key degrades to the mechanical description (by design, never breaks), but "DeepSeek actually wrote this PR body" is not yet proven end-to-end.

### 🟢 `GITHUB_TOKEN` needs two scopes, easy to get wrong
A classic PAT needs both `repo` **and** `project` scopes (the latter for Projects v2 GraphQL — reading Priority/Size fields via `board.project_number`). A token with only `repo` scope will fail the moment `GithubBoard._fetch_via_project()` runs a GraphQL query, with an unhelpful GitHub API error rather than a clear "missing project scope" message.

### 🟢 `devOrchestrator.yaml` in the repo root is stale (plane/gitea, not github)
This is tharun's personal config, committed to the repo, still targeting the pre-pivot Plane/Gitea stack. Anyone running `devorchestrator` commands from this repo without first editing this file will hit the new type-guard's `LanePending("board", ...)`. Not a code bug — just a config file nobody updated after the GitHub pivot. See `docs/DEMO.md` for the exact fix.

### 🟢 `git add -A` in the new commit-and-push step is broad
`Pipeline._commit_and_push` stages everything with `git add -A`, matching how a human would commit after reviewing, but it means any *other* uncommitted change sitting in the working tree at the time (not just the AI's edits) rides along in the same commit. Documented as a "clean your working tree first" caveat in `DEMO.md`; not fixed with more selective staging since the pipeline has no way to know which files are "its own" versus pre-existing edits.

### 🟢 Two adapters have a design mismatch nobody's resolved: SQLite (in early docs) vs. Supabase (what's actually built)
`docs/research.md`/`docs/vision.md`/the original product backlog all describe the mesh as SQLite (WAL mode), a deliberate zero-infra choice. Lane D actually built it against Supabase/Postgres instead (a real, reasonable pivot — hosted, queryable, no per-dev file to sync) but the earlier vision docs were never updated to reflect this. Purely a documentation-lag issue, not a functional one.

---

## What's genuinely solid (for balance)

- The core loop (`Pipeline.start()` → `prepare_pr()`, `ReviewGate`) has real test coverage: 162 tests passing, including a real-tmux integration test (skipped only when tmux isn't installed) and a real end-to-end run against a stand-in agent binary.
- Every adapter (`GithubBoard`, `GithubGit`, `SupabaseMesh`, `SubprocessCheckRunner`, `ClaudeSession`) is independently unit-tested with mocked transports, not just exercised through the pipeline.
- The autofix retry loop, conflict detection, and PR-description generation are all real, tested code paths — not stubs. (This was previously claimed while `devorchestrator pr` still ran the `checks/autofix.py` stub instead; it is true now that `pr` goes through `Pipeline.prepare_pr`. `checks/autofix.py` itself is still a no-op and is no longer on any live path — it should be deleted or given a real re-invoke callback.)
- Config validation fails loud with actionable hints (missing env vars, mismatched board/git track) rather than failing silently mid-run.
