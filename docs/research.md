# Project Research: Sprint Multiplier
_Generated: 2026-06-05_

## Problem & Goal
Out of a 10-day sprint, ~60% is non-feature friction: boilerplate, PR setup, waiting on review, context switching between tasks. No existing tool automates the full SDLC loop end-to-end while remaining agent-agnostic and infra-agnostic. Sprint Multiplier absorbs that friction via a CLI orchestrator, targeting 2× sprint velocity for a 4-dev team.

## Target Users
- **Primary**: Small dev teams (2–6 devs) who are already using AI co-pilots (Claude Code, Cursor, agy) and want to eliminate repetitive SDLC plumbing
- **Secondary**: Team leads who need a low-friction approval gate without losing visibility
- **Initial**: Solo developer (Yuvaraj) dogfooding before team rollout

---

## Competitive Landscape

| Product | Strengths | Weaknesses | Key Takeaway |
|---------|-----------|------------|--------------|
| **PR-Agent** (open source) | AI PR descriptions, reviews, self-hosted, no per-seat pricing | Only covers PR review step, no pipeline orchestration | Good reference for PR description generation logic |
| **CodeRabbit / Qodo Merge** | Excellent async PR review, GitHub/GitLab native | SaaS only, single-step (review), no task fetch or deploy | Confirms the review bottleneck — 27.6% of PRs are now AI-generated |
| **Linear + Copilot** | Best-in-class UX, task ↔ branch link | No automation layer, still requires manual branch/PR/deploy steps | Proves the demand; doesn't solve the plumbing |
| **Tmux-Orchestrator** (absmartly) | Three-tier hierarchy, tmux process isolation pattern | Dev tooling only, no SDLC awareness, no shared context | Validates tmux as agent runtime; borrow session management pattern |
| **AgentCollision** | File-lease system for parallel AI agents, collision queue | Only solves file-level locking, no team memory, no CI/CD | Confirms the collision problem is real and unsolved cleanly |
| **Claude Code Agent Teams** | git worktrees per subagent, shared task list | Anthropic-internal pattern, not a packaged tool | Validates the shared task list concept; Sprint Multiplier goes further with a persistent mesh |
| **amux / agentmaxxing** | tmux session pool, parallel agent execution guide | Manual setup, no rate-limit-aware routing, no SDLC pipeline | Confirms the pattern; Sprint Multiplier automates the rotation |
| **LOFT / Azure AI SDLC** | Enterprise-grade agentic SDLC from Microsoft | Vendor lock-in, heavy, Azure-only, not for self-hosted teams | Shows the enterprise version of the same idea; confirms market need |

---

## Feature List

### Core (MVP)
- [ ] YAML config loader — without one-file setup, onboarding friction breaks the "plug and play" promise
- [ ] Task fetch (Plane REST API) — the loop starts here; can't automate what you can't read
- [ ] Branch creation (Gitea API) — eliminates the most mindless manual step
- [ ] `claude -p` subprocess wrapper — the AI co-pilot integration; everything downstream depends on it
- [ ] Auto-checks runner (lint + secrets scan + unit tests) — gate before PR; prevents junk PRs
- [ ] PR creation with auto-generated description (Gitea API) — closes the inner loop; links back to task card
- [ ] TL approval gate (terminal view: diff + test results + task context, one keypress to merge) — the only human checkpoint
- [ ] Deploy webhook trigger (Coolify) — completes the loop; no deploy = no done
- [ ] Task close + Mattermost notification — team visibility; confirms the automation worked

### Important (v1.1)
- [ ] Shared context mesh (SQLite + JSON, write on task start / decisions, read before acting) — the novel differentiator; prevents merge wars before they happen
- [ ] Conflict detection (warn when two devs touch the same module) — turns silent collisions into explicit nudges
- [ ] Account rotation (tmux session pool, rate-limit detection, auto-switch to next account) — necessary once the team actually hits rate limits at scale
- [ ] Azure DevOps track (Azure Boards + Repos + Pipelines + App Service + Teams) — unlocks enterprise teams; same YAML, different URLs
- [ ] Autofix flag (`--autofix`) on check failures — agent retries the fix instead of blocking the dev

### Nice-to-have (Backlog)
- [ ] `agy` / `codex` subprocess support (agent-agnostic routing)
- [ ] Metrics dashboard (cycle time, velocity, time-saved per sprint)
- [ ] Teams/Slack notification adapter
- [ ] Web dashboard for TL (visual kanban view over the mesh)
- [ ] Git worktree isolation per agent (prevent file-level conflicts in parallel runs)

