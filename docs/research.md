# Project Research: DevOrchestrator
_Generated: 2026-06-05_

## Problem & Goal
Out of a 10-day sprint, ~60% is non-feature friction: boilerplate, PR setup, waiting on review, context switching. No existing tool automates the full SDLC loop end-to-end — from task selection to deployed code — while using only a Claude Code Pro subscription (no API key). DevOrchestrator absorbs that friction: the developer picks a task and reviews the result. The machine does everything else.

## Target Users
- **Primary**: Small dev teams (2–6 devs) already using Claude Code who want to eliminate repetitive SDLC plumbing
- **Secondary**: Team leads who need a low-friction approval gate without losing visibility
- **Initial**: Solo developer (Yuvaraj) dogfooding before team rollout

---

## The Pipeline (How It Actually Runs)

```
dev runs: devorchestrator start
```

```
[1]  Config loads            devOrchestrator.yaml → board, git server, agent binary, role
[2]  Task fetch              → Plane / Azure Boards REST API → tasks displayed in terminal
[3]  Dev selects task        ← HUMAN: picks which task to work on
[4]  Branch created          → git server API creates feature/task-slug automatically

[5]  Research session        → orchestrator spawns tmux pane 1
                               runs: claude -p "[research prompt + task description]"
                               Claude Code reads codebase files, checks patterns, identifies
                               relevant modules and risks using its built-in file/bash tools
                               → writes .orchestrator/[branch]/artifact.md and exits

[6]  Orchestrator polls      → watches for artifact.md to appear (inotify / file watch)
                               renders artifact preview in terminal
                               ← OPTIONAL HUMAN GATE: dev can edit artifact before impl

[7]  Implementation session  → orchestrator spawns tmux pane 2
                               runs: claude -p "implement .orchestrator/[branch]/artifact.md"
                               Claude Code reads artifact + relevant files → implements
                               dev watches tmux pane live — can intervene at any point

[8]  Dev reviews output      ← HUMAN: reviews what Claude Code produced, makes fixes
[9]  Dev runs: devorchestrator pr

[10] Auto-checks             → ruff lint + gitleaks secrets scan + pytest
     FAIL → re-invokes claude -p with failure context + artifact (--autofix)
     PASS → continue

[11] PR created              → DeepSeek V4 Flash generates PR description from git log
                               → git server API opens PR, links to task card

[12] TL notified             → Mattermost: "PR ready: [task title] by [dev]"
[13] TL runs: devorchestrator review
     → terminal view: diff | test results | CI status | artifact (what was planned vs built)
     → [a] approve → merge API call | [r] reject → comment + notify dev

[14] CI/CD fires             → Woodpecker CI / Azure Pipelines (YAML in repo)
[15] Deploy                  → Coolify webhook → health check polls until green
[16] Task closed             → board API marks Done → Mattermost team notification
```

**Human moments: [3] pick task, [6] optionally edit artifact, [8] review implementation.** Everything else is the machine.

### Why two Claude sessions instead of DeepSeek for the artifact

Claude Code has tools — it can read files, run bash, search the web. When the research session runs, it actually opens your codebase and understands it. A DeepSeek chat call via OpenRouter only sees the task description as text. The artifact produced by a Claude Code research session is categorically richer.

DeepSeek V4 Flash is now only used for one thing: **PR description generation** — a fast, cheap text transformation from `git log` output that doesn't need codebase access. If you want to drop the OpenRouter dependency entirely, this step can also be a third Claude session.

---

## The Artifact

The artifact is the central coordination document generated at step [6]. It is what gets passed directly to Claude Code as its implementation spec.

```markdown
# Artifact: [Task Title]
_Task: PROJ-42 | Branch: feature/user-auth | Generated: 2026-06-05_

## Context (from research sub-agent)
- Existing auth pattern: src/middleware/auth.py uses session-based approach
- JWT library already installed: python-jose==3.3.0
- Related files: src/models/user.py, src/routes/api.py
- Risk: session store not thread-safe — use Redis or switch to stateless JWT

## Sub-tasks
- [ ] Create User model with email + hashed password fields
- [ ] Implement JWT generation helper (use existing python-jose)
- [ ] Add POST /auth/login endpoint
- [ ] Add POST /auth/register endpoint
- [ ] Write auth middleware for protected routes
- [ ] Write unit tests for all endpoints

## Files to Create / Modify
- `src/models/user.py` — add User model
- `src/routes/auth.py` — new file, login + register
- `src/middleware/jwt.py` — new file
- `tests/test_auth.py` — new file

## Acceptance Criteria
- [ ] User can register with email/password
- [ ] User receives JWT on login
- [ ] Protected routes return 401 without valid token
- [ ] All tests pass
```

