from __future__ import annotations

from devorchestrator.mesh.store import SupabaseMesh
from tests.mocks import MockSupabaseClient, MockSupabaseTable


def _make_client() -> MockSupabaseClient:
    return MockSupabaseClient()


def test_emit_inserts_event() -> None:
    client = _make_client()
    mesh = SupabaseMesh(client)  # type: ignore[arg-type]
    mesh.emit("check_pass", "runner.py", {"dev": "tharun"})

    events = client.table("events")
    assert len(events.inserted) == 1
    assert events.inserted[0]["event_type"] == "check_pass"
    assert events.inserted[0]["module"] == "runner.py"


def test_who_is_touching_returns_activities() -> None:
    client = _make_client()
    client.tables["events"] = MockSupabaseTable(
        rows=[
            {"dev": "alice", "module": "runner.py", "branch": "main",
             "event_type": "check", "ts": "2026-01-01T00:00:00"},
        ]
    )
    mesh = SupabaseMesh(client)  # type: ignore[arg-type]
    activities = mesh.who_is_touching("runner.py")
    assert len(activities) == 1
    assert activities[0].dev == "alice"


def test_who_is_touching_empty_module() -> None:
    client = _make_client()
    client.tables["events"] = MockSupabaseTable(rows=[])
    mesh = SupabaseMesh(client)  # type: ignore[arg-type]
    assert mesh.who_is_touching("nonexistent.py") == []


def test_recent_decisions_returns_filtered() -> None:
    client = _make_client()
    client.tables["events"] = MockSupabaseTable(
        rows=[
            {"dev": "tharun", "event_type": "decision", "module": "store.py",
             "payload": {"description": "use supabase", "modules": ["store.py"]},
             "ts": "2026-01-01T00:00:00"},
        ]
    )
    mesh = SupabaseMesh(client)  # type: ignore[arg-type]
    decisions = mesh.recent_decisions(limit=5)
    assert len(decisions) == 1
    assert decisions[0].description == "use supabase"
    assert decisions[0].dev == "tharun"


def test_recent_decisions_empty() -> None:
    client = _make_client()
    client.tables["events"] = MockSupabaseTable(rows=[])
    mesh = SupabaseMesh(client)  # type: ignore[arg-type]
    assert mesh.recent_decisions() == []


def test_list_modules_returns_distinct_modules() -> None:
    client = _make_client()
    client.tables["events"] = MockSupabaseTable(
        rows=[
            {"module": "runner.py"},
            {"module": "runner.py"},
            {"module": "store.py"},
        ]
    )
    mesh = SupabaseMesh(client)  # type: ignore[arg-type]
    modules = mesh.list_modules()
    assert "runner.py" in modules
    assert "store.py" in modules
    assert len(modules) == 2


def test_list_modules_empty() -> None:
    client = _make_client()
    client.tables["events"] = MockSupabaseTable(rows=[])
    mesh = SupabaseMesh(client)  # type: ignore[arg-type]
    assert mesh.list_modules() == []


def test_mesh_satisfies_protocol() -> None:
    from devorchestrator.contracts import Mesh

    client = _make_client()
    assert isinstance(SupabaseMesh(client), Mesh)  # type: ignore[arg-type]


class _BrokenClient:
    """A client whose every call raises — simulates a 401 / missing table."""

    def table(self, *_a, **_k):
        raise RuntimeError("Invalid API key")


def test_mesh_operations_are_non_fatal_when_backend_errors() -> None:
    """A misconfigured mesh (wrong key, missing tables) must degrade, never crash
    — the loop's observability is optional. Regression for the init 401 traceback."""
    mesh = SupabaseMesh(_BrokenClient())  # type: ignore[arg-type]

    # writes swallow the error, reads return empty, healthy() reports False
    mesh.emit("dev_joined", "init", {"dev": "yuvaraj"})  # must not raise
    assert mesh.who_is_touching("x") == []
    assert mesh.list_modules() == []
    assert mesh.recent_decisions() == []
    assert mesh.healthy() is False
    assert mesh.last_error and "Invalid API key" in mesh.last_error
