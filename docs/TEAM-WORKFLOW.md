# Team Workflow — 18h Hackathon (4 devs, zero conflicts)

**Board:** https://github.com/users/YUVARAJ-R-ai/projects/10 · **Track:** Dev productivity · **Frontend:** terminal (Rich TUI + tmux)

This doc exists so four people can build in parallel for 18 hours **without ever editing the same file**. Read the golden rules, then work only inside your lane.

---

## The 4 lanes (who owns what)

Each lane owns a disjoint set of files. **You touch only your lane's files.** No exceptions after Wave 1.

| Lane | Owner | GitHub | Owns (only these paths) |
|------|-------|--------|--------------------------|
| **A — Spine** | harsha | `Haise-727` | `pyproject.toml`, `cli.py`, `contracts.py`, `config.py`, `pipeline.py`, `review.py`, `devOrchestrator.yaml.template` |
| **B — Integrations** | yuvaraj | `YUVARAJ-R-ai` | `integrations/github_board.py`, `integrations/github_git.py`, `integrations/selector.py`, `scripts/demo.sh`, `docs/DEMO.md` |
| **C — AI sessions** | ragav | `ragavhariharan` | `sessions/tmux_runner.py`, `sessions/research.py`, `sessions/impl.py`, `sessions/brain.py`, `sessions/artifact.py`, `prompts/` |
| **D — Mesh + Gates** | tharun | `ConTresillo` | `checks/runner.py`, `checks/autofix.py`, `mesh/store.py`, `mesh/dashboard.py`, `pr_description.py`, `notify.py` |

All under `src/devorchestrator/`.

---

## Golden rules (the anti-conflict contract)

1. **`contracts.py` is the only shared file, and it is FROZEN after Wave 1.** Lane A writes it in hours 0–3 with everyone on a call. After that, nobody edits it. If you need a new shared type, ask harsha — he makes the change, everyone pulls.
2. **Talk to other lanes through `contracts.py` types only** — never import another lane's internals. You call `board.fetch_issues() -> list[Issue]`, you don't reach into how it works.
3. **One file has one owner.** If you feel the urge to edit a file outside your lane, stop and ping the owner. This is the single rule that prevents merge hell.
4. **Small, frequent commits** with the issue number: `git commit -m "issue #8: tmux research pane spawns"`. Never `git add .` — add specific files (keeps `.env`/`.orchestrator/` out).
5. **Pull `dev` before you start each work block.** `git checkout dev && git pull` then rebase your feature branch.
6. **Integration (Wave 3) is Lane A's call.** When wiring the pipeline, harsha drives; others support their module's glue. Don't independently rewire.

---

## The 18-hour timeline (waves = milestones)

| Wave | Hours | Everyone does | Exit condition |
|------|-------|---------------|----------------|
| **1 — Contracts & Scaffold** | 0–3 | harsha merges #1 (scaffold + `contracts.py`). Everyone else stubs their module signatures against it. | `uv run devorchestrator --help` works; every lane has stub files that import from `contracts` |
| **2 — Parallel Build** | 3–11 | Each lane builds its own modules **independently**. No shared files touched. | Each module works in isolation (unit-runnable) |
| **3 — Integration** | 11–15 | harsha wires `pipeline.py` end-to-end; each owner fixes their module's glue on request. | `devorchestrator start` runs task→research→impl→checks→PR |
| **4 — Polish & Demo** | 15–18 | review gate (#4), mesh dashboard (#14), autofix polish (#10/#12), demo dry-run (#7). | Full dry-run passes; demo script rehearsed |

**#1 is the unblocker — nothing else starts until it's merged.**

---

## Git flow (per task)

We use the vendored **`/start-task`** skill to standardize this — run it in Claude Code and it does the steps below for you:

1. Pick your assigned issue from the board (**Backlog → Ready**).
2. Branch: `feature/issue-<N>-<slug>` off `dev`.
3. Implement inside your lane's files only. Commit small, with `issue #N:`.
4. Move issue **In Progress** while coding.
5. Open a PR into **`dev`** (not `main`). Assign a teammate to review.
6. Issue auto-moves to **In Review**; on merge, **Done**.

> **Lane B note:** issue #6 deliberately **wraps `/start-task`'s** branch + PR logic instead of rebuilding it. Lift the naming/PR-creation steps from `.claude/skills/start-task/SKILL.md` — don't reinvent them.

---

## Vendored skills (in this repo — everyone can use them)

Available under `.claude/skills/` so all four of you get the same tools in Claude Code:

| Skill | Use it to… |
|-------|-----------|
| `/plan-project` | Set up / re-plan the board, add issues, plan a sprint |
| `/new-issue` | Log a new bug/feature mid-hackathon (auto-adds to Backlog) |
| `/start-task` | Pick up your assigned issue → branch → implement → PR → In Review |

If you hit an unplanned bug or scope, run **`/new-issue`** rather than editing code silently — it keeps the board honest and avoids two people fixing the same thing.

---

## Coordination without meetings (use the mesh)

Once Lane D's mesh (#13) is up, log decisions instead of losing them in chat:

- `devorchestrator decision "switched PR body to markdown"` → visible to the whole team
- `devorchestrator mesh` → who's touching what module right now (conflict warning if two of you overlap)

This is also your **demo's observability story** — the same mesh that keeps you from colliding is what judges see on screen.

---

## If two people must touch the same thing (escape hatch)

It shouldn't happen if you stay in your lane. If it's unavoidable:
1. Ping the file's owner in chat — **they** make the edit, or explicitly hand it over for one commit.
2. Never both edit in parallel. Serialize it. One commit, one owner, then release.

---

## Demo (hour 18) — the one sentence

> *An issue becomes a reviewed, merged PR with zero human coding — four AI companions do the work, and every decision is observable in the mesh.*

Live beats to show: **two tmux panes** (research + impl) → **artifact** appears → **autofix self-heals** a failing check → **PR opens automatically** → **`devorchestrator mesh`** shows the team + escalation trail → human hits `[a]` to merge. Full script in `docs/DEMO.md` (#7).
