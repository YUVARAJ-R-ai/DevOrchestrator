# DevOrchestrator

> **The AI-native SDLC operating layer.** A developer picks a task and reviews the result. The machine does everything in between — research, implementation, quality gates, PR, review routing, deploy, and organizational memory.
>
> DevOrchestrator is the **first buildable slice** of a larger idea: the **AI-Native Enterprise**, where every human role has a policy-aware AI companion, and coordination happens through shared structured memory instead of tribal knowledge.

---

## The Vision — AI-Native Enterprise

Instead of treating AI as just another tool, we treat **every employee as having a mandatory AI companion**. Every human role has a corresponding AI agent that understands its owner's work, context, responsibilities, and company policy.

The AI does not replace the human. The human and AI operate as a **team**:

- **AI handles** implementation, boilerplate, routine coordination, documentation, information gathering, progress tracking, and context preservation.
- **Humans handle** architecture, system design, product decisions, review, approvals, hard edge cases, and creative problem solving.

### Why

Today's organizations lose enormous value to friction that isn't the actual work:

- Tribal knowledge lives only in people's heads.
- Human-to-human communication loses context over time and across ambiguous text.
- A large fraction of engineering time is operational coordination, not problem solving.
- Every departure or team switch is a knowledge-loss event.

The goal is to make AI the **primary operational layer** while humans stay responsible for strategic decisions — reducing communication overhead and turning ephemeral conversations into durable organizational memory.

### Core principles

