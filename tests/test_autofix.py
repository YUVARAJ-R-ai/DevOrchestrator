from __future__ import annotations

from devorchestrator.checks.autofix import autofix
from devorchestrator.checks.runner import SubprocessCheckRunner
from tests.mocks import make_runner


def test_autofix_passes_first_try() -> None:
    mock = make_runner(ruff_rc=0, pytest_rc=0)
    runner = SubprocessCheckRunner(cwd=".", runner=mock)
    results = autofix(runner, max_retries=2)
    assert all(r.passed for r in results)


def test_autofix_recovers_after_retry() -> None:
    call_count = 0

    def flaky_runner(cmd, **kw):
        nonlocal call_count
        call_count += 1
        rc = 0 if call_count > 1 else 1
        return type("Proc", (), {"returncode": rc, "stdout": "", "stderr": ""})()

    runner = SubprocessCheckRunner(cwd=".", runner=flaky_runner)
    results = autofix(runner, max_retries=2)
    assert all(r.passed for r in results)
    assert call_count >= 3


def test_autofix_exhausts_retries() -> None:
    mock = make_runner(ruff_rc=1)
    runner = SubprocessCheckRunner(cwd=".", runner=mock)
    results = autofix(runner, max_retries=1)
    failed = [r for r in results if not r.passed]
    assert len(failed) >= 1
