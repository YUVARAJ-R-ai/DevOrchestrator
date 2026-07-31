"""FastMCP stdio server wiring the Supabase mesh into any Claude Code session.

The mesh is Lane D's shared source of truth. Today only ``devorchestrator``-spawned
pipelines write to it; this server lets *any* Claude Code session (Bring-Your-Own-
Agent) read and write it through MCP tools.

Two layers:
- :class:`MeshTools` — plain handlers over an injected mesh. Unit-tested directly
  with a mock Supabase client; no MCP machinery needed.
- :func:`build_mcp` — registers those handlers on a :class:`FastMCP` server
  (FastMCP derives each tool's input schema from the handler signature).
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from devorchestrator.contracts import Mesh
from devorchestrator.mesh.store import SupabaseMesh, create_supabase_client


class MeshTools:
    """The MCP tool set, as plain methods over an injected mesh.

    Writes carry ``dev`` (from the config's ``name``) so the mesh knows who logged
    them. Reads degrade exactly like the mesh itself — ``[]`` on any backend error.
    """

    def __init__(self, mesh: Mesh, *, dev: str = "unknown") -> None:
        self._mesh = mesh
        self._dev = dev

    def log_decision(self, description: str, module: str) -> str:
        """Log an architectural decision to the shared mesh."""
        self._mesh.emit("decision", module, {
            "dev": self._dev,
            "description": description,
            "modules": [module],
        })
        return f"Decision logged: {description}"

    def log_session_event(self, kind: str, branch: str, payload: dict | None = None) -> str:
        """Record a session lifecycle event (research/impl/autofix) on a branch."""
        self._mesh.emit(f"session:{kind}", branch, {
            "dev": self._dev,
            "kind": kind,
            "branch": branch,
            **(payload or {}),
        })
        return f"Session event logged: {kind} on {branch}"

    def who_is_touching(self, module: str) -> list[dict[str, Any]]:
        """Who is currently active on a module, newest first."""
        return [_as_dict(a) for a in self._mesh.who_is_touching(module)]

    def active_sessions(self) -> list[dict[str, Any]]:
        """Sessions running right now (fresh heartbeat within 60s)."""
        return [_as_dict(a) for a in self._mesh.active_sessions()]  # type: ignore[attr-defined]

    def recent_decisions(self, limit: int = 10) -> list[dict[str, Any]]:
        """The most recent architectural decisions logged to the mesh."""
        return [_as_dict(d) for d in self._mesh.recent_decisions(limit)]


def build_mcp(tools: MeshTools) -> FastMCP:
    """Register every :class:`MeshTools` handler as an MCP tool."""
    mcp = FastMCP("devorchestrator-mesh")
    mcp.add_tool(tools.log_decision)
    mcp.add_tool(tools.log_session_event)
    mcp.add_tool(tools.who_is_touching)
    mcp.add_tool(tools.active_sessions)
    mcp.add_tool(tools.recent_decisions)
    return mcp


def build_server_from_config(
    directory: str | Path | None = None, *, check_env: bool = False
) -> FastMCP:
    """Build the stdio server from a ``devOrchestrator.yaml`` config.

    Only the ``mesh`` section is required — the MCP server must keep working for a
    teammate who runs Claude Code directly without a board/git setup.
    """
    from devorchestrator.config import ConfigError, load_config

    config = load_config(directory, check_env=check_env)
    if not config.mesh.supabase_url:
        raise ConfigError(
            "mesh.supabase_url is not configured — the MCP server needs the mesh.",
            hint="set mesh.supabase_url + mesh.supabase_key_env in devOrchestrator.yaml",
        )
    key = os.environ.get(config.mesh.supabase_key_env, "")
    if not key:
        raise ConfigError(
            f"${config.mesh.supabase_key_env} is not set.",
            hint="export it in .env (the CLI loads it there too)",
        )
    mesh = SupabaseMesh(create_supabase_client(config.mesh.supabase_url, key))
    return build_mcp(MeshTools(mesh, dev=config.name))


def main() -> None:
    """Console-script entry point: build from config and run the stdio server.

    All diagnostics go to stderr — stdout is the MCP protocol channel."""
    try:
        server = build_server_from_config()
    except Exception as exc:  # noqa: BLE001 — report cleanly, then exit
        print(f"devorchestrator-mcp: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    server.run(transport="stdio")


def _as_dict(obj: Any) -> dict[str, Any]:
    """Serialize a frozen mesh value object (Decision/DevActivity/SessionActivity)."""
    if is_dataclass(obj):
        return asdict(obj)  # type: ignore[arg-type]
    return dict(obj)


__all__ = ["MeshTools", "build_mcp", "build_server_from_config", "main"]