| Principle | What it means |
|---|---|
| **Every role has a companion** | Manager ↔ Manager AI, Frontend ↔ Frontend AI, Backend ↔ Backend AI, QA ↔ QA AI, DevOps ↔ DevOps AI. |
| **Bring Your Own Agent** | The company provides governance and a protocol, **not** the assistant. Claude Code, Copilot, Cursor, OpenCode, Windsurf, or any future agent can connect. |
| **Coordinate through shared memory, not chatter** | Agents synchronize via a structured, queryable **mesh** and shared **artifacts** — not by two non-deterministic models improvising at each other. (See [design stance](#design-stance-what-we-deliberately-do-not-do).) |
| **Escalate, don't interrupt** | `AI → AI` first. Only unresolved issues become `AI → Human`, and only genuinely cross-cutting ones become `Human ↔ Human`. Outcomes are recorded back so context is never lost. |
| **Governance is first-class** | Every agent gets least-privilege, read-only access to the source of truth. A central policy engine enforces scope; out-of-scope access must be requested, approved, logged, and audited. |
| **Loosely coupled** | The enterprise owns the protocol, interfaces, security policy, and organizational memory — not one monolithic AI system. Any compliant agent participates. |

### Escalation model

```
AI ──▶ AI          routine issues resolved automatically, resolution logged
  │
  ▼ (unresolved)
AI ──▶ Human        escalated WITH full context, not fragmented chat messages
  │
  ▼ (needs several people)
Human ◀─▶ Human     humans make the strategic call
  │
  ▼
Human ──▶ AI        decision recorded back into org memory for future reuse
```

The full vision — including the Manager-AI pattern, persistent organizational memory, and the governance model — lives in **[docs/vision.md](docs/vision.md)**, along with the open questions we have deliberately *not* hand-waved.

---

## Where DevOrchestrator fits

The vision is a multi-year direction. You cannot ship "an AI companion for every role" on day one — so DevOrchestrator starts with the **engineering SDLC loop**, the domain where the payoff is fastest and most measurable.

DevOrchestrator is the vision, scoped to one role (the developer) and one workflow (task → deployed code):

| Vision concept | DevOrchestrator mechanism | Status |
|---|---|---|
| Every role has an AI companion | Per-developer Claude Code **research + implementation** sessions | ✅ MVP (Sprint 1) |
| Coordinate through shared memory | **Artifact** (the shared spec) + **Context Mesh** (SQLite: who touches what, decisions made) | ✅ MVP (Sprint 3) |
| Escalation model | Quality gates → **TL approval gate**; `--autofix` resolves routine failures before a human sees them | ✅ MVP (Sprint 2) |
| Persistent organizational memory | Mesh events + logged architectural decisions | ✅ MVP (Sprint 3) |
| Bring Your Own Agent | Agent adapter layer (`claude`, then `agy`, then others) | 🟡 MVP-partial (Sprint 4) |
| Per-pod package manager (skills, plugins & shareable workflows) | Manual vendoring today → `devorchestrator skills`/`workflow` versioned, shareable, policy-gated distribution | 🔭 Horizon (post-MVP) |
| Governance / policy engine | Least-privilege access, audit log, policy checks | 🔭 Horizon (post-MVP) |
| Agent-connection **protocol** (the moat) | A documented contract any compliant agent implements to plug in | 🔭 Horizon (post-MVP) |

The last two rows are the parts of the vision with the deepest moat — and they are intentionally **not** in the 4-sprint MVP. They become real work only after the wedge is proven. See the [roadmap](#roadmap-horizons).

---

## How the loop actually runs

```
dev runs: devorchestrator start

[1]  Config loads         devOrchestrator.yaml → board, git, agent, role
[2]  Task fetch           Plane / Azure Boards REST API → tasks in terminal
[3]  Dev selects task     ← HUMAN
[4]  Branch created       git server API → feature/task-slug
[5]  Research session     tmux pane: claude -p reads codebase → writes artifact.md
[6]  Artifact preview     rendered in terminal   ← OPTIONAL HUMAN GATE (edit before impl)
[7]  Impl session         tmux pane: claude -p implements the artifact, dev watches live
[8]  Dev reviews          ← HUMAN
[9]  dev runs: devorchestrator pr
[10] Auto-checks          ruff + gitleaks + pytest;  FAIL → --autofix re-invokes agent
[11] PR created           AI-written description → PR opened, linked to task
[12] TL notified          Mattermost
[13] TL runs: devorchestrator review   → diff | tests | CI | artifact → [a]pprove / [r]eject
[14] CI/CD fires          Woodpecker CI / Azure Pipelines
[15] Deploy               Coolify webhook → health check until green
[16] Task closed          board API → Done → team notified
```

**Human moments: [3] pick task, [6] optionally edit artifact, [8] review implementation.** Everything else is the machine.

### The coordination substrate: artifact + mesh

Two ideas do the load-bearing work, and they are why DevOrchestrator's coordination is trustworthy where "agents chatting" is not:

- **The Artifact** — a structured Markdown spec (context, sub-tasks, files to touch, acceptance criteria) produced by a research session that actually reads the codebase, then handed to the implementation session. It is the shared contract between "what we decided" and "what got built."
- **The Mesh** — a small SQLite event store (WAL mode) that records who is touching which module and what architectural decisions were made. It is the concrete, queryable form of "persistent organizational memory," and the basis for conflict detection between developers.

---

## Design stance — what we deliberately do *not* do

The vision is ambitious; the build stays honest. These non-goals keep the MVP shippable and the coordination reliable:

- **No unsupervised agent-to-agent negotiation of contracts.** Two non-deterministic agents "negotiating an API" unsupervised is two hallucination surfaces talking. We coordinate through the **shared artifact + mesh** and a **human gate**, not improvised chat.
- **Organizational memory needs provenance, not just capture.** A logged resolution is only useful if it carries who/when and can be superseded — stale decisions cited with confidence are worse than no memory. Memory entries are treated as facts-at-a-time, not eternal truth.
- **No monolith.** DevOrchestrator triggers CI/CD and project tooling; it does not reimplement them. Plane owns project management, Woodpecker owns pipelines, the orchestrator owns the *loop*.
- **CLI, not an IDE plugin.** The terminal (with a live tmux pane the dev can watch and interrupt) is the right surface.

Full critique and open questions: **[docs/vision.md](docs/vision.md#open-questions)**.

---

## Roadmap horizons

| Horizon | Scope | Where it's tracked |
|---|---|---|
| **H0 — Inner loop** | Task → research → artifact → implement, for one dev | [Sprint 1](docs/sprint-1.md) |
| **H0 — Pipeline** | Quality gates → autofix → PR → TL approval | [Sprint 2](docs/sprint-2.md) |
| **H1 — Team** | Deploy + notify + shared context mesh + one-command infra | [Sprint 3](docs/sprint-3.md) |
| **H1 — Scale** | Rate-limit rotation, BYO-agent (`agy`), Azure DevOps track | [Sprint 4](docs/sprint-4.md) |
| **H2 — Multi-role companions** | Companions beyond the developer: Manager AI, QA AI, DevOps AI | [product-backlog.md](docs/product-backlog.md) · [vision.md](docs/vision.md) |
| **H3 — Enterprise platform** | **Governance/policy engine** + **agent-connection protocol** (the moat) + **per-pod package manager for skills/plugins/shareable workflows** | [product-backlog.md](docs/product-backlog.md) · [vision.md](docs/vision.md) |

H0–H1 are the current 4-sprint MVP. H2–H3 are the vision made concrete as future epics — real, but explicitly not MVP.

---

## Quickstart

DevOrchestrator runs on a **Claude Code Pro subscription — no API key required**. It invokes the `claude` CLI as a subprocess in a visible tmux pane.

**Team lead, once:**
```bash
docker compose up -d          # Plane + Gitea + Woodpecker CI + Coolify + Mattermost
# commit devOrchestrator.yaml.template with shared URLs pre-filled
```

**Each dev, once:**
```bash
uvx install devorchestrator                     # or: pip install devorchestrator
cp devOrchestrator.yaml.template devOrchestrator.yaml
# fill in: name, role, agent — set token env vars in .env
devorchestrator init                            # tests connections, registers in the mesh
```

**Every task:**
```bash
devorchestrator start         # pick a task, watch the loop run
devorchestrator pr            # checks → PR
devorchestrator review        # (TL) approve / reject
```

Minimal config:
```yaml
name: yuvaraj
role: dev                     # or: tl
agent: claude                 # BYO agent — claude today, agy/others next

board:  { type: plane,  url: https://plane.team.internal,  token_env: PLANE_API_KEY }
git:    { type: gitea,  url: https://gitea.team.internal,  token_env: GITEA_TOKEN }
brain:  { provider: openrouter, model: deepseek/deepseek-v4-flash, token_env: OPENROUTER_API_KEY }
notify: { type: mattermost, webhook_env: MATTERMOST_WEBHOOK }
```

---

## Documentation

| Doc | What's in it |
|---|---|
| **[docs/vision.md](docs/vision.md)** | The complete AI-Native Enterprise vision, the design stance, and open questions |
| **[docs/TEAM-WORKFLOW.md](docs/TEAM-WORKFLOW.md)** | 18h hackathon: 4 conflict-free lanes, wave timeline, git flow, vendored skills |
| **[docs/spine.md](docs/spine.md)** | Lane A full reference: every `contracts.py` type/Protocol, `pipeline.py`/`review.py` walkthroughs, adapter skeletons to copy-paste, testing patterns, troubleshooting |
| [docs/research.md](docs/research.md) | Problem, pipeline detail, competitive landscape, tech decisions, risks |
| [docs/product-backlog.md](docs/product-backlog.md) | Ordered backlog: MVP epics + H2/H3 vision epics |
| [docs/sprints.md](docs/sprints.md) | 4-sprint MVP overview and vision horizons |
| [docs/sprint-1.md](docs/sprint-1.md) … [sprint-4.md](docs/sprint-4.md) | Per-sprint backlog, DoD, and vision alignment |
| [docs/board.md](docs/board.md) | Live task board |

---

## Status

Planning complete; MVP (H0–H1) is a 4-sprint, ~37-point build. The [product backlog](docs/product-backlog.md) now also carries the H2–H3 vision epics so the north-star is never lost — while the MVP stays deliberately small.

## Tech stack

Python 3.12 · Pydantic v2 · `claude` CLI (Pro, no API key) · libtmux · Rich · httpx · SQLite (WAL) · gitleaks · uv. Full rationale in [docs/research.md](docs/research.md#tech-recommendations).
