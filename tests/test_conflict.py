from __future__ import annotations

from devorchestrator.contracts import DevActivity
from devorchestrator.mesh.conflict import warn_on_overlap


class FakeMesh:
    def __init__(self, activities: dict[str, list[DevActivity]]) -> None:
        self._activities = activities

    def emit(self, *a, **kw) -> None:
        pass

    def who_is_touching(self, module: str) -> list[DevActivity]:
        return self._activities.get(module, [])

    def recent_decisions(self, limit: int = 10) -> list:
        return []

    def list_modules(self) -> list[str]:
        return list(self._activities)


def test_no_overlap_returns_empty() -> None:
    mesh = FakeMesh({"runner.py": []})
    assert warn_on_overlap(mesh, ["runner.py"]) == []


def test_single_overlap_detected() -> None:
    act = DevActivity(dev="alice", module="runner.py", branch="feature/x",
                      event_type="check", ts="2026-01-01T00:00:00")
    mesh = FakeMesh({"runner.py": [act]})
    warnings = warn_on_overlap(mesh, ["runner.py"])
    assert len(warnings) == 1
    assert "alice" in warnings[0]
    assert "runner.py" in warnings[0]


def test_multiple_modules_overlap_detected() -> None:
    a1 = DevActivity(dev="alice", module="runner.py", branch="feature/x",
                     event_type="check", ts="2026-01-01T00:00:00")
    a2 = DevActivity(dev="bob", module="store.py", branch="feature/y",
                     event_type="check", ts="2026-01-01T00:00:01")
    mesh = FakeMesh({"runner.py": [a1], "store.py": [a2]})
    warnings = warn_on_overlap(mesh, ["runner.py", "store.py"])
    assert len(warnings) == 2

def test_duplicate_activities_deduplicated() -> None:
    act = DevActivity(dev="alice", module="runner.py", branch="feature/x",
                      event_type="check", ts="2026-01-01T00:00:00")
    mesh = FakeMesh({"runner.py": [act, act]})
    warnings = warn_on_overlap(mesh, ["runner.py"])
    assert len(warnings) == 1


def test_limit_respected() -> None:
    acts = [
        DevActivity(dev=f"dev{i}", module=f"mod{i}", branch="main",
                    event_type="check", ts="2026-01-01T00:00:00")
        for i in range(10)
    ]
    mesh = FakeMesh({f"mod{i}": [acts[i]] for i in range(10)})
    warnings = warn_on_overlap(mesh, [f"mod{i}" for i in range(10)], limit=3)
    assert len(warnings) == 3
