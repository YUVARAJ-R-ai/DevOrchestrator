# Demo Runbook

**The one-line pitch:**
> An issue becomes a reviewed, merged PR with zero human coding — AI companions do the work, and every decision is observable in the mesh.

> **If you are recording the video and did not build this:** read [Setup](#setup-one-time) → [The three commands](#the-three-commands) → [What to say while it runs](#what-to-say-while-it-runs). That is everything you need. The rest is failure handling.

---

## What the tool actually does

One command picks a GitHub issue, and from there the machine: creates the branch, checks it out locally, runs **two live Claude Code sessions in tmux** (one reads the codebase and writes a plan, one implements that plan), commits and pushes, runs `ruff` + `pytest`, re-invokes the agent to fix its own failures, opens a real PR with an AI-written description, and moves the issue across the project board.

**The human does exactly two things:** pick the issue, and approve the PR. That contrast is the demo.

---

## Setup (one-time)

### 1. Config

```bash
devorchestrator init
```

Interactive — it writes `devOrchestrator.yaml` and `.env` for you, then makes a real API call to confirm the token works and can see the repo. Prefer this over copying the template by hand.

If you'd rather edit by hand: `cp devOrchestrator.yaml.template devOrchestrator.yaml`. The fields that matter:

| Field | Value | Why |
|---|---|---|
| `name` | your display name | used in mesh events + notifications |
| `board.url` / `git.url` | the repo URL | |
| `board.project_number` | **10** | the GitHub Project the issues live on |
| `git.reviewer` | your GitHub **login** (e.g. `Haise-727`) | **`devorchestrator review` finds nothing without it** — see below |

> ⚠️ `git.reviewer` is a GitHub *login*, not the `name` field above. The review gate lists PRs where that login is a requested reviewer; a display name matches nothing.

### 2. Env vars (`.env`, which `init` writes for you)

| Var | Needed? |
|---|---|
| `GITHUB_TOKEN` | **Yes.** Classic PAT with **both `repo` and `project`** scopes — `project` is for reading the board's Priority/Size fields, and a token missing it fails with an unhelpful GitHub error |
| `SILICONFLOW_API_KEY` | Optional — brain-written PR descriptions. Without it you get a mechanical description; nothing breaks |
| `SUPABASE_SERVICE_KEY` | Optional — the mesh. Without it, no conflict detection or decision log; the task→PR loop still works |
| `MATTERMOST_WEBHOOK` | Optional — team notifications |

### 3. On PATH

`tmux`, `claude` (logged in via `claude auth login`), `uv`.

Without `tmux` everything still runs, but headless — **you lose the two live panes, which are the visual centerpiece.** Install it before recording.

### 4. Clean working tree

`git status` should be empty before you start. The commit step runs `git add -A`, so anything uncommitted sitting around gets swept into the AI's commit.

### 5. The seeded issue

Issue **#30** ("demo: add a Python version guard helper") is on the board in Backlog. It's deliberately small and touches only new files, so a live AI run has good odds of finishing cleanly on camera. Re-open it after each rehearsal.

---

## The three commands

Run these from the repo root, in this order. **`pr` requires `start` to have run first** — `start` saves the task context that `pr` reads.

```bash
devorchestrator start     # pick #30 → branch → research pane → impl pane → commit + push
# ── look at the code the AI wrote; this pause is the point ──
devorchestrator pr        # ruff + pytest → autofix on failure → opens the real PR
devorchestrator review    # the human moment: diff | checks | artifact → [a] approve
```

**In a second terminal, before `start` finishes:**
```bash
tmux attach -t do-<branch-name>
```
This is the shot worth filming — two panes, one planning, one writing code.

### What each command prints

| Command | You should see | Takes |
|---|---|---|
| `start` | issue list → your pick → branch created → two tmux panes spawn → `implementation session finished` → `committed and pushed to <branch>` | minutes — research reads real files |
| `pr` | check results table → (autofix retries if red) → `✓ PR opened: <url>` | under a minute if checks pass |
| `review` | the PR's diff, check results, and the artifact side by side → `[a]/[r]/[q]` prompt | instant |

Press **`a`** at the review prompt. That merges the PR for real.

---

## What to say while it runs

The dead air during the research session is the risk. Beats worth narrating, in order:

1. **"The only thing I did was pick an issue."** — right after selecting #30.
2. **"This pane is reading the codebase, not guessing."** — during research. It's opening real files; that's why it isn't instant.
3. **"That's the plan it wrote."** — when `artifact.md` appears. Show it. This is the artifact the second session implements against, and the contract between what was decided and what got built.
4. **"Checks failed, so it's fixing its own work."** — if autofix fires. This is the best unscripted moment you can get; don't rush past it.
5. **"The issue moved itself across the board."** — flip to the GitHub Project, the Status column tracks the run.
6. **"Now the only other human step."** — press `a`.

---

## Dry-run checklist (before recording, not during)

- [ ] Full `start` → `pr` → `review` run on the actual recording machine and network
- [ ] Both tmux panes render, and the font is legible at recording resolution
- [ ] The PR really opened on GitHub — click it, don't trust stdout
- [ ] `devorchestrator review` actually listed the PR (if it says "No PRs awaiting your review", `git.reviewer` is wrong — see Setup)
- [ ] Time the research session so you know how long you're narrating
- [ ] Reopen issue #30 and delete the branch afterwards so the live run starts clean

---

## If something breaks

| Failure | What to do |
|---|---|
| **`review` says "No PRs awaiting your review"** | `git.reviewer` isn't your GitHub login. Fix it in `devOrchestrator.yaml` and re-run `review` — the PR is already open, nothing is lost. |
| **`pr` says "No saved task context"** | You ran `pr` without `start`, or from a different branch. Check you're on the feature branch `start` created. |
| **Brain unreachable** | Degrades silently to a mechanical PR description. Nothing to do. |
| **Supabase mesh unreachable** | Runs with the mesh off. The task→PR loop still completes; just skip the mesh beat rather than pretending it ran. |
| **`claude` rate-limited mid-session** | No account rotation exists. Fall back to a pre-recorded capture of a good dry-run — **have one recorded before you start.** |
| **Branch already exists** | A previous run left it. `git push origin --delete feature/issue-30-...`, reopen #30, retry. |
| **No tmux on the machine** | It runs headless. You lose the panes; narrate instead. |
| **Total failure** | Walk the architecture and the merged code on GitHub. The story holds as a code walkthrough. |

**One-shot alternative:** `./scripts/demo.sh` runs the whole loop non-interactively (no pause between implementation and PR). It uses the same `build_pipeline`/`build_review` as the CLI, so it behaves identically — useful if you'd rather not type three commands on camera.

---

## After recording

Close or reopen issue #30 and delete the demo branch so the next run starts clean. Don't merge rehearsal PRs into `main`.
