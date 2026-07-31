"""Tests for the mesh MCP server tool handlers (issue #58).

Handlers are plain methods on ``MeshTools`` backed by an injected mesh, so every
tool is exercised against the same ``MockSupabaseClient`` the mesh store tests use
— no real Supabase, no MCP transport needed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from devorchestrator.config import ConfigError
from devorchestrator.mcp.server import MeshTools, _parse_args, build_mcp, build_server_from_config
from devorchestrator.mesh.store import SupabaseMesh
from tests.conftest import make_config
from tests.mocks import MockSupabaseClient, MockSupabaseTable


def _make_client() -> MockSupabaseClient:
    return MockSupabaseClient()


def _iso(seconds_ago: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()


def _make_tools(client: MockSupabaseClient, dev: str = "tharun") -> MeshTools:
    mesh = SupabaseMesh(client)  # type: ignore[arg-type]
    return MeshTools(mesh, dev=dev)


def test_log_decision_emits_decision_event() -> None:
    client = _make_client()
    tools = _make_tools(client)
    result = tools.log_decision("use supabase", "store.py")

    assert "Decision logged" in result
    rows = client.table("events").inserted
    assert len(rows) == 1
    assert rows[0]["event_type"] == "decision"
    assert rows[0]["module"] == "store.py"
    assert rows[0]["payload"]["dev"] == "tharun"
    assert rows[0]["payload"]["description"] == "use supabase"


def test_log_session_event_merges_payload() -> None:
    client = _make_client()
    tools = _make_tools(client, dev="alice")
    result = tools.log_session_event("impl", "feature/issue-1-x", {"exit_code": 0})

    assert "Session event logged" in result
    rows = client.table("events").inserted
    assert len(rows) == 1
    assert rows[0]["event_type"] == "session:impl"
    assert rows[0]["module"] == "feature/issue-1-x"
    assert rows[0]["payload"]["kind"] == "impl"
    assert rows[0]["payload"]["branch"] == "feature/issue-1-x"
    assert rows[0]["payload"]["dev"] == "alice"
    assert rows[0]["payload"]["exit_code"] == 0


def test_log_session_event_without_payload() -> None:
    client = _make_client()
    tools = _make_tools(client)
    tools.log_session_event("research", "feature/issue-1-x")
    rows = client.table("events").inserted
    assert rows[0]["payload"]["kind"] == "research"
    assert "exit_code" not in rows[0]["payload"]


def test_who_is_touching_serializes_activities() -> None:
    client = _make_client()
    client.tables["events"] = MockSupabaseTable(
        rows=[
            {"project": "", "dev": "alice", "module": "runner.py", "branch": "main",
             "event_type": "check", "ts": "2026-01-01T00:00:00"},
        ]
    )
    tools = _make_tools(client)
    out = json.loads(tools.who_is_touching("runner.py"))
    assert out == [
        {"dev": "alice", "module": "runner.py", "branch": "main",
         "event_type": "check", "ts": "2026-01-01T00:00:00"},
    ]


def test_active_sessions_returns_running_only() -> None:
    client = _make_client()
    client.tables["sessions"] = MockSupabaseTable(
        rows=[
            {"project": "", "dev": "alice", "branch": "feature/x", "kind": "research",
             "state": "running",
             "last_seen": _iso(10), "started_at": _iso(100), "finished_at": None},
            {"project": "", "dev": "bob", "branch": "feature/y", "kind": "impl",
             "state": "completed",
             "last_seen": _iso(20), "started_at": _iso(200),
             "finished_at": _iso(15)},
        ]
    )
    tools = _make_tools(client)
    out = json.loads(tools.active_sessions())
    assert [s["dev"] for s in out] == ["alice"]


def test_recent_decisions_serializes() -> None:
    client = _make_client()
    client.tables["events"] = MockSupabaseTable(
        rows=[
            {"project": "", "dev": "tharun", "event_type": "decision", "module": "store.py",
             "payload": {"description": "use supabase", "modules": ["store.py"]},
             "ts": "2026-01-01T00:00:00"},
        ]
    )
    tools = _make_tools(client)
    out = json.loads(tools.recent_decisions(limit=5))
    assert len(out) == 1
    assert out[0]["description"] == "use supabase"
    assert out[0]["dev"] == "tharun"


def test_tools_degrade_to_empty_on_backend_error() -> None:
    class _BrokenClient:
        def table(self, *_a, **_k):
            raise RuntimeError("Invalid API key")

    tools = MeshTools(SupabaseMesh(_BrokenClient()), dev="tharun")  # type: ignore[arg-type]
    assert tools.who_is_touching("x") == "[]"
    assert tools.active_sessions() == "[]"
    assert tools.recent_decisions() == "[]"


def test_read_tools_return_visible_json_text_even_when_empty() -> None:
    """Regression: FastMCP emits no content block for a bare [], so handlers must
    return JSON text — an empty result must still be visible to the model."""
    tools = _make_tools(_make_client())
    assert tools.who_is_touching("x") == "[]"
    assert tools.active_sessions() == "[]"
    assert tools.recent_decisions() == "[]"


def test_build_mcp_advertises_the_tool_set() -> None:
    import asyncio

    tools = _make_tools(_make_client())
    mcp = build_mcp(tools)
    listed = asyncio.run(mcp.list_tools())
    names = {t.name for t in listed}
    assert names == {
        "log_decision",
        "log_session_event",
        "who_is_touching",
        "active_sessions",
        "recent_decisions",
    }


def test_build_server_from_config_requires_mesh(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(mesh={"supabase_url": "", "supabase_key_env": ""})
    monkeypatch.setattr("devorchestrator.config.load_config", lambda *a, **k: config)
    with pytest.raises(ConfigError):
        build_server_from_config()


def test_main_defaults_to_stdio() -> None:
    args = _parse_args([])
    assert args.transport == "stdio"
    assert args.host is None
    assert args.port is None


def test_main_accepts_http_transport_and_bind() -> None:
    args = _parse_args(
        ["--transport", "http", "--host", "0.0.0.0", "--port", "9000", "--path", "/mcp"]
    )
    assert args.transport == "http"
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.path == "/mcp"


def test_main_accepts_sse_transport() -> None:
    args = _parse_args(["-t", "sse"])
    assert args.transport == "sse"
