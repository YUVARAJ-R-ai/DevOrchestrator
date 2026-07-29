# Sprint 4 — Scale, Resilience + Azure Track
**Jun 29 – Jul 3, 2026 · 9/10 pts · Solo dev (Claude Code)**

---

## MVP Definition
The orchestrator handles rate limits transparently — when one Claude account hits a limit, it silently routes to the next account in the pool, no productivity loss. `agy` is supported alongside `claude` as an agent. The full Azure DevOps track is live — the same `devorchestrator` commands work identically whether the team is on the OSS stack or Azure DevOps, controlled entirely by config. Teams also get a Microsoft Teams notification adapter. **The orchestrator is production-ready for any team, any scale.**

```
Rate limit hit (transparent):
  claude-pro-1 → limit detected in stderr
  → orchestrator silently routes to claude-pro-2
  → impl session continues in new pane, no crash, no lost work

Azure DevOps team:
  board.type: azure_boards
  git.type: azure_repos
  → devorchestrator start   ← identical experience, different backend

agy support:
  agent: agy    ← one config change, same prompts, same tmux pattern
```

---

## Sprint Backlog

### Account Rotation
- [ ] **(L) #40** — tmux session pool manager
  - Config: `rotation.accounts` list in `devOrchestrator.yaml`:
    ```yaml
    rotation:
      accounts:
        - name: claude-pro-1
          agent: claude
        - name: claude-pro-2
          agent: claude
        - name: agy-backup
          agent: agy
    ```
  - Creates one named tmux session per account on `devorchestrator init`
  - Tracks state per session: `active` | `cooldown` | `unavailable`
  - `pool.get_available() -> Session` — returns next non-cooldown session
- [ ] **(M) #41** — Rate-limit detector
  - Monitors pane output in real time (`pane.capture_pane()` polling or `libtmux` hooks)
  - Detects signals: `"rate limit"`, `"429"`, `"usage limit"`, `"quota exceeded"` in stdout/stderr
  - On detection: marks session as `cooldown`, sets `cooldown_until = now + 60min`
  - Depends on: #40
- [ ] **(M) #42** — Round-robin router
  - `router.next_session(task: str) -> Session`
  - Skips sessions in `cooldown` or `unavailable` state
  - Falls back gracefully: if all sessions in cooldown, waits and shows countdown timer
  - Logs rotation events to `.orchestrator/rotation.log`
  - Depends on: #41
- [ ] **(S) #43** — Integrate rotation into tmux agent spawner
  - Replace direct `claude -p` call in research/impl spawners with `router.next_session()` call
  - Spawner receives a `Session` object and sends the command to that session's pane
  - Zero change to existing spawner interface — rotation is transparent
  - Depends on: #42

### agy Support
- [ ] **(M) #21** — agy invocation adapter
  - Abstract base: `AgentAdapter.run(prompt: str, pane: tmux.Pane) -> None`
  - `ClaudeAdapter`: sends `claude -p "{prompt}"` to pane
  - `AgyAdapter`: sends `agy run "{prompt}"` (or equivalent agy CLI syntax) to pane
  - Config `agent: agy` in `devOrchestrator.yaml` routes to `AgyAdapter`
  - Same prompt templates work for both — no prompt changes needed

### Azure DevOps Track
- [ ] **(M) #10** — Azure Boards REST client
  - `GET https://dev.azure.com/{org}/{project}/_apis/wit/wiql` to query work items
  - Filter: assigned to current user, current sprint iteration, state not Done
  - Returns same `list[Issue]` interface as Plane client — pipeline sees no difference
- [ ] **(M) #12** — Azure Repos branch creation
  - `POST https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo}/refs`
  - Branch naming: same `feature/{task-id}-{slug}` convention
  - Returns same interface as Gitea branch client
- [ ] **(M) #28** — Azure Repos PR creation
  - `POST https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo}/pullrequests`
  - Auto-links work item: `workItemRefs: [{id: task_id}]`
  - Assigns required reviewer from config (TL)
  - Returns same PR URL interface as Gitea PR client

### Notifications
- [ ] **(S) #35** — Microsoft Teams webhook notification adapter
  - `POST {notify.webhook_url}` with Teams Adaptive Card payload
  - Same interface as Mattermost adapter — config `notify.type: teams` routes to it
  - Message card: task title, dev name, deploy URL, PR link

---

## Definition of Done
- [ ] Simulating a rate limit (kill claude mid-task) triggers transparent failover to the next account
- [ ] `agent: agy` in config runs agy instead of claude with identical behavior
- [ ] Azure DevOps config works end-to-end: task fetched from Azure Boards → branch on Azure Repos → PR opened and merged → deployed
- [ ] Teams notification fires correctly on task close
- [ ] `devorchestrator status` shows: active sessions, cooldown status, current task per dev, mesh summary

## Carry-over Risk
- Azure DevOps API uses PAT tokens and has nested org/project/repo path requirements — if auth is complex, build the Boards client first (read-only, lower risk) and push Repos + PR to backlog. The adapter pattern means partial Azure support is still useful.
- agy CLI syntax may differ significantly from `claude -p` — verify invocation before building the adapter.
