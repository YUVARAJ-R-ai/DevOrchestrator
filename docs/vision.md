# Vision: The AI-Native Enterprise
_DevOrchestrator is the first buildable slice of this vision. This document is the north star; the [product backlog](product-backlog.md) and [sprints](sprints.md) are the road._

---

## Vision

Instead of viewing AI as just another tool, we treat **every employee as having a mandatory AI companion**. Every human role in the organization has a corresponding AI agent that understands its owner's work, context, responsibilities, and company policies.

The AI is not meant to replace the human. The human and AI function as a **team**:

- **AI** performs repetitive, implementation-heavy, and operational work.
- **Humans** focus on system design, critical thinking, decision making, validation, documentation, and creative problem solving.

---

## Motivation

Current organizations suffer from several problems:

- Tribal knowledge exists only inside people's heads.
- Human-to-human communication loses context over time.
- Text conversations are often ambiguous and misinterpreted.
- A large amount of engineering time is spent on operational coordination rather than actual problem solving.
- Knowledge transfer becomes difficult whenever people switch teams or leave the company.

This vision reduces these issues by making AI the **primary operational layer** while humans remain responsible for strategic decisions.

---

## Core principle

**Every employee has an AI companion.**

- Manager ↔ Manager AI
- Frontend Developer ↔ Frontend AI
- Backend Developer ↔ Backend AI
- QA Engineer ↔ QA AI
- DevOps Engineer ↔ DevOps AI

The companion continuously understands the employee's work, context, responsibilities, and ongoing tasks.

### Human responsibilities
Architecture · system design · product decisions · reviewing AI-generated work · approving important decisions · handling complex edge cases · creative problem solving.

### AI responsibilities
Coding · boilerplate generation · routine implementation · documentation · task coordination · information gathering · progress tracking · communication assistance · maintaining project context.

---

## Bring Your Own Agent

The company should not force employees onto a specific coding assistant or IDE. Employees stay free to use Claude Code, OpenCode, GitHub Copilot, Cursor, Windsurf, or any future coding agent.

The enterprise platform provides a **standard protocol** that any compatible agent can connect to. **The company provides governance, not the assistant itself.**

