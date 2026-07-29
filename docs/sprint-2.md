# Sprint 2 — Quality Gates + PR Automation
**Jun 15–19, 2026 · 9/10 pts · Solo dev (Claude Code)**

---

## MVP Definition
After Claude Code finishes implementing, the orchestrator automatically runs quality checks (lint, secrets scan, tests). If checks fail, it retries with Claude Code. If checks pass, it generates an AI-written PR description and opens the PR on Gitea. The TL gets a terminal dashboard to review the diff and merge with one keypress. **The pipeline is now fully automated from task selection to merged PR.**

```
devorchestrator pr
  → ruff + gitleaks + pytest run automatically
  → FAIL → claude -p retries with failure context
  → PASS → DeepSeek writes PR description from git log + artifact
  → Gitea PR opened, TL assigned

devorchestrator review          ← TL runs this
  → Rich view: diff | test results | artifact | CI status
  → [a] approve → merge → branch deleted
  → [r] reject → comment posted + dev notified
```

---

## Sprint Backlog

### Auto-checks
- [ ] **(M) #22** — Check runner
  - Runs as subprocesses sequentially: `ruff check .` → `gitleaks detect` → `pytest`
  - Returns: `CheckResult(tool, passed, output, duration)` per check
  - Stops on first failure by default; `--all-checks` flag runs everything regardless
- [ ] **(S) #23** — Rich pass/fail result panel
  - Shows each check as a row: tool name | ✅/❌ | duration | summary
  - On failure: prints truncated output with "see full log at `.orchestrator/{branch}/checks.log`"
  - Depends on: #22
- [ ] **(M) #24** — `--autofix` flag
  - On check failure: builds a fix prompt (failure output + artifact + relevant file diffs)
  - Re-spawns impl session with fix context in `.orchestrator/{branch}/fix-prompt.txt`
  - Max retries: 2 (configurable in `devOrchestrator.yaml`)
  - Depends on: #19 (impl spawner), #22

### PR Automation
- [ ] **(S) #25** — DeepSeek V4 Flash client
  - `AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=...)`
  - Wrapper: `brain.complete(prompt: str) -> str`
  - Reads `brain.provider` and `brain.token_env` from config
- [ ] **(M) #26** — PR description generator
  - Input: `git log origin/{base}..HEAD --oneline`, artifact.md sub-tasks checklist, changed file list
  - Prompt to DeepSeek: generate a structured PR description (summary, what changed, testing notes)
  - Output saved to `.orchestrator/{branch}/pr-description.md`
  - Depends on: #25
- [ ] **(M) #27** — Gitea PR creation
  - `POST /api/v1/repos/{owner}/{repo}/pulls`
  - Body: title (from task), body (from #26), head branch, base branch, assignees (TL from config)
  - Prints PR URL to terminal on success
  - Depends on: #26

### TL Approval Gate
- [ ] **(L) #29** — Rich TL approval view
  - 3-pane Rich layout:
    - Left: `git diff` output (syntax-highlighted via Rich)
    - Top right: test results summary + CI status (polls Gitea CI status API)
    - Bottom right: artifact.md rendered (what was planned)
  - Footer: `[a] Approve & Merge  [r] Reject  [o] Open in browser  [q] Quit`
  - Fetches open PRs assigned to TL from Gitea API on `devorchestrator review`
- [ ] **(M) #30** — [a] Approve handler
  - `POST /api/v1/repos/{owner}/{repo}/pulls/{index}/merge`
  - Merge strategy: squash (configurable: merge/squash/rebase in config)
  - Delete source branch after merge
  - Prints: "Merged ✅ — {PR title}"
  - Depends on: #29
- [ ] **(S) #31** — [r] Reject handler
  - Prompts TL for rejection reason (one-line input)
  - Posts comment on Gitea PR with reason
  - Sends Mattermost DM to dev: "PR rejected: {reason} — {PR URL}"
  - Depends on: #29

---

## Definition of Done
- [ ] After `devorchestrator pr`: ruff, gitleaks, pytest run automatically and results display in terminal
- [ ] A failing check triggers --autofix and re-runs the implementation session
- [ ] A passing check auto-generates a PR description and opens the PR on Gitea
- [ ] TL can run `devorchestrator review` and see diff + tests + artifact in one view
- [ ] TL can approve (merge) or reject (comment + notify) with a single keypress
- [ ] End-to-end: task selected → implemented → checks pass → PR merged by TL, all in one session

## Carry-over Risk
- Rich TL view (#29) is the most complex UI task — if layout is tricky, fall back to a simpler sequential display (diff, then tests, then artifact) with the same [a]/[r] keybindings. Functionality over polish.
