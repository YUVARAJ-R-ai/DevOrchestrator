# Product Backlog: DevOrchestrator
_Generated: 2026-06-05 | Total: 36 items · 36 pts_

Ordered by delivery priority. Sprint column shows planned sprint. Items without a sprint are unscheduled backlog.

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
