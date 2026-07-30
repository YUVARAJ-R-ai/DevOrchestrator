"""Tests for `devorchestrator pr`'s dispatch into Pipeline.prepare_pr.

The command used to reimplement the checks → PR sequence inline, which meant its
autofix went through checks/autofix.py (a stub that only logs that it *would*
re-invoke the agent) rather than the pipeline's loop that actually re-runs the
implementation session. These cover the wiring that replaced it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from devorchestrator.cli import app
from devorchestrator.contracts import BranchRef, Issue, PipelineContext
from devorchestrator.pipeline import save_pipeline_context

runner = CliRunner()

CONFIG = """\
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


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "devOrchestrator.yaml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    return tmp_path


def test_pr_refuses_without_a_saved_context(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running `pr` before `start` must explain itself, not traceback."""
    monkeypatch.setattr("devorchestrator.cli._detect_branch", lambda: "feature/issue-9-widget")
    monkeypatch.chdir(workspace)

    result = runner.invoke(app, ["-C", str(workspace), "pr"])

    assert result.exit_code == 1
    assert "No saved task context" in result.output
    assert "devorchestrator start" in result.output


def test_pr_uses_the_saved_issue_and_calls_prepare_pr(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real issue title reaches prepare_pr — not a slug reconstruction."""
    branch = BranchRef(name="feature/issue-9-widget", issue_id="9", base="dev")
    ctx = PipelineContext(
        issue=Issue(id="9", title="Add the widget", description="d"), branch=branch
    )
    save_pipeline_context(ctx, root=workspace / ".orchestrator")

    seen: dict[str, object] = {}

    class _FakePipeline:
        def prepare_pr(self, pctx, *, autofix=True):
            seen["title"] = pctx.issue.title
            seen["base"] = pctx.branch.base
            seen["autofix"] = autofix
            pctx.pull_request = type(
                "PR", (), {"url": "https://github.com/acme/repo/pull/7", "number": 7}
            )()
            return pctx

    monkeypatch.setattr("devorchestrator.cli.build_pipeline", lambda *a, **kw: _FakePipeline())
    monkeypatch.setattr("devorchestrator.cli._detect_branch", lambda: branch.name)
    monkeypatch.chdir(workspace)

    result = runner.invoke(app, ["-C", str(workspace), "pr", "--no-autofix"])

    assert result.exit_code == 0, result.output
    assert seen["title"] == "Add the widget"
    assert seen["autofix"] is False
    assert "PR opened" in result.output


def test_pr_base_flag_overrides_the_saved_base(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    branch = BranchRef(name="feature/issue-9-widget", issue_id="9", base="dev")
    save_pipeline_context(
        PipelineContext(issue=Issue(id="9", title="t"), branch=branch),
        root=workspace / ".orchestrator",
    )

    seen: dict[str, object] = {}

    class _FakePipeline:
        def prepare_pr(self, pctx, *, autofix=True):
            seen["base"] = pctx.branch.base
            pctx.pull_request = type("PR", (), {"url": "u", "number": 1})()
            return pctx

    monkeypatch.setattr("devorchestrator.cli.build_pipeline", lambda *a, **kw: _FakePipeline())
    monkeypatch.setattr("devorchestrator.cli._detect_branch", lambda: branch.name)
    monkeypatch.chdir(workspace)

    result = runner.invoke(app, ["-C", str(workspace), "pr", "--base", "main"])

    assert result.exit_code == 0, result.output
    assert seen["base"] == "main"
