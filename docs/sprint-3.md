# Sprint 3 — Full Pipeline + Team Infrastructure
**Jun 22–26, 2026 · 9/10 pts · Solo dev (Claude Code)**

---

## MVP Definition
The pipeline is complete end-to-end — merged PR triggers deploy, task is auto-closed on Plane, team is notified on Mattermost. The shared infra stack (Plane + Gitea + Woodpecker + Coolify + Mattermost) spins up with one command. The shared context mesh is live — every developer's orchestrator reads and writes to it, so the team sees who is touching what and architectural decisions are visible to all. **The tool is ready for a 4-dev team to use.**

```
After merge (auto-triggered):
  → Coolify webhook fires → health check polls until green
  → Plane task moved to Done
  → Mattermost: "Shipped: {task title} by {dev} — {deploy URL}"

Team context (always running):
  → Dev A starts task touching auth/ → mesh records it
  → Dev B starts task → "⚠ alice is in auth/ (feature/jwt-refresh)"
  → TL runs `devorchestrator mesh` → sees full team activity

Setup (new team member, one-time):
  → docker compose up -d       ← full OSS stack
  → devorchestrator init       ← test connections, register in mesh
```

---

## Sprint Backlog

### Deploy + Notify
- [ ] **(M) #32** — Coolify webhook trigger + health check poller
  - `POST {coolify.webhook_url}` on merge event (triggered by Gitea webhook → orchestrator endpoint, or TL approve handler)
  - Polls `GET /api/v1/applications/{id}/status` every 5s until `status == "running"` or timeout (120s)
  - On success: prints deploy URL
- [ ] **(S) #33** — Task-close API call (Plane)
  - `PATCH /api/v1/workspaces/{slug}/projects/{id}/issues/{issue_id}/`
  - Body: `{"state": "<done-state-id>"}`
  - Triggered after health check passes
  - Depends on: #32
- [ ] **(S) #34** — Mattermost webhook notification
  - `POST {notify.webhook_url}` with JSON body
  - Message: "✅ Shipped: **{task title}** by {dev_name} — {deploy_url} | {pr_url}"
  - Also used by [r] reject handler in Sprint 2 for DM notifications

### Shared Infrastructure
- [ ] **(L) #3** — Docker Compose stack
  - Services: `plane`, `gitea`, `woodpecker-server`, `woodpecker-agent`, `coolify`, `mattermost`
  - All connected via internal Docker network
  - Volumes for persistence: `plane-data`, `gitea-data`, `woodpecker-data`, `coolify-data`, `mattermost-data`
  - Tailscale sidecar for remote access from team
  - `.env.compose` for all service credentials (gitea admin password, plane secret key, etc.)
  - Readme section: how to get tokens from each service after first boot
- [ ] **(S) #2** — devOrchestrator.yaml.template
  - All shared infra URLs pre-filled (team lead fills these in after `docker compose up`)
  - Personal fields clearly marked with `# FILL IN` comments: `name`, `role`, `agent`
  - Env var names listed for each `token_env` field
- [ ] **(M) #4** — `devorchestrator init` command
  - Tests each connection in sequence: Plane → Gitea → Mattermost → Coolify → DeepSeek
  - Shows ✅/❌ per service with error hints on failure
  - On success: registers dev in mesh (`INSERT OR REPLACE INTO devs`)
  - Creates `.orchestrator/` directory structure

### Shared Context Mesh
- [ ] **(S) #36** — SQLite mesh schema + init
  - Tables: `events(id, dev, module, event_type, payload JSON, ts)`, `devs(name, role, last_seen)`
  - WAL mode enabled at init
  - DB path: `{shared_server_path}/mesh.db` (configurable in `devOrchestrator.yaml` as `mesh.db_path`)
  - Accessed over Tailscale network mount or SSH — same SQLite file, WAL handles concurrent writes
- [ ] **(M) #37** — Mesh writer
  - `mesh.emit(event_type, module, payload)` called at key pipeline moments:
    - `task_started`: `{task_id, task_title, branch}`
    - `artifact_generated`: `{branch, artifact_path, modules_affected}`
    - `pr_opened`: `{branch, pr_url}`
    - `decision_made`: `{description, affected_modules}` (dev can log manually via `devorchestrator decision "switched JWT to session-based"`)
  - Depends on: #36
- [ ] **(S) #38** — Mesh reader
  - `mesh.who_is_touching(module: str) -> list[DevActivity]`
  - `mesh.recent_decisions(limit=10) -> list[Decision]`
  - `mesh.team_status() -> list[DevStatus]` (what each dev is working on right now)
  - Depends on: #37
- [ ] **(M) #39** — Conflict detector
  - Called at branch creation step (Sprint 1 #11): checks `who_is_touching()` for modules in the new task description
  - If overlap found: prints warning with dev name, branch, time started
  - Not a block — prints warning, asks "Continue? [y/n]"
  - `devorchestrator mesh` command: shows full team activity table (Rich)
  - Depends on: #38

---

## Definition of Done
- [ ] After TL approves a PR: Coolify deploys, Plane task closes, Mattermost notifies — automatically
- [ ] `docker compose up -d` in the repo root brings up the full OSS stack
- [ ] A new dev can onboard by: copying `devOrchestrator.yaml.template` + setting 3 env vars + running `devorchestrator init`
- [ ] Dev A starting a task that overlaps with Dev B's active modules shows a warning
- [ ] `devorchestrator mesh` shows a live table of what the whole team is doing
- [ ] `devorchestrator decision "message"` logs an architectural decision visible to all co-pilots

## Carry-over Risk
- Docker Compose (#3) is L but mostly config — the risk is first-boot service wiring (Woodpecker ↔ Gitea OAuth, Coolify webhook setup). Document these steps in the compose README rather than automating them in Sprint 3.
