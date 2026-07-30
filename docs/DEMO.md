# Demo Runbook — 18h Hackathon

**The one-line pitch:**
> An issue becomes a reviewed, merged PR with zero human coding — four AI companions do the work, and every decision is observable in the mesh.

---

## Why this doc exists

`pipeline.build_pipeline()` and `review.build_review()` were unconditional `LanePending` stubs through issue #7 — `devorchestrator start`/`pr`/`review` couldn't run at all. That Wave-3 wiring is now done (merged into `dev`): the real CLI commands work end-to-end. **Use the real commands below** (`devorchestrator start` etc.) for the actual demo. `scripts/demo.sh` is kept as a documented equivalent/fallback — it constructs the same `Pipeline`/`ReviewGate` by hand and is useful if you want the whole loop scripted in one non-interactive shot instead of three separate commands.

---

## Before you run it (one-time setup)

1. **Config**: `cp devOrchestrator.yaml.template devOrchestrator.yaml` and fill in your name + repo URL. `board.project_number` should point at project **#10**.
2. **Env vars** (`.env` or exported):
   - `GITHUB_TOKEN` — PAT with `repo` scope (issues, contents, pulls)
   - `SUPABASE_SERVICE_KEY` — optional; without it the demo runs with the mesh disabled (task→PR loop still works, no conflict detection / decision log)
   - `OPENROUTER_API_KEY`, `MATTERMOST_WEBHOOK` — required by config validation even if not central to the demo; any placeholder value satisfies the check
3. **Tools on PATH**: `tmux`, `claude` (logged in — `claude auth login`), `uv`
4. **The seeded demo issue** — **#30** ("demo: add a Python version guard helper") is already on the board (Backlog). It's deliberately small and isolated (new files only, touches no lane-owned file) so a live AI run has good odds of finishing cleanly on stage. Re-open it before each rehearsal if a prior run closed/merged it.

---

## Running it

**Real CLI (recommended — this is what's actually being demoed):**
```bash
devorchestrator start          # pick #30, watch research + impl run live in tmux
# ... review the code the AI wrote ...
devorchestrator pr              # checks (autofix on failure) -> opens the real PR
devorchestrator review          # TL gate: diff | checks | artifact -> [a]/[r]/[q]
```

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
| **GitHub API flaky / branch already exists** | Re-run `./scripts/demo.sh` — `GithubGit.create_branch` will fail loudly on a name collision; delete the stale branch (`git push origin --delete feature/issue-30-...`) and retry. |
| **tmux not available on the demo machine** | Construct the sessions with `headless=True` instead (edit `scripts/demo.sh`'s `ClaudeSession(..., headless=True)`) — loses the live-pane visual but the loop still runs; narrate it verbally instead. |
| **Nothing works at all** | Fall back to walking through the architecture diagrams (`docs/architecture-high-level.drawio`) and the merged code on GitHub — the story ("multi-agent, mesh-coordinated, human-gated SDLC loop") stands even as a code walkthrough. |

---

## After the PR is merged

Move the demo issue back to Backlog and reopen it (`gh issue reopen 30`) so the next rehearsal has a clean seed. Do **not** merge dry-run PRs into `main` — merge them into a disposable branch or just leave them open/close without merging if this was only a rehearsal, not the live judged run.