Claude Code receives this artifact and works through it systematically. The dev watches in the tmux pane.

---

## Competitive Landscape

| Product | Strengths | Weaknesses | Key Takeaway |
|---------|-----------|------------|--------------|
| **PR-Agent** | AI PR descriptions, self-hosted | Single-step only, no pipeline | Borrow PR description generation pattern |
| **CodeRabbit / Qodo Merge** | Excellent async review | SaaS, no task fetch or deploy | Confirms review bottleneck is real |
| **Linear + Copilot** | Best-in-class UX | No automation layer, all manual | Proves demand; doesn't solve plumbing |
| **Tmux-Orchestrator** (absmartly) | Three-tier tmux hierarchy | No SDLC awareness, no artifact system | Validates tmux as agent runtime |
| **AgentCollision** | File-lease collision prevention | No team memory, no CI/CD | Collision problem is real and unsolved cleanly |
| **Claude Code Agent Teams** | git worktrees, shared task list | Not a packaged tool | Validates the artifact-driven approach |
| **amux / agentmaxxing** | tmux session pool pattern | Manual, no SDLC pipeline | Confirms account rotation pattern |
| **LOFT / Azure AI SDLC** | Enterprise agentic SDLC | Vendor lock-in, Azure-only | Shows market need; no OSS equivalent |

---

## Feature List

### Core (MVP)
- [ ] YAML config loader — minimal config, zero-friction onboarding
- [ ] Task fetch (Plane REST API) — the loop starts here
- [ ] Branch creation (Gitea API) — from task slug, automatic
- [ ] Research sub-agent — placeholder module, pluggable; returns context.json
- [ ] Artifact generator (DeepSeek V4 Flash) — task + research → structured sub-task spec
- [ ] tmux subprocess spawner — launches `claude -p artifact.md` in a visible pane
- [ ] Auto-checks runner (ruff + gitleaks + pytest) — gate before PR
- [ ] PR creation with auto-generated description (Gitea API) — links to task card
- [ ] TL approval gate (Rich terminal view, one keypress to merge)
- [ ] Deploy webhook trigger (Coolify)
- [ ] Task close + Mattermost notification

### Important (v1.1)
- [ ] Shared context mesh (SQLite — who is touching what module, what decisions were made)
- [ ] Conflict detection (warn when two devs touch the same module before they start)
- [ ] Account rotation (tmux session pool, rate-limit detection, auto-switch)
- [ ] Azure DevOps track (same pipeline, different adapters)
- [ ] `agy` agent support alongside `claude`
- [ ] Autofix flag (`--autofix`) — re-invoke agent with check failure context

### Nice-to-have (Backlog)
- [ ] Research framework v1 (web search + codebase graph, not just file scan)
- [ ] Metrics (cycle time, velocity, AI vs human time ratio)
- [ ] Teams/Slack notification adapter
- [ ] Web dashboard for TL (mesh overview, PR queue)
- [ ] Git worktree isolation per agent

### Don't Build
- Full project management UI — Plane handles this
- CI/CD pipeline engine — Woodpecker CI handles YAML pipelines; orchestrator just triggers it
- IDE plugin — CLI is the right surface
- General-purpose AI memory — the mesh must stay dev-workflow-specific

---

## Task Breakdown

### Config Loader
- [ ] Write Pydantic schema for `devOrchestrator.yaml` (S)
- [ ] Build loader with track auto-detection (oss vs azure from board/git URLs) (S)
- [ ] Write clear validation errors with fix hints (S)

### Task Fetch + Selection
- [ ] Build Plane REST API client (fetch sprint tasks by assignee + state filter) (M)
- [ ] Write Rich terminal task selector (arrow-key, shows title + priority + estimate) (S) ← depends on: Plane client
- [ ] Build Azure Boards client (v1.1) (M)

### Branch Creation
- [ ] Build Gitea API branch creation from task slug (M)
- [ ] Build Azure Repos branch creation (v1.1) (M)

