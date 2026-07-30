"""Mock factories and templates for integration testing Lane D components.

Each mock simulates an external dependency (subprocess, Supabase, httpx, git)
so tests verify behavior without hitting real services.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Mock subprocess runner (for checks/runner.py)
# ---------------------------------------------------------------------------


@dataclass
class MockSubprocessResult:
    """Shape mimicking ``subprocess.CompletedProcess``."""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


MockSubprocessRunner = Callable[
    [list[str], str | None, dict[str, Any]],
    MockSubprocessResult,
]


def make_runner(
    *,
    ruff_rc: int = 0,
    ruff_out: str = "All checks passed!",
    pytest_rc: int = 0,
    pytest_out: str = "1 passed",
) -> MockSubprocessRunner:
    """Build a mock subprocess runner that returns canned outputs.

    Inspects the command to decide whether it's ruff or pytest.
    Accepts and ignores extra kwargs so it can replace ``subprocess.run``.
    """

    def _run(
        cmd: list[str],
        cwd: str | None = None,
        env: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> MockSubprocessResult:
        tool = Path(cmd[0]).name if cmd else ""
        if tool == "ruff":
            return MockSubprocessResult(returncode=ruff_rc, stdout=ruff_out)
        if tool == "pytest":
            return MockSubprocessResult(returncode=pytest_rc, stdout=pytest_out)
        return MockSubprocessResult(returncode=0, stdout="")

    return _run


# ---------------------------------------------------------------------------
# Mock Supabase client (for mesh/store.py)
# ---------------------------------------------------------------------------


@dataclass
class MockSupabaseTable:
    """Mock a ``supabase.table(...)`` chain."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    inserted: list[dict[str, Any]] = field(default_factory=list)

    def insert(self, data: dict[str, Any]) -> MockSupabaseTable:
        self.inserted.append(data)
        return self

    def select(self, *cols: str) -> MockSupabaseTable:
        return self

    def eq(self, col: str, val: Any) -> MockSupabaseTable:
        self.rows = [r for r in self.rows if r.get(col) == val]
        return self

    def order(self, col: str, desc: bool = False) -> MockSupabaseTable:
        rev = -1 if desc else 1
        self.rows.sort(key=lambda r: r.get(col, ""), reverse=rev)
        return self

    def limit(self, n: int) -> MockSupabaseTable:
        self.rows = self.rows[:n]
        return self

    def execute(self) -> dict[str, Any]:
        return {"data": self.rows}

    def single(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None


@dataclass
class MockSupabaseClient:
    """Mock ``supabase.Client`` that returns ``MockSupabaseTable`` per table."""

    tables: dict[str, MockSupabaseTable] = field(default_factory=dict)

    def table(self, name: str) -> MockSupabaseTable:
        if name not in self.tables:
            self.tables[name] = MockSupabaseTable()
        return self.tables[name]


# ---------------------------------------------------------------------------
# Mock httpx client (for notify.py)
# ---------------------------------------------------------------------------


@dataclass
class MockHttpxResponse:
    status_code: int = 200
    text: str = "ok"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


@dataclass
class MockHttpxClient:
    """Mock ``httpx.Client`` that records POSTs and returns canned responses."""

    posts: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    status_code: int = 200

    def post(self, url: str, json: dict[str, Any] | None = None) -> MockHttpxResponse:
        self.posts.append((url, json or {}))
        return MockHttpxResponse(status_code=self.status_code)


# ---------------------------------------------------------------------------
# Mock git runner (for pr_description.py)
# ---------------------------------------------------------------------------


@dataclass
class MockGitRunner:
    """Mock ``subprocess.run`` for git commands."""

    log_output: str = ""
    fallback_log: str = ""

    def __call__(
        self,
        cmd: list[str],
        cwd: str | None = None,
        capture_output: bool = True,
        text: bool = True,
        env: dict[str, Any] | None = None,
    ) -> MockSubprocessResult:
        joined = " ".join(str(c) for c in cmd)
        if "log" in joined and "origin/dev..HEAD" in joined:
            return MockSubprocessResult(returncode=0, stdout=self.log_output)
        if "log" in joined:
            return MockSubprocessResult(returncode=0, stdout=self.fallback_log)
        return MockSubprocessResult(returncode=0, stdout="")


__all__ = [
    "MockSubprocessResult",
    "MockSubprocessRunner",
    "make_runner",
    "MockSupabaseTable",
    "MockSupabaseClient",
    "MockHttpxResponse",
    "MockHttpxClient",
    "MockGitRunner",
]