> This is the actual product thesis and the deepest moat: the enterprise owns the **protocol and policies**, not the AI model. It is intentionally a **Horizon (H3)** deliverable — see [DevOrchestrator alignment](#how-devorchestrator-realizes-this-vision).

---

## AI-to-AI communication (done through shared memory)

Instead of every engineer coordinating manually, their AI companions coordinate first — e.g. Frontend AI and Backend AI synchronizing on an API. Whenever something is resolved, the **resolution is logged, the reasoning is preserved, and future agents reuse it.** This gradually builds organizational memory instead of tribal knowledge.

**How we actually implement it — and why it matters:** we do **not** rely on two non-deterministic agents improvising an API contract at each other unsupervised. Coordination happens through a **shared structured substrate**:

- **The Artifact** — a structured spec, produced by an agent that reads the real codebase, that both sides work against.
- **The Mesh** — a queryable event store of who-touches-what and decisions-made.

Agents read and write facts; humans gate the important ones. This is the trustworthy form of "AI-to-AI communication." (See [Open questions](#open-questions).)

---

## Escalation model

Not every problem should reach humans.

```
AI ──▶ AI          routine issues resolved automatically; resolution + reasoning logged
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

---

## Manager AI

Managers also have companions. A developer needing clarification does not immediately interrupt the manager — instead **Developer AI → Manager AI**. The Manager AI understands current project state, team priorities, existing discussions, and prior architectural decisions. If it can answer, it does; if not, it escalates to the human manager **with complete context** rather than fragmented chat. This reduces communication overhead while preserving intent.

---

## Persistent organizational memory

Today, conversations disappear into chat messages, meetings, and personal memory. In this architecture, **every important interaction becomes structured organizational knowledge** — the *context behind decisions* is preserved, not just the final outcome. This creates long-term memory for both humans and agents.

> **Design requirement (not optional):** memory must carry **provenance** (who, when), **supersession/expiry**, and a **confidence signal**. A logged resolution cited with confidence after it has gone stale is worse than no memory at all. We treat memory entries as facts-at-a-time, not eternal truth. See [Open questions](#open-questions).

---

## Security and governance

Every connected AI agent receives access only to information it is authorized to use. A **central policy engine** (e.g. Open Policy Agent) enforces permissions:

- Agents get **read-only** access to the organization's source of truth.
- Information outside an agent's scope **cannot** be accessed automatically — it must be **requested**, approved per company policy, and **logged and audited**.

This ensures strong separation between teams while still allowing controlled collaboration. Governance is a **first-class Horizon (H3) pillar**, not an afterthought — it is what determines whether any enterprise can adopt the platform.

---

## Guiding philosophy

The platform is **loosely coupled**. Instead of one monolithic AI system, we provide a common communication protocol, standard interfaces, security policies, organizational memory, and governance. Any compliant AI agent can participate. **The enterprise owns the protocol and policies — not the AI model.**

---

## High-level workflow

1. Human defines goals.
2. AI performs implementation.
3. AI agents coordinate with other AI agents (through shared memory).
4. Routine issues are solved automatically.
5. Difficult problems escalate to humans — with full context.
6. Human decisions are recorded back into the system.
7. Organizational knowledge continuously grows and becomes reusable.

---

## How DevOrchestrator realizes this vision

The vision spans multiple years and roles. DevOrchestrator makes it real by scoping it to **one role (the developer)** and **one workflow (task → deployed code)** — the domain with the fastest, most measurable payoff — then expanding outward.

| Vision concept | DevOrchestrator mechanism | Horizon |
|---|---|---|
| Every role has an AI companion | Per-developer Claude Code research + implementation sessions | H0 · [Sprint 1](sprint-1.md) |
| AI-to-AI communication via shared memory | Artifact (shared spec) + Context Mesh (who-touches-what, decisions) | H1 · [Sprint 3](sprint-3.md) |
| Escalation model | Quality gates + `--autofix` (AI→AI) → TL approval gate (AI→Human) | H0 · [Sprint 2](sprint-2.md) |
| Persistent organizational memory | Mesh events + `devorchestrator decision "…"` | H1 · [Sprint 3](sprint-3.md) |
| Bring Your Own Agent | Agent adapter layer: `claude` → `agy` → others | H1 · [Sprint 4](sprint-4.md) |
| **Governance / policy engine** | Least-privilege access, request/approve/audit flow | **H3** · [backlog](product-backlog.md#horizon-h3--enterprise-platform) |
| **Agent-connection protocol** (the moat) | Documented contract any compliant agent implements | **H3** · [backlog](product-backlog.md#horizon-h3--enterprise-platform) |
| Multi-role companions (Manager/QA/DevOps AI) | Companion + escalation patterns beyond the developer | **H2** · [backlog](product-backlog.md#horizon-h2--multi-role-companions) |

**H0–H1 = the current 4-sprint MVP. H2–H3 = the vision as concrete future epics.** The MVP stays deliberately small so the wedge ships; the horizons keep the north star from being lost.

---

## Open questions

Honest gaps we are choosing to name rather than hand-wave. These gate the H2–H3 horizons.

1. **Agent-to-agent contract negotiation.** Unsupervised negotiation between two non-deterministic agents is unreliable. **Stance:** coordinate through shared artifact + mesh + a human gate; never treat improvised agent chat as authoritative. Revisit only with a verification/testing layer that makes a negotiated contract checkable.
2. **Memory trust & decay.** "Log every resolution" assumes resolutions stay correct. **Stance:** every memory entry carries provenance, supersession, and confidence; memory is facts-at-a-time. Open: automatic staleness detection and conflict resolution between contradictory memories.
3. **Governance depth.** OPA is named but not designed. **Stance:** governance is a first-class H3 epic (permission model, request/approve flow, audit trail), not a paragraph. Open: default policy templates per role.
4. **The protocol.** "Any compliant agent connects" is the moat but underspecified. **Stance:** define the minimal contract a BYO agent must implement (auth, scoped read of source-of-truth, artifact I/O, mesh events, escalation hooks) as an H3 deliverable, incubated by the `claude`→`agy` adapter work in H1.
5. **Economics at scale.** "Mandatory companion for everyone" has real rate-limit/cost implications. **Stance:** MVP confronts this via account rotation ([Sprint 4](sprint-4.md)); org-scale cost modeling is an H2 question.
6. **Human incentives.** "Mandatory AI companion" invites quiet resistance. **Stance:** design for opt-in value (zero-config, one command, watchable live) so adoption is pulled, not pushed; do not mandate what the workflow can earn.

---

## Long-term goal

Shift organizations from primarily human-to-human operational communication to **AI-mediated collaboration**, where humans focus on high-value thinking while AI handles execution, coordination, and knowledge preservation. The objective is **not to replace employees** but to augment every employee with an intelligent, policy-aware AI companion that improves productivity, reduces communication overhead, and preserves organizational knowledge.