### Research Session
- [ ] Write research prompt template (task description → "read codebase, generate artifact.md") (M)
- [ ] Write libtmux pane spawner for research session (named: research-[branch]) (M)
- [ ] Write artifact.md file watcher (inotify/polling — detect when session writes the file) (S)
- [ ] Write artifact renderer (Rich preview in terminal after research session exits) (S)
- [ ] Design artifact.md schema (sub-tasks, files to touch, acceptance criteria, notes) (S)

### Implementation Session
- [ ] Write implementation prompt template ("implement artifact at [path]") (S)
- [ ] Write libtmux pane spawner for implementation session (named: impl-[branch]) (M) ← depends on: artifact watcher
- [ ] Write pane monitor (detect when session exits, surface status) (S)
- [ ] Write agy invocation adapter (v1.1) (M)

### Auto-checks
- [ ] Build check runner (ruff, gitleaks, pytest as subprocesses, structured results) (M)
- [ ] Write Rich pass/fail result panel (S)
- [ ] Implement --autofix (re-invoke agent with failure + artifact context) (M) ← depends on: tmux spawner

### PR Creation
- [ ] Build PR description generator (DeepSeek: git log + artifact → description) (M)
- [ ] Build Gitea PR API call (link task card, assign TL as reviewer) (M) ← depends on: description generator
- [ ] Build Azure Repos PR API call (v1.1) (M)

### TL Approval Gate
- [ ] Build Rich TL view: diff pane + test summary + artifact + CI status (L)
- [ ] Write [a] approve → merge API + branch delete (M) ← depends on: TL view
- [ ] Write [r] reject → PR comment + Mattermost ping to dev (S)

### Deploy + Notify
- [ ] Build Coolify webhook trigger + health check poller (M)
- [ ] Write task-close API call (Plane) after deploy success (S)
- [ ] Write Mattermost webhook notification (S)

### Shared Context Mesh (v1.1)
- [ ] Design SQLite schema: events(dev, module, event_type, payload, ts) (S)
- [ ] Write mesh writer: emit on branch-create, on artifact-generated, on decisions (M)
- [ ] Write mesh reader: who_is_touching(module), recent_decisions() (S)
- [ ] Build conflict detector: warn on module overlap at task-start (M)

### Account Rotation (v1.1)
- [ ] Build tmux session pool (N sessions, named by account) (L)
- [ ] Write rate-limit detector (parse claude stderr for limit signals) (M)
- [ ] Write round-robin router (skip sessions in cooldown) (M)
- [ ] Integrate into tmux agent spawner (S)

---

## Tech Recommendations

### Model Architecture
Two Claude Code sessions handle all AI work. DeepSeek is lightweight and optional:

| Session | Tool | Role | Cost |
|---------|------|------|------|
| **Research** | `claude` CLI (Code Pro) | Reads codebase → generates artifact.md | Pro subscription |
| **Implementation** | `claude` CLI (Code Pro) | Reads artifact → writes code | Pro subscription |
| **PR description** | DeepSeek V4 Flash (OpenRouter) | `git log` → PR description text | $0.14/M tokens |

Claude Code is invoked as a CLI subprocess — **no API key required**. The dev must be logged in via `claude auth login` with their Pro account. DeepSeek is used only for PR description generation; if you want zero external API dependencies, this step can also use a third Claude session instead.

```yaml
# devOrchestrator.yaml — full config, nothing else needed
name: yuvaraj
role: dev                   # or: tl
agent: claude               # binary in PATH, logged in via Pro subscription

board:
  type: plane
  url: https://plane.team.internal
  token_env: PLANE_API_KEY

git:
  type: gitea
  url: https://gitea.team.internal
  token_env: GITEA_TOKEN

brain:
  provider: openrouter
  model: deepseek/deepseek-v4-flash
  token_env: OPENROUTER_API_KEY

notify:
  type: mattermost
  webhook_env: MATTERMOST_WEBHOOK
```

```python
# Claude Code invocation — no API key, uses logged-in Pro session
import subprocess
result = subprocess.run(
    ["claude", "-p", artifact_content],
    capture_output=True, text=True
)

# Or via tmux (for live visibility)
import libtmux
session.new_window(window_name=branch).attached_pane.send_keys(
    f"claude -p \"$(cat {artifact_path})\""
)
```

### Full Stack