### Don't Build
- Full project management UI — Plane already does this; don't duplicate
- CI/CD pipeline engine — Woodpecker CI handles YAML pipelines natively; just trigger it
- In-editor IDE plugin — CLI is the correct surface; IDE plugins are maintenance sink
- General-purpose AI memory (like mem0) — too generic; the mesh must be dev-workflow-specific to stay useful

---

## Task Breakdown

### YAML Config Loader
- [ ] Write Pydantic schema for `orchestrator.yaml` (S)
- [ ] Build config loader with track auto-detection (oss vs azure from URLs) (S)
- [ ] Write config validation error messages (S)

### Task Fetch
- [ ] Build Plane REST API client (fetch sprint tasks by assignee + state filter) (M)
- [ ] Write terminal task selector (Rich table, arrow-key select) (S) ← depends on: Plane client
- [ ] Build Azure Boards REST API client (query work items by sprint iteration) (M)

### Branch + Scaffold
- [ ] Build Gitea API branch creation from task slug (M)
- [ ] Write `claude -p` subprocess wrapper (stdin prompt → stdout capture, timeout, error handling) (M)
- [ ] Build scaffold prompt template (task description → boilerplate generation request) (S) ← depends on: subprocess wrapper
- [ ] Build Azure Repos API branch creation (M)

### Auto-checks
- [ ] Build check runner orchestrator (lint via ruff, secrets via gitleaks, tests via pytest) (M)
- [ ] Write check result formatter (Rich panel, pass/fail per check) (S) ← depends on: check runner
- [ ] Implement `--autofix` flag (re-invoke subprocess wrapper with failure context) (M) ← depends on: subprocess wrapper + check runner

### PR Creation
- [ ] Build PR description generator (parse `git log` + task title → structured description) (M)
- [ ] Build Gitea PR creation API call (link to task card, assign reviewer from config) (M) ← depends on: description generator
- [ ] Build Azure Repos PR creation API call (auto-link work item, assign required reviewer) (M) ← depends on: description generator

### TL Approval Gate
- [ ] Build TL terminal view: diff pane + test summary + task context (Rich layout) (L)
- [ ] Write approval keypress handler → merge API call → branch delete (M) ← depends on: TL view
- [ ] Write rejection handler → comment on PR + notify dev via Mattermost (S) ← depends on: TL view

### Deploy + Notify
- [ ] Build Coolify deploy webhook trigger + health check poller (M)
- [ ] Build Azure App Service release pipeline trigger (M)
- [ ] Write task-close API call (Plane / Azure Boards) after deploy success (S) ← depends on: deploy trigger
- [ ] Write Mattermost webhook notification (deploy result + task link) (S)

### Shared Context Mesh (v1.1)
- [ ] Design SQLite schema: `events(id, dev, module, event_type, payload, ts)` (S)
- [ ] Write mesh writer: emit on task-start, on branch-create, on decision log (M) ← depends on: schema
- [ ] Write mesh reader: `who_is_touching(module)`, `what_decisions_made()` (S) ← depends on: writer
- [ ] Build conflict detector: cross-ref active modules on task-start, surface warning (M) ← depends on: mesh reader

### Account Rotation (v1.1)
- [ ] Build tmux session pool manager (create N sessions per config, name by account) (L)
- [ ] Write rate-limit detector (parse `claude -p` stderr for limit signals) (M)
- [ ] Write routing logic (round-robin, skip sessions in cooldown) (M) ← depends on: pool manager + detector
- [ ] Integrate routing into subprocess wrapper (S) ← depends on: routing logic

---

## Tech Recommendations

### Two-model architecture
The orchestrator uses two distinct model tiers:
- **Brain model** (DeepSeek V3 via OpenRouter) — all orchestration logic: task parsing, prompt generation, PR descriptions, routing decisions, mesh queries. Fast, cheap, runs constantly.
- **Worker model** (`claude -p` sessions) — actual code writing, test generation, autofix. Only invoked when a human is producing a feature. Expensive model, used sparingly.

Both use the OpenAI-compatible API. Switch provider by changing `base_url` and `api_key_env` in config — no code changes.

```yaml
# orchestrator.yaml
orchestrator_model:
  provider: openrouter            # or: siliconflow
  model: deepseek/deepseek-chat   # verify exact model ID on openrouter.ai
  api_key_env: OPENROUTER_API_KEY

worker_agent: claude              # or: agy, codex
```

