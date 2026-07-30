from __future__ import annotations

from devorchestrator.checks.runner import SubprocessCheckRunner, _run_tool
from devorchestrator.contracts import CheckStatus
from tests.mocks import make_runner


def test_run_tool_passes() -> None:
    runner = make_runner(ruff_rc=0)
    result = _run_tool("ruff", ["check", "."], ".", runner)
    assert result.tool == "ruff"
    assert result.status is CheckStatus.passed
    assert result.duration_s >= 0


def test_run_tool_fails() -> None:
    runner = make_runner(ruff_rc=1, ruff_out="E302 expected 2 blank lines")
    result = _run_tool("ruff", ["check", "."], ".", runner)
    assert result.status is CheckStatus.failed
    assert "E302" in result.output


def test_runner_stops_on_first_failure() -> None:
    mock = make_runner(ruff_rc=1)
    runner_inst = SubprocessCheckRunner(cwd=".", runner=mock)
    results = runner_inst.run_all()
    assert len(results) == 1
    assert results[0].tool == "ruff"
    assert results[0].status is CheckStatus.failed


def test_runner_all_checks_flag() -> None:
    mock = make_runner(ruff_rc=1)
    runner_inst = SubprocessCheckRunner(cwd=".", all_checks=True, runner=mock)
    results = runner_inst.run_all()
    assert len(results) == 2
    assert results[1].tool == "pytest"


def test_runner_both_pass() -> None:
    mock = make_runner(ruff_rc=0, pytest_rc=0)
    runner_inst = SubprocessCheckRunner(cwd=".", runner=mock)
    results = runner_inst.run_all()
    assert len(results) == 2
    assert all(r.passed for r in results)


def test_runner_pytest_failure() -> None:
    mock = make_runner(ruff_rc=0, pytest_rc=1, pytest_out="FAILED test_x.py")
    runner_inst = SubprocessCheckRunner(cwd=".", runner=mock)
    results = runner_inst.run_all()
    assert len(results) == 2
    assert results[0].passed
    assert results[1].status is CheckStatus.failed


def test_run_tool_not_found() -> None:
    def fake_runner(cmd, **kw):
        raise FileNotFoundError("ruff not found")

    result = _run_tool("ruff", ["check", "."], ".", fake_runner)
    assert result.status is CheckStatus.skipped


def test_runner_satisfies_protocol() -> None:
    from devorchestrator.contracts import CheckRunner

    assert isinstance(SubprocessCheckRunner(), CheckRunner)
