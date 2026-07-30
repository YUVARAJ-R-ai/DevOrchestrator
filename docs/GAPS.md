# Known Gaps — DevOrchestrator (as of 2026-07-30, post-Wave-3 wiring)

This is an honest inventory of everything that's **not** finished, discovered while verifying the system end-to-end for the hackathon demo. None of these block the demo (the critical one — Wave-3 wiring never existing — is already fixed, see below), but all of them are real and worth knowing before anyone extends this beyond the hackathon.

Severity key: 🔴 would break a real run · 🟡 works but is a known limitation · 🟢 cosmetic / minor

---

## Fixed during this session (for context — no longer gaps)

- 🔴 **`pipeline.build_pipeline()` / `review.build_review()` were unconditional `LanePending` stubs** on every branch, despite issue #3 being closed. `devorchestrator start`/`pr`/`review` could not run at all. **Fixed** (Wave-3 wiring implemented, PR #33).
- 🔴 **`devorchestrator pr` never actually called `git.open_pr()`** — it only ran checks and saved the PR description to a local file. **Fixed** as part of the same wiring.
- 🔴 **Nothing anywhere committed or pushed code, or checked out the created branch locally.** `GithubGit.create_branch()` only creates an empty ref via the GitHub API; the research/impl sessions would have edited files on whatever branch was checked out beforehand, uncommitted, and `open_pr()` would have opened a PR with zero commits. **Fixed** (`Pipeline._checkout_local` / `_commit_and_push`, PR #36).
- 🟡 **A single bad import (`from conftest import ...` instead of `from tests.conftest import ...`) in `test_lane_c_pipeline.py` aborted collection of the entire test suite** — `test_pipeline.py`/`test_review.py` were wrongly assumed broken by the same cause in earlier PRs. **Fixed.**
- 🟡 **`build_pipeline`/`build_review` would misconstruct a `GithubBoard`/`GithubGit` for a non-GitHub config** (e.g. `board.type: plane`), since they unconditionally imported the GitHub adapters regardless of configured type — would have thrown a confusing `ValueError` from URL parsing instead of a clear "not implemented" message. **Fixed** with an explicit type guard.

---

## Open gaps

### 🔴 Mesh has no per-project/tenant isolation
`mesh/store.py`'s `events` table is a single flat table (`dev, module, event_type, payload, ts`) with **no project/repo/tenant column**. If two different projects point their `mesh.supabase_url` at the same Supabase instance, their events mix in the same table — `who_is_touching("some/path.py")` would return activity from *both* projects if they share a module path. Today, every team/pod needs its **own separate Supabase project**, not just its own config file, to keep mesh data isolated.

### 🟡 `devs` table exists in `schema.sql` but is never written to
`SupabaseMesh` (`mesh/store.py`) has no method that writes to the `devs` table — `devorchestrator init`'s "register in mesh" only inserts a `dev_joined` row into `events`. The `devs` table is dead schema right now; the dev roster shown anywhere would need to be derived from distinct `dev` values in `events`, not a real roster table.

### 🟡 PR title in `devorchestrator pr` is derived from the branch slug, not the real issue title
`cli.py`'s `pr` command reconstructs the issue title from the branch name (`feature/issue-N-slug` → `"issue #N: slug words"`) rather than fetching the actual GitHub issue title. This is because `devorchestrator start` and `devorchestrator pr` run as **separate processes** (by design — the human reviews code in between) and `pr` has no persisted `PipelineContext` to read from. Functional, but the PR title may read slightly differently than the issue title if the branch slug truncated or altered words.

### 🟡 No persisted `PipelineContext` between `start` and `pr`
Related to the above: `Pipeline.prepare_pr()` (the method) expects a full `PipelineContext` (issue, branch, artifact), but `devorchestrator pr` (the CLI command) doesn't have one — it reconstructs only what it needs (branch name, issue ID) from `git rev-parse` and regex. This works for the current flow but means `pr` can't do anything that needs the original `Issue`/`Artifact` objects (e.g., re-checking acceptance criteria against the artifact). A `.orchestrator/{branch}/context.json` persisted at the end of `start` would close this gap.

### 🟡 `move_issue` (board Status column updates) is implemented but never called
`GithubBoard.move_issue()` (moving an issue between Backlog/Ready/In Progress/etc. on the Project board) is fully implemented and tested, but **nothing in `pipeline.py` or `cli.py` ever calls it**. The board's Status column doesn't move automatically as a task progresses through the pipeline — someone still has to update it by hand (as has been done manually throughout this hackathon).

### 🟡 Account rotation / rate-limit handling doesn't exist
If the `claude` CLI hits a rate limit mid-session, there's no automatic account rotation or retry-with-backoff (this was always Sprint-4/post-MVP scope, never built). A rate limit mid-demo means the session fails; the only mitigation is `docs/DEMO.md`'s fallback plan (pre-recorded backup video).

### 🟡 Nanbeige/SiliconFlow brain path is unverified against a real endpoint
Issue #9's brain module has a documented "hard fallback" to Claude-only if SiliconFlow is unreachable, but nobody on this thread has actually exercised the SiliconFlow path against a live endpoint during this session — only the fallback behavior has been discussed/verified in isolation. Treat the SiliconFlow integration as unverified, not proven, for the live demo.

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
- The autofix retry loop, conflict detection, and PR-description generation are all real, tested code paths — not stubs.
- Config validation fails loud with actionable hints (missing env vars, mismatched board/git track) rather than failing silently mid-run.