```python
# Single client, provider-swappable
from openai import AsyncOpenAI
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",   # siliconflow: https://api.siliconflow.cn/v1
    api_key=os.environ[config.orchestrator_model.api_key_env],
)
```

| Layer | Recommendation | Reason |
|-------|---------------|--------|
| Language | Python 3.12 | Already decided; asyncio handles concurrent subprocess + API calls cleanly |
| Config schema | Pydantic v2 | Type-safe YAML parsing; catches bad configs at startup, not mid-run |
| Brain model | DeepSeek V3 via OpenRouter | Cheap + fast for routing/prompt-gen; OpenAI-compatible API; swappable by config |
| Brain model fallback | SiliconFlow | Cheaper but CN-hosted; use as cost fallback, not primary (latency + privacy) |
| LLM client | `openai` Python SDK (AsyncOpenAI) | Same SDK works for OpenRouter, SiliconFlow, and any OpenAI-compatible endpoint |
| HTTP client | httpx (async) | Single client for all REST APIs (Plane, Gitea, Coolify, Azure DevOps) |
| Shared mesh DB | SQLite (stdlib) | Zero extra infra; WAL mode handles concurrent writes from 4 devs |
| Worker agent | `claude -p` via `subprocess.run` | Non-interactive mode; stdout capture; use `claude setup-token` for CI |
| Session management | libtmux | Python bindings for tmux; battle-tested; used by absmartly/Tmux-Orchestrator |
| Terminal UI | Rich | Tables + panels for task selector and TL approval view; no heavy framework |
| Secrets scanning | gitleaks (subprocess) | Industry standard; runs as a subprocess call; zero Python dependency |
| Packaging | uv + pyproject.toml | Fast installs; reproducible envs; single `uv run orchestrator` entry point |
| Infra | Docker Compose on Debian/Tailscale | Already planned; one `docker compose up` for full OSS stack |

---

## Risks & Open Decisions

### Risks
- **`claude -p` pricing/API change** (June 2026 pricing split surfaced in research) — mitigation: use Claude Agent SDK (`pip install claude-agent-sdk`) as the subprocess layer; not just raw CLI
- **Rate limits under team load** — mitigation: account rotation is planned (Layer 4, Day 6); build detection early even before rotation is wired
- **SQLite concurrent writes (mesh)** — mitigation: enable WAL mode at init; all writes are short and infrequent (event-per-task)
- **Plane/Gitea API instability** (smaller OSS projects) — mitigation: thin adapter pattern; each API is one class, swap without touching orchestrator logic
- **Azure DevOps API complexity** (PAT scopes, nested org/project/repo paths) — mitigation: build OSS track first, add Azure as v1.1 after core loop is validated
- **Team adoption friction** — mitigation: zero-training design (orchestrator surfaces, doesn't command); one YAML file; TL gate is the only new habit required

### Open Decisions
- [ ] **Daemon vs per-invocation**: Should the orchestrator run as a persistent background daemon (better for rate-limit detection and mesh sync) or be invoked per-task (simpler MVP)? → Recommend: per-task invocation for MVP, daemon wrapper in v1.1
- [ ] **Azure DevOps in MVP?** → No. OSS track only for Day 1–6. Azure is v1.1 — validate the pipeline shape first
- [ ] **agy support in MVP?** → No. `claude -p` only. Agent-agnostic routing is v1.1 once the subprocess interface is stable
- [ ] **Mesh as embedded module or standalone service?** → Embedded Python module for MVP (SQLite file on shared server). Extract to microservice only if a web dashboard is needed
- [ ] **Secrets in `orchestrator.yaml`?** → API tokens via environment variables only (`.env` loaded by orchestrator at startup). Never written to YAML. Document this clearly

---

## GitHub References
- [absmartly/Tmux-Orchestrator](https://github.com/absmartly/Tmux-Orchestrator) — three-tier tmux hierarchy; study the session spawn + heartbeat monitor pattern
- [raine/tmux-agent-usage](https://github.com/raine/tmux-agent-usage) — rate limit display from tmux status bar; borrow the Claude rate-limit stderr parsing approach
- [awslabs/cli-agent-orchestrator](https://github.com/awslabs/cli-agent-orchestrator) — supervisor-worker pattern over MCP; reference for multi-agent coordination without shared state
