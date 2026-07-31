"""MCP server exposing the DevOrchestrator mesh as tools (issue #58).

Run it in stdio mode and register it in Claude Code's ``.mcp.json`` so *any*
Claude Code session — not just ``devorchestrator start`` pipelines — can read
and write the shared mesh. See docs/MCP.md for the setup snippet.

Entry points:
- ``devorchestrator-mcp`` (console script) / ``python -m devorchestrator.mcp``
"""

from __future__ import annotations

from devorchestrator.mcp.server import (
    MeshTools,
    build_mcp,
    build_server_from_config,
    main,
)

__all__ = ["MeshTools", "build_mcp", "build_server_from_config", "main"]
