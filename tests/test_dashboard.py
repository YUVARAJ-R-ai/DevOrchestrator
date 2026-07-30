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
