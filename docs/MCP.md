# DevOrchestrator MCP server

Exposes the DevOrchestrator **mesh** (Lane D's shared source of truth) as MCP tools,
so *any* Claude Code session — including one started with a plain `claude` command,
not `devorchestrator start` — can read and write team activity. This is the
Bring-Your-Own-Agent goal: every agent becomes a tracked participant.

## What it exposes

| Tool | What it does |
|------|--------------|
| `log_decision(description, module)` | Log an architectural decision to the mesh |
| `log_session_event(kind, branch, payload)` | Record a session lifecycle event (research/impl/autofix) on a branch |
| `who_is_touching(module)` | Who is currently active on a module, newest first |
| `active_sessions()` | Sessions running right now (fresh heartbeat within 60s) |
| `recent_decisions(limit)` | The most recent architectural decisions |

All tools talk to the same Supabase mesh (`events` / `devs` / `sessions` tables) as
the rest of the codebase. Reads degrade to `[]` on any backend error, exactly like
the mesh itself — the server never breaks your session.

## Setup

The server needs the same mesh config as the CLI: a `devOrchestrator.yaml` with
`mesh.supabase_url` + `mesh.supabase_key_env`, and the service key exported in
`.env` (see `devOrchestrator.yaml.template` / `devorchestrator init`).

### 1. Register it in Claude Code

Add a `.mcp.json` to your project root (or merge into your user-level config):

```json
{
  "mcpServers": {
    "devorchestrator-mesh": {
      "command": "uv",
      "args": ["run", "devorchestrator-mcp"]
    }
  }
}
```

> Run from the repo root (`uv run` picks up the project environment). If the
> package isn't installed, `uv run --with devorchestrator devorchestrator-mcp`
> works from anywhere.

### 2. Run it manually (sanity check)

```bash
uv run devorchestrator-mcp
# or
uv run python -m devorchestrator.mcp
```

The server speaks MCP over stdio — it won't print anything while idle. In Claude
Code, `/mcp` shows the registered server and its tools.

## How it works

- `src/devorchestrator/mcp/server.py` — `MeshTools` (plain handlers over an
  injected mesh) + `build_mcp()` (registers them on a `FastMCP` stdio server).
- Writes carry the config's `name` as `dev`, so activity is attributed correctly.
- `log_session_event` currently records events in the `events` table. Writing the
  derived `sessions`-table state (so MCP-logged sessions also show in
  `active_sessions()`) is the session-emit issue's job.
