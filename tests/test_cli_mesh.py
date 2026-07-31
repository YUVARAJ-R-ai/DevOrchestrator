"""Tests for `mesh` / `decision` backend failure handling (#48).

Both commands used to build the Supabase client inline with no guard, so an
unconfigured mesh, a missing key, or an unreachable host produced a raw httpx
traceback. `init` already reported these properly; these two now match it.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from devorchestrator.cli import app

runner = CliRunner()

BASE = """\
name: tester
role: dev
agent: claude
board:
  type: github
  url: https://github.com/acme/repo
  token_env: GITHUB_TOKEN
git:
  type: github
  url: https://github.com/acme/repo
  token_env: GITHUB_TOKEN
"""

WITH_MESH = BASE + """\
mesh:
  supabase_url: https://proj.supabase.co
  supabase_key_env: SUPABASE_SERVICE_KEY
"""


def _workspace(tmp_path: Path, config: str) -> Path:
    (tmp_path / "devOrchestrator.yaml").write_text(config, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("command", [["mesh"], ["decision", "a decision"]])
def test_unconfigured_mesh_reports_clearly(tmp_path, monkeypatch, command):
    ws = _workspace(tmp_path, BASE)  # no mesh section at all
    monkeypatch.setenv("GITHUB_TOKEN", "t")

    result = runner.invoke(app, ["-C", str(ws), *command])

    assert result.exit_code == 2
    assert "no mesh configured" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("command", [["mesh"], ["decision", "a decision"]])
def test_missing_mesh_key_reports_clearly(tmp_path, monkeypatch, command):
    ws = _workspace(tmp_path, WITH_MESH)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)

    result = runner.invoke(app, ["-C", str(ws), *command])

    assert result.exit_code == 2
    assert "SUPABASE_SERVICE_KEY" in result.output
    assert "Traceback" not in result.output


def test_unreachable_backend_reports_instead_of_tracebacking(tmp_path, monkeypatch):
    ws = _workspace(tmp_path, WITH_MESH)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")

    class _Boom:
        def emit(self, *a, **kw):
            raise httpx.ConnectError("connection refused")

        def list_modules(self):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("devorchestrator.cli._mesh_or_exit", lambda config: _Boom())

    result = runner.invoke(app, ["-C", str(ws), "decision", "a decision"])

    assert result.exit_code == 1
    assert "mesh unreachable" in result.output
    assert "Traceback" not in result.output
