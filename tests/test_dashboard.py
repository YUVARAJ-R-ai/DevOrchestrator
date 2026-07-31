from __future__ import annotations

from io import StringIO

from rich.console import Console

from devorchestrator.contracts import DevActivity
from devorchestrator.mesh.dashboard import render_dashboard


class FakeMesh:
    def emit(self, event_type: str, module: str, payload: dict) -> None:
        pass

    def who_is_touching(self, module: str) -> list[DevActivity]:
        return [
            DevActivity(
                dev="tharun",
                module=module,
                branch="main",
                event_type="check",
                ts="2026-01-01T00:00:00",
            )
        ]

    def recent_decisions(self, limit: int = 10) -> list:
        return []

    def list_modules(self) -> list[str]:
        return ["runner.py"]


def test_render_dashboard_output() -> None:
    buf = StringIO()
    console = Console(file=buf, width=120)
    mesh = FakeMesh()
    render_dashboard(mesh, console=console)
    output = buf.getvalue()
    assert "tharun" in output
    assert "runner.py" in output or "autofix.py" in output
    assert "check" in output


def test_render_dashboard_empty_mesh() -> None:
    class EmptyMesh:
        def emit(self, *a, **kw):
            pass
        def who_is_touching(self, module):
            return []
        def recent_decisions(self, limit=10):
            return []

        def list_modules(self) -> list[str]:
            return []

    buf = StringIO()
    console = Console(file=buf, width=120)
    render_dashboard(EmptyMesh(), console=console)
    output = buf.getvalue()
    assert "tharun" not in output


def test_dashboard_shows_active_sessions() -> None:
    """#59: the dashboard surfaces live sessions from active_sessions()."""
    from dataclasses import dataclass

    from devorchestrator.mesh.dashboard import build_dashboard

    @dataclass
    class _Session:
        dev: str
        branch: str
        kind: str
        state: str
        last_seen: str

    class MeshWithSessions:
        def who_is_touching(self, module):
            return []
        def list_modules(self):
            return []
        def recent_decisions(self, limit=10):
            return []
        def active_sessions(self):
            return [_Session("yuvaraj", "feature/x", "research", "running", "2026-07-31T09:00:00")]

    buf = StringIO()
    Console(file=buf, width=140).print(build_dashboard(MeshWithSessions()))
    out = buf.getvalue()
    assert "yuvaraj" in out
    assert "research" in out
    assert "running" in out


def test_dashboard_handles_mesh_without_active_sessions() -> None:
    """A mesh lacking active_sessions() (older/fake) must not crash the dashboard."""
    from devorchestrator.mesh.dashboard import build_dashboard

    class NoSessions:
        def who_is_touching(self, module):
            return []
        def list_modules(self):
            return []
        def recent_decisions(self, limit=10):
            return []

    buf = StringIO()
    Console(file=buf, width=140).print(build_dashboard(NoSessions()))
    assert "no active sessions" in buf.getvalue()
