# Sprint 1 — Core AI Loop
**Jun 8–12, 2026 · 10/10 pts · Solo dev (Claude Code)**

---

## MVP Definition
A developer can run `devorchestrator start`, pick a task from Plane, watch a branch get created, then watch two sequential Claude Code sessions — one that researches the task and writes `artifact.md`, and one that reads the artifact and implements the code. No automation after that yet — the dev manually pushes and creates the PR. The **inner AI loop is working.**

```
devorchestrator start
  → select task from Plane
  → branch created on Gitea
  → tmux pane 1: Claude Code researches → writes artifact.md
  → terminal: artifact preview shown
  → tmux pane 2: Claude Code reads artifact → implements
  → dev reviews, pushes manually
```

---

## Sprint Backlog

### Infra & Project Scaffold
- [ ] **(M) #1** — Initialize project with `uv init`, configure `pyproject.toml`, wire `devorchestrator` as CLI entry point via `[project.scripts]`
  - Entry point: `devorchestrator.cli:main`
  - Commands scaffold: `start`, `pr`, `review`, `init`, `status`

### Configuration Layer
- [ ] **(S) #5** — Write Pydantic v2 schema for `devOrchestrator.yaml`
  - Fields: `name`, `role` (dev/tl), `agent` (claude/agy), `board`, `git`, `brain`, `notify`
  - Nested models for each section
- [ ] **(S) #6** — Build config loader: reads `devOrchestrator.yaml` from CWD, merges `.env`, detects track (oss vs azure) from `board.type`
- [ ] **(S) #7** — Validation error messages with fix hints — fail loud at startup, not mid-run
  - Example: `Missing board.token_env — set PLANE_API_KEY in your .env`

### Task Board
- [ ] **(M) #8** — Plane REST API client
  - `GET /api/v1/workspaces/{slug}/projects/{id}/issues/`
  - Filter: `assignees=me`, `state__group=started,unstarted`, current sprint cycle
  - Returns: `list[Issue]` with id, title, priority, estimate, state
- [ ] **(S) #9** — Rich terminal task selector
  - Table: title | priority | estimate | state
  - Arrow key navigation, Enter to select, `q` to quit
  - Depends on: #8

### Git Server
- [ ] **(M) #11** — Gitea API client: create branch
  - `POST /api/v1/repos/{owner}/{repo}/branches`
  - Branch name: `feature/{task-id}-{slugified-title}`
  - Auto-checkout locally after creation

### Research Session
- [ ] **(S) #13** — Design and document `artifact.md` schema
  - Sections: Context, Sub-tasks (checkboxes), Files to Create/Modify, Acceptance Criteria, Implementation Notes
  - Write as a Jinja2 template so the research session knows the exact format to produce
- [ ] **(M) #14** — Research prompt template
  - Prompt instructs Claude Code to: read relevant files, understand existing patterns, identify risks, then write `artifact.md` at `.orchestrator/{branch}/artifact.md`
  - Includes: task title, description, branch name, artifact schema
- [ ] **(M) #15** — libtmux pane spawner for research session
  - Creates tmux session `do-{branch}`, window `research`
  - Sends: `claude -p "$(cat .orchestrator/{branch}/research-prompt.txt)"`
  - Depends on: #14
- [ ] **(S) #16** — Artifact.md file watcher
  - Polls `.orchestrator/{branch}/artifact.md` every 2s using `watchfiles` or `os.path.getmtime`
  - Resolves when file appears and is non-empty
  - Depends on: #15
- [ ] **(S) #17** — Artifact Rich renderer
  - Reads `artifact.md` and pretty-prints with Rich Markdown
  - Shows after research session exits: "Research complete — review artifact above. Press [Enter] to start implementation, [e] to edit first."
  - Depends on: #16

### Implementation Session
- [ ] **(S) #18** — Implementation prompt template
  - Prompt: "Read the artifact at `.orchestrator/{branch}/artifact.md` and implement every sub-task. Check off each task as you complete it."
- [ ] **(M) #19** — libtmux pane spawner for implementation session
  - New window `impl` in existing `do-{branch}` session
  - Sends: `claude -p "$(cat .orchestrator/{branch}/impl-prompt.txt)"`
  - Dev watches pane live — can intervene at any point
  - Depends on: #16
- [ ] **(S) #20** — Pane monitor
  - Watches impl pane for exit (poll pane `is_alive`)
  - On exit: prints "Implementation complete. Run `devorchestrator pr` to continue."
  - Depends on: #19

---

## Definition of Done
- [ ] `devorchestrator start` runs without error on a fresh clone + `.env` file
- [ ] A real Plane task can be selected from the terminal
- [ ] A branch is created on Gitea and checked out locally
- [ ] Research tmux pane opens, Claude Code produces a valid `artifact.md`
- [ ] Artifact is previewed in terminal with correct formatting
- [ ] Implementation tmux pane opens, Claude Code implements the artifact
- [ ] Dev can watch both sessions live in the terminal

## Carry-over Risk
- libtmux session management is the highest-risk task — if tmux integration is harder than expected, the pane monitor (#20) and artifact renderer (#17) can be cut to keep the core loop working with simpler subprocess calls.
