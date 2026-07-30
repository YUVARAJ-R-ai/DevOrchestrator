# Demo Runbook — 18h Hackathon

**The one-line pitch:**
> An issue becomes a reviewed, merged PR with zero human coding — four AI companions do the work, and every decision is observable in the mesh.

---

## Why this doc exists

`pipeline.build_pipeline()` and `review.build_review()` were unconditional `LanePending` stubs through issue #7 — `devorchestrator start`/`pr`/`review` couldn't run at all. That Wave-3 wiring is now done (merged into `dev`): the real CLI commands work end-to-end. **Use the real commands below** (`devorchestrator start` etc.) for the actual demo. `scripts/demo.sh` is kept as a documented equivalent/fallback — it constructs the same `Pipeline`/`ReviewGate` by hand and is useful if you want the whole loop scripted in one non-interactive shot instead of three separate commands.

---

## Before you run it (one-time setup)

**Run everything from the root of this repo** (`devOrchestrator` itself — the demo issue lives here, the tool orchestrates its own repo for this demo).

1. **Config — `devOrchestrator.yaml` must say `type: github`.** The committed file in the repo root currently has `board.type: plane` / `git.type: gitea` (a teammate's leftover from before the GitHub pivot). If you run commands without fixing this, the pipeline will immediately refuse with "only board.type=github is implemented." Edit `devOrchestrator.yaml` in place to:
   ```yaml
   name: <your name>
   role: dev
   agent: claude

   board:
     type: github
     url: https://github.com/YUVARAJ-R-ai/DevOrchestrator
     token_env: GITHUB_TOKEN
     project_number: 10

   git:
     type: github
     url: https://github.com/YUVARAJ-R-ai/DevOrchestrator
     token_env: GITHUB_TOKEN

   brain:
     provider: openrouter
     model: deepseek/deepseek-v4-flash
     token_env: OPENROUTER_API_KEY

   notify:
     type: mattermost
     webhook_env: MATTERMOST_WEBHOOK

   mesh:
     supabase_url: https://<project>.supabase.co    # or leave blank to skip mesh
     supabase_key_env: SUPABASE_SERVICE_KEY
   ```
   (You don't need to commit this change — it's fine to just edit it locally for the recording.)

2. **`.env` file, same directory as `devOrchestrator.yaml`** (the repo root):
   ```bash
   GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
   SUPABASE_SERVICE_KEY=eyJ...              # optional — omit to run without the mesh
   OPENROUTER_API_KEY=sk-or-anything         # required by config validation even if unused; any non-empty value passes
   MATTERMOST_WEBHOOK=https://example.com/placeholder   # same — any non-empty value passes
   ```
   **`GITHUB_TOKEN` scopes**: a classic PAT needs both **`repo`** (issues, contents, pull requests) and **`project`** (Projects v2 read/write — needed because `board.project_number: 10` reads Priority/Size fields via GraphQL). Create one at github.com/settings/tokens.

3. **Tools on PATH**: `tmux`, `claude` (logged in — `claude auth login`), `uv`.
4. **The seeded demo issue** — **#30** ("demo: add a Python version guard helper") is already on the board (Backlog). It's deliberately small and isolated (new files only, touches no lane-owned file) so a live AI run has good odds of finishing cleanly on stage. Re-open it before each rehearsal if a prior run closed/merged it.
5. **`git status` must be clean before you run `devorchestrator start`.** It commits with `git add -A` after the implementation session — any uncommitted changes already sitting in your working tree (including an edited `devOrchestrator.yaml` from step 1, if you didn't `git stash` it) get swept into that commit too. Either commit/stash your own edits first, or accept that `devOrchestrator.yaml`'s local edit rides along in the demo commit (harmless, but know it'll be there if you inspect the PR diff on camera).

---

## Running it

**Real CLI (recommended — this is what's actually being demoed):**
```bash
devorchestrator start          # pick #30, watch research + impl run live in tmux
# ... review the code the AI wrote ...
devorchestrator pr              # checks (autofix on failure) -> opens the real PR
devorchestrator review          # TL gate: diff | checks | artifact -> [a]/[r]/[q]
```

What `start` actually does to your local checkout (worth narrating on camera — it's a real, visible effect): creates the branch on GitHub, then **automatically fetches and checks it out locally** (`git checkout -B feature/issue-30-...`) before the research/impl sessions run, and **automatically commits + pushes** whatever the implementation session wrote once it finishes. Your terminal prompt's branch indicator will visibly change — that's real, not staged. By the time `start` prints "Review the code, then run `devorchestrator pr`", you're sitting on the new branch with the AI's commit already pushed.

**Scripted equivalent** (one shot, no manual step between implementation and PR):
```bash
./scripts/demo.sh
```

What happens, in order:
1. Pre-flight checks (config, tokens, `tmux`/`claude` present)
2. Fetches your open issues, auto-picks the one with "demo" in the title (#30)
3. Creates the branch, spawns **two live tmux panes** — research (reads the codebase, writes `artifact.md`) then implementation (writes the code)
4. Runs checks (`ruff` + `pytest`); on failure, autofix re-invokes the impl session automatically
5. Opens the PR (description generated from the commit log + artifact)
6. Renders the **TL review gate** — diff, checks, artifact — and waits for `[a]`/`[r]`/`[q]`

**Watch the tmux panes live:** `tmux attach -t do-<branch-name>` in a second terminal — this is the visual centerpiece of the demo.

---

## Full dry-run checklist (do this before judging, not during)

- [ ] Run `./scripts/demo.sh` once, start to finish, on the actual demo machine/network
- [ ] Confirm both tmux panes render and the audience-visible terminal is legible (font size!)
- [ ] Confirm the PR actually opens on GitHub (click through, don't just trust stdout)
- [ ] Practice the `[a]` approve keypress — that's the "human moment" beat
- [ ] Time it — know how long research+impl actually takes so you don't stand there silently
- [ ] Re-open/reset issue #30 after a successful dry-run so it's ready for the live run

---

## Fallback plan (if something breaks on stage)

| Failure | Fallback |
|---|---|
| **SiliconFlow/Nanbeige brain unreachable** | Per issue #9's design, the brain has a **hard fallback** — the loop runs on Claude sessions alone. Nothing to do; it degrades silently. |
| **Supabase mesh unreachable** | `SUPABASE_SERVICE_KEY` unset (or the client errors) → the script prints a warning and runs with `mesh=None`. Task→PR loop still completes; only the mesh dashboard/conflict-detection beat is skipped. Mention it's disabled rather than pretending it ran. |
| **`claude` CLI rate-limited mid-session** | No account rotation yet (Sprint 4 scope, not built). Have a **pre-recorded terminal capture** (`asciinema` or a screen recording) of a successful dry-run as the backup video. |
| **GitHub API flaky / branch already exists (remote)** | Re-run — `GithubGit.create_branch` will fail loudly on a name collision; delete the stale branch (`git push origin --delete feature/issue-30-...`) and retry. |
| **Branch already exists locally from a previous run** | `_checkout_local` uses `git checkout -B`, which force-resets the local branch to match the freshly created remote ref — safe to re-run, it won't get stuck on stale local state. |
| **tmux not available on the demo machine** | Construct the sessions with `headless=True` instead (edit `scripts/demo.sh`'s `ClaudeSession(..., headless=True)`) — loses the live-pane visual but the loop still runs; narrate it verbally instead. |
| **Nothing works at all** | Fall back to walking through the architecture diagrams (`docs/architecture-high-level.drawio`) and the merged code on GitHub — the story ("multi-agent, mesh-coordinated, human-gated SDLC loop") stands even as a code walkthrough. |

---

## After the PR is merged

Move the demo issue back to Backlog and reopen it (`gh issue reopen 30`) so the next rehearsal has a clean seed. Do **not** merge dry-run PRs into `main` — merge them into a disposable branch or just leave them open/close without merging if this was only a rehearsal, not the live judged run.