| Layer | Choice | Reason |
|-------|--------|--------|
| Language | Python 3.12 | asyncio for concurrent API calls; subprocess for agent invocation |
| Config | Pydantic v2 | Type-safe YAML; catches bad config at startup with clear error messages |
| Brain model | DeepSeek V4 Flash via OpenRouter | 83.6 tok/s, $0.14/M input; artifact generation + PR descriptions |
| Worker agent | `claude` CLI (Pro subscription) | No API key; already installed; runs in tmux for live visibility |
| LLM client | `openai` SDK (AsyncOpenAI, custom base_url) | OpenRouter + any future provider with zero code change |
| HTTP client | httpx (async) | All REST APIs: Plane, Gitea, Coolify, Mattermost |
| Mesh DB | SQLite (stdlib, WAL mode) | Zero infra; handles 4-dev concurrent writes |
| Session manager | libtmux | Python tmux bindings; spawn + monitor agent panes |
| Terminal UI | Rich | Task selector, artifact preview, TL approval view |
| Secrets scanner | gitleaks (subprocess) | Zero Python deps; industry standard |
| Packaging | uv + pyproject.toml | Single entry point: `uvx devorchestrator start` |
| Shared infra | Docker Compose on Debian via Tailscale | One `docker compose up` for full OSS stack |

---

## Setup (Seamless by Design)

**TL does once:**
```bash
# 1. On server: docker compose up -d
#    → Plane + Gitea + Woodpecker CI + Coolify + Mattermost

# 2. Commit devOrchestrator.yaml.template to repo (all shared URLs pre-filled)
# 3. Done
```

**Each dev does once:**
```bash
# 1. Install devOrchestrator
uvx install devorchestrator   # or: pip install devorchestrator

# 2. Copy template, fill in 4 personal lines
cp devOrchestrator.yaml.template devOrchestrator.yaml
# edit: name, role, and set env vars in .env

# 3. Init
devorchestrator init   # tests all connections, registers in mesh, done

# 4. Go
devorchestrator start
```

Total new-member setup time: under 10 minutes. No documentation to read — the CLI guides each step.

---

## Risks & Open Decisions

### Risks
- **Claude Code CLI breaking changes** — orchestrator calls the `claude` binary as a subprocess; major CLI changes could break invocation. Mitigation: pin the claude CLI version in devOrchestrator's dependencies; test against new releases
- **Rate limits on Pro subscription** — under heavy team load, a single Pro account hits limits. Mitigation: account rotation (v1.1); detect limit signals in stderr early
- **Research sub-agent quality** — poor research = poor artifact = poor implementation. Mitigation: build the research module iteratively; artifact preview step lets dev correct before agent runs
- **SQLite concurrent writes (mesh)** — 4 devs writing simultaneously. Mitigation: WAL mode enabled at init; writes are short event inserts
- **Plane/Gitea API stability** — smaller OSS projects, less stable APIs. Mitigation: thin adapter pattern per provider; swap without touching pipeline logic
- **Team adoption** — any new tool creates overhead. Mitigation: zero-config design; `devorchestrator start` is the only command a dev needs to learn

### Open Decisions
- [ ] **Artifact format: Markdown vs JSON?** → Markdown — Claude Code reads it naturally as a prompt; JSON is for the research context.json only
- [ ] **Research sub-agent in MVP or stub?** → Stub for MVP (simple codebase keyword scan). Full research framework is its own project milestone
- [ ] **tmux visibility: mandatory or optional?** → Mandatory for MVP — the dev watching the pane is a feature, not overhead. Headless mode in v1.1
- [ ] **Azure DevOps in MVP?** → No. OSS track only. Validate pipeline shape first
- [ ] **agy in MVP?** → No. `claude` CLI only. Agent-agnostic routing in v1.1
- [ ] **DeepSeek / external intelligence exact role** → Reserved as a general-purpose external AI layer. Current confirmed use: PR description generation. Future candidates: team chatbot, natural language mesh queries ("what did the team do this sprint?"), TL dashboard assistant, anything where a persistent conversational model fits better than a one-shot Claude session. Decide through experimentation — do not remove from the stack.

---

## GitHub References
- [absmartly/Tmux-Orchestrator](https://github.com/absmartly/Tmux-Orchestrator) — three-tier tmux hierarchy; study session spawn + heartbeat monitor
- [raine/tmux-agent-usage](https://github.com/raine/tmux-agent-usage) — rate-limit signal detection from claude stderr
- [awslabs/cli-agent-orchestrator](https://github.com/awslabs/cli-agent-orchestrator) — supervisor-worker pattern; reference for multi-agent coordination
