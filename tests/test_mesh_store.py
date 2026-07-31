from __future__ import annotations

from datetime import UTC, datetime, timedelta

from devorchestrator.mesh.store import SupabaseMesh
from tests.mocks import MockSupabaseClient, MockSupabaseTable


def _make_client() -> MockSupabaseClient:
    return MockSupabaseClient()


def _iso(seconds_ago: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()


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


def _session_row(
    *,
    dev: str,
    kind: str,
    state: str,
    branch: str = "feature/x",
    seconds_ago: int = 0,
) -> dict:
    return {
        "dev": dev,
        "branch": branch,
        "kind": kind,
        "state": state,
        "last_seen": _iso(seconds_ago),
        "started_at": _iso(seconds_ago + 30),
        "finished_at": None if state in ("running", "pending") else _iso(seconds_ago - 5),
    }


def test_active_sessions_returns_only_recent_running() -> None:
    client = _make_client()
    client.tables["sessions"] = MockSupabaseTable(
        rows=[
            _session_row(dev="alice", kind="research", state="running", seconds_ago=10),
            _session_row(dev="bob", kind="impl", state="running", seconds_ago=500),
            _session_row(dev="carol", kind="impl", state="completed", seconds_ago=20),
        ]
    )
    mesh = SupabaseMesh(client)  # type: ignore[arg-type]
    active = mesh.active_sessions()
    assert [s.dev for s in active] == ["alice"]


def test_active_sessions_obeys_custom_window() -> None:
    client = _make_client()
    client.tables["sessions"] = MockSupabaseTable(
        rows=[
            _session_row(dev="alice", kind="research", state="running", seconds_ago=30),
            _session_row(dev="bob", kind="impl", state="running", seconds_ago=90),
        ]
    )
    mesh = SupabaseMesh(client)  # type: ignore[arg-type]
    active = mesh.active_sessions(within_seconds=60)
    assert [s.dev for s in active] == ["alice"]


def test_active_sessions_empty() -> None:
    client = _make_client()
    client.tables["sessions"] = MockSupabaseTable(rows=[])
    mesh = SupabaseMesh(client)  # type: ignore[arg-type]
    assert mesh.active_sessions() == []


def test_session_history_returns_finished_only() -> None:
    client = _make_client()
    client.tables["sessions"] = MockSupabaseTable(
        rows=[
            _session_row(dev="bob", kind="impl", state="running", seconds_ago=5),
            _session_row(dev="carol", kind="impl", state="completed", seconds_ago=100),
            _session_row(dev="dave", kind="research", state="failed", seconds_ago=200),
            _session_row(dev="erin", kind="impl", state="pending", seconds_ago=1),
        ]
    )
    mesh = SupabaseMesh(client)  # type: ignore[arg-type]
    history = mesh.session_history()
    assert [s.dev for s in history] == ["carol", "dave"]


def test_session_history_respects_limit() -> None:
    client = _make_client()
    client.tables["sessions"] = MockSupabaseTable(
        rows=[
            _session_row(dev="carol", kind="impl", state="completed", seconds_ago=100),
            _session_row(dev="dave", kind="research", state="failed", seconds_ago=200),
            _session_row(dev="erin", kind="impl", state="timeout", seconds_ago=300),
        ]
    )
    mesh = SupabaseMesh(client)  # type: ignore[arg-type]
    history = mesh.session_history(limit=2)
    assert [s.dev for s in history] == ["carol", "dave"]


def test_session_history_empty() -> None:
    client = _make_client()
    client.tables["sessions"] = MockSupabaseTable(rows=[])
    mesh = SupabaseMesh(client)  # type: ignore[arg-type]
    assert mesh.session_history() == []


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
    assert mesh.active_sessions() == []
    assert mesh.session_history() == []
    assert mesh.healthy() is False
    assert mesh.last_error and "Invalid API key" in mesh.last_error


def test_register_dev_upserts_the_roster():
    """devs was dead schema — nothing wrote to it (#51)."""
    client = MockSupabaseClient()
    mesh = SupabaseMesh(client)

    mesh.register_dev("harsha", "tl")

    row = client.tables["devs"].inserted[0]
    assert row["name"] == "harsha"
    assert row["role"] == "tl"
    assert row["last_seen"]


def test_register_dev_is_idempotent_per_name():
    client = MockSupabaseClient()
    mesh = SupabaseMesh(client)

    mesh.register_dev("harsha", "dev")
    mesh.register_dev("harsha", "tl")  # same person, role changed

    assert len(client.tables["devs"].rows) == 1
    assert client.tables["devs"].rows[0]["role"] == "tl"


def test_team_roster_reads_back_registered_devs():
    client = MockSupabaseClient()
    mesh = SupabaseMesh(client)
    mesh.register_dev("harsha", "tl")
    mesh.register_dev("yuvaraj", "dev")

    roster = mesh.team_roster()

    assert {(n, r) for n, r, _ in roster} == {("harsha", "tl"), ("yuvaraj", "dev")}


def test_register_dev_never_raises_when_the_backend_is_down():
    """The roster is metadata — a failure must not break `init`."""
    class _Boom:
        def table(self, name):
            raise RuntimeError("connection refused")

    mesh = SupabaseMesh(_Boom())
    mesh.register_dev("harsha")  # must not raise
    assert mesh.last_error is not None
