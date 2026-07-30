# Product Backlog: DevOrchestrator
_Generated: 2026-06-05 · Vision-aligned: 2026-07-29 | MVP: 36 items · 36 pts + Vision-Horizon epics_

Ordered by delivery priority. Sprint column shows planned sprint. Items without a sprint are unscheduled backlog. **Horizon** rows (H2/H3) realize the [AI-Native Enterprise vision](vision.md) and are deliberately **post-MVP** — they are not scheduled into the 4-sprint MVP and exist so the north star is never lost. See [horizon epics](#vision-horizon-epics-post-mvp) below.

---

## Epics

| # | Epic | Sprint | Size | Description |
|---|------|--------|------|-------------|
| **INFRA** | **Project Setup** | | | |
| 1 | Project scaffold (uv init, pyproject.toml, `devorchestrator` CLI entry point) | S1 | M | |
| 2 | devOrchestrator.yaml.template (team-shareable, all shared URLs pre-filled) | S3 | S | |
| 3 | Docker Compose: Plane + Gitea + Woodpecker CI + Coolify + Mattermost | S3 | L | |
| 4 | `devorchestrator init` command (test all connections, register dev in mesh) | S3 | M | |
| **CONFIG** | **Configuration Layer** | | | |
| 5 | Pydantic v2 schema for devOrchestrator.yaml | S1 | S | |
| 6 | Config loader with track auto-detection (oss vs azure from URLs) | S1 | S | |
| 7 | Validation errors with fix hints (fail loud at startup, not mid-run) | S1 | S | |
| **BOARD** | **Task Board Integration** | | | |
| 8 | Plane REST API client (fetch sprint tasks by assignee + state filter) | S1 | M | |
| 9 | Rich terminal task selector (arrow-key, shows title + priority + estimate) | S1 | S | dep: 8 |
| 10 | Azure Boards REST client (query work items by sprint iteration) | S4 | M | |
| **GIT** | **Git Server Integration** | | | |
| 11 | Gitea API client: create branch from task slug | S1 | M | |
| 12 | Azure Repos API: create branch | S4 | M | |
| **RESEARCH** | **Research Session** | | | |
| 13 | Design + document artifact.md schema (sub-tasks, files, criteria, notes) | S1 | S | |
| 14 | Research prompt template (task description → codebase read → artifact.md) | S1 | M | |
| 15 | libtmux pane spawner for research session (named: research-[branch]) | S1 | M | dep: 14 |
| 16 | Artifact.md file watcher (detect when research session writes file) | S1 | S | dep: 15 |
| 17 | Artifact Rich renderer (preview artifact in terminal before impl fires) | S1 | S | dep: 16 |
| **IMPL** | **Implementation Session** | | | |
| 18 | Implementation prompt template ("implement artifact at [path]") | S1 | S | |
| 19 | libtmux pane spawner for implementation session (named: impl-[branch]) | S1 | M | dep: 16 |
| 20 | Pane monitor (detect session exit, surface exit status to orchestrator) | S1 | S | dep: 19 |
| 21 | agy invocation adapter (alongside claude) | S4 | M | |
| **CHECKS** | **Auto-checks** | | | |
| 22 | Check runner: ruff + gitleaks + pytest as subprocesses, structured results | S2 | M | |
| 23 | Rich pass/fail result panel | S2 | S | dep: 22 |
| 24 | --autofix flag: re-invoke impl session with failure + artifact context | S2 | M | dep: 19, 22 |
| **PR** | **PR Automation** | | | |
| 25 | DeepSeek V4 Flash client (AsyncOpenAI, OpenRouter base_url) | S2 | S | |
| 26 | PR description generator (git log + artifact → DeepSeek → description) | S2 | M | dep: 25 |
| 27 | Gitea PR creation: open PR, link task card, assign TL reviewer | S2 | M | dep: 26 |
| 28 | Azure Repos PR creation API | S4 | M | |
| **TL** | **TL Approval Gate** | | | |
| 29 | Rich TL view: diff pane + test summary + artifact + CI status | S2 | L | |
| 30 | [a] approve handler: merge API + branch delete | S2 | M | dep: 29 |
| 31 | [r] reject handler: PR comment + Mattermost ping to dev | S2 | S | dep: 29 |
| **DEPLOY** | **Deploy + Notify** | | | |
| 32 | Coolify webhook trigger + health check poller | S3 | M | |
| 33 | Task-close API call (Plane) after deploy success | S3 | S | dep: 32 |
| 34 | Mattermost webhook notification | S3 | S | |
| 35 | Teams webhook notification adapter | S4 | S | |
| **MESH** | **Shared Context Mesh** | | | |
| 36 | SQLite mesh schema: events(dev, module, event_type, payload, ts) + WAL mode | S3 | S | |
| 37 | Mesh writer: emit on branch-create, artifact-generated, decisions | S3 | M | dep: 36 |
| 38 | Mesh reader: who_is_touching(module), recent_decisions() | S3 | S | dep: 37 |
| 39 | Conflict detector: warn on module overlap at task-start | S3 | M | dep: 38 |
| **ROTATION** | **Account Rotation** | | | |
| 40 | tmux session pool manager (N sessions, named by account) | S4 | L | |
| 41 | Rate-limit detector (parse claude stderr for limit signals) | S4 | M | dep: 40 |
| 42 | Round-robin router (skip sessions in cooldown) | S4 | M | dep: 41 |
| 43 | Integrate rotation into tmux agent spawner | S4 | S | dep: 42 |

---

## Unscheduled Backlog

- [ ] Research framework v1 (web search + codebase graph, upgrade from file scan)
- [ ] Metrics dashboard (cycle time, velocity, AI vs human time ratio)
- [ ] Web TL dashboard (mesh overview, PR queue visual)
- [ ] Git worktree isolation per agent (parallel task safety)
- [ ] DeepSeek chatbot interface (conversational layer over mesh + board data)
- [ ] Headless mode (no tmux, fully non-interactive for CI environments)
- [ ] Codex invocation adapter

---

## Vision-Horizon Epics (post-MVP)

These realize the [AI-Native Enterprise vision](vision.md). They are **not scheduled into the MVP** — each starts only after the H0–H1 wedge is proven. Sized coarsely (T-shirt) because they will be broken down when picked up. Coordination stays through the **shared artifact + mesh + human gate**, never unsupervised agent negotiation ([why](vision.md#open-questions)).

### Horizon H2 — Multi-role companions
Extend the companion + escalation pattern beyond the developer, reusing the artifact + mesh substrate.

| # | Epic | Size | Notes |
|---|------|------|-------|
| H2-1 | **Manager AI** companion: answers Developer-AI clarifications from project state / priorities / prior decisions before interrupting the human; escalates with full context | XL | dep: mesh (#36–39) |
| H2-2 | Developer-AI → Manager-AI escalation channel (structured, logged, context-preserving) | L | dep: H2-1 |
| H2-3 | **QA AI** companion: consumes artifact + diff, proposes test coverage, flags acceptance-criteria gaps | L | dep: artifact schema (#13) |
| H2-4 | **DevOps AI** companion: owns deploy/health/rollback signals, escalates infra decisions | L | dep: deploy (#32) |
| H2-5 | Org-scale cost/rate-limit modeling (companion-for-everyone economics) | M | builds on rotation (#40–43) |

### Horizon H3 — Enterprise platform
The deepest-moat pillars: the company owns the **protocol and policies, not the model**.

| # | Epic | Size | Notes |
|---|------|------|-------|
| H3-1 | **Governance / policy engine**: least-privilege read-only access to source-of-truth, enforced centrally (e.g. OPA) | XL | first-class adoption gate |
| H3-2 | Access request → policy-based approval → **immutable audit trail** flow | L | dep: H3-1 |
| H3-3 | Per-role policy templates (dev / TL / manager / QA / devops) | M | dep: H3-1 |
| H3-4 | **Agent-connection protocol** spec: auth, scoped source-of-truth read, artifact I/O, mesh emit/read, escalation hooks | XL | the moat; incubated by #21 (`agy` adapter) |
| H3-5 | Protocol conformance suite (any BYO agent can self-certify) | L | dep: H3-4 |
| H3-6 | Organizational-memory trust layer: provenance, supersession/expiry, confidence, staleness detection | L | hardens mesh into durable org memory |
| H3-7 | **Per-pod package manager** for skills, plugins & workflows: `add/publish/pin/upgrade/rollback` with semver | XL | productizes manual vendoring; capability travels with the pod |
| H3-8 | Policy-gated distribution: signed provenance + audited installs (skills/workflows are executable capability = permission surface) | L | dep: H3-1, H3-7 |
| H3-9 | Org-level index: cross-pod discovery & adoption at chosen versions | M | dep: H3-7 |
| H3-10 | **Shareable workflows**: declarative recipe (chained skills/agents/gates/escalation) + `devorchestrator workflow share/install` | L | dep: H3-7; a pod's proven pipeline → one command for the team |
