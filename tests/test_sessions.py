"""Session runner + prompt tests (issue #8, Lane C).

These run headless: tmux and ``libtmux`` are optional extras, and the headless
path is the same code minus the pane, so the sentinel, timeout, and teardown
logic is exercised either way.
"""

from __future__ import annotations

import subprocess

import pytest

from devorchestrator import prompts
from devorchestrator.contracts import AgentSession, CheckResult, CheckStatus, Issue, Priority
from devorchestrator.sessions.impl import (
    build_autofix_prompt,
    build_impl_prompt,
    failing,
    run_impl,
)
from devorchestrator.sessions.research import branch_for, build_research_prompt
from devorchestrator.sessions.tmux_runner import (
    ClaudeSession,
    SessionKind,
    SessionStatus,
    TmuxRunner,
    artifact_path,
    claude_command,
    tmux_available,
    work_dir,
)

# ---------------------------------------------------------------------------
# Contract conformance
# ---------------------------------------------------------------------------


def test_claude_session_satisfies_the_agent_session_contract(tmp_path):
    session = ClaudeSession(
        SessionKind.research, branch="feature/issue-8-x", root=tmp_path, headless=True
    )
    assert isinstance(session, AgentSession)


def test_branch_name_adds_the_feature_prefix_to_the_contract_slug():
    """contracts.Issue.branch_slug() is the body; Lane C adds the prefix."""
    issue = Issue(id="8", title="tmux research + impl sessions")
    assert issue.branch_slug() == "issue-8-tmux-research-impl-sessions"
    assert branch_for(issue) == "feature/issue-8-tmux-research-impl-sessions"


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def test_every_template_loads():
    for name in ("research", "impl", "autofix", "artifact_schema"):
        assert prompts.load(name).strip()


def test_unknown_placeholder_does_not_raise():
    """A prompt typo must not abort a live demo."""
    rendered = prompts.render("impl", branch="b", artifact_path="p", bogus="ignored")
    assert "$branch" not in rendered and "$artifact_path" not in rendered


def test_research_prompt_embeds_task_and_schema(tmp_path):
    issue = Issue(
        id="42",
        title="Add JWT login",
        description="Needs stateless auth.",
        priority=Priority.high,
    )
    branch = branch_for(issue)
    text = build_research_prompt(issue, branch, root=tmp_path).read_text()

    assert "#42" in text and "Add JWT login" in text
    assert "Needs stateless auth." in text
    assert "high" in text
    assert "## Sub-tasks" in text  # the schema was interpolated
    assert str(artifact_path(branch, root=tmp_path)) in text


def test_research_prompt_handles_an_empty_description(tmp_path):
    path = build_research_prompt(Issue(id="1", title="t"), "feature/issue-1-t", root=tmp_path)
    assert "No description provided" in path.read_text()


def test_prompts_forbid_editing_the_frozen_contracts_file(tmp_path):
    """The agent must not edit another lane's file — least of all contracts.py."""
    impl = build_impl_prompt("feature/issue-8-x", root=tmp_path).read_text()
    assert "contracts.py" in impl
    assert "frozen" in impl.lower()


def test_impl_prompt_points_at_the_artifact(tmp_path):
    path = build_impl_prompt("feature/issue-42-x", root=tmp_path)
    assert str(artifact_path("feature/issue-42-x", root=tmp_path)) in path.read_text()


# ---------------------------------------------------------------------------
# Autofix prompt
# ---------------------------------------------------------------------------


def test_failing_ignores_skipped_checks():
    """A skipped optional tool is not something to send an agent to repair."""
    results = [
        CheckResult(tool="ruff", status=CheckStatus.passed),
        CheckResult(tool="gitleaks", status=CheckStatus.skipped),
        CheckResult(tool="pytest", status=CheckStatus.failed, output="1 failed"),
    ]
    assert [r.tool for r in failing(results)] == ["pytest"]


def test_autofix_prompt_carries_failure_context(tmp_path):
    results = [
        CheckResult(tool="ruff", status=CheckStatus.passed),
        CheckResult(
            tool="pytest",
            status=CheckStatus.failed,
            output="E   assert 1 == 2\nFAILED tests/test_x.py::test_y\n1 failed, 3 passed",
        ),
    ]
    text = build_autofix_prompt("feature/issue-8-x", results, attempt=2, root=tmp_path).read_text()

    assert "pytest" in text
    assert "1 failed, 3 passed" in text  # headline taken from the last output line
    assert "assert 1 == 2" in text
    assert "attempt **2 of 2**" in text
    assert "Never weaken a test" in text  # the guardrail survived rendering


def test_autofix_prompt_omits_passing_tools_from_the_failure_list(tmp_path):
    results = [
        CheckResult(tool="ruff", status=CheckStatus.passed, output="All checks passed!"),
        CheckResult(tool="pytest", status=CheckStatus.failed, output="1 failed"),
    ]
    text = build_autofix_prompt("feature/issue-8-x", results, root=tmp_path).read_text()
    what_failed = text.split("## Failure output")[0].split("## What failed")[1]
    assert "pytest" in what_failed and "ruff" not in what_failed


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------


def test_work_dir_records_the_branch_name(tmp_path):
    """Branch names contain slashes, so the directory path alone is lossy."""
    branch = "feature/issue-8-tmux-sessions"
    assert (work_dir(branch, root=tmp_path) / ".do-branch").read_text().strip() == branch


def test_claude_command_quotes_paths_and_sets_permission_mode(tmp_path):
    weird = tmp_path / "a dir with spaces" / "research-prompt.txt"
    weird.parent.mkdir(parents=True)
    weird.touch()
    command = claude_command(weird)
    assert "'" in command
    assert "--permission-mode" in command


def test_claude_args_are_overridable(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVORCH_CLAUDE_ARGS", "--permission-mode plan")
    path = tmp_path / "p.txt"
    path.touch()
    assert "plan" in claude_command(path)


# ---------------------------------------------------------------------------
# Runner (headless)
# ---------------------------------------------------------------------------


def test_headless_runner_captures_exit_code_and_output(tmp_path):
    runner = TmuxRunner(
        branch="feature/issue-1-x", cwd=tmp_path, force_headless=True, root=tmp_path
    )
    spawned = runner.spawn(SessionKind.research, "echo hello-agent")
    state = runner.wait(spawned, timeout=30, poll=0.1)

    assert state.ok and state.exit_code == 0
    assert "hello-agent" in runner.capture(state)
    assert not runner.is_alive(state)


def test_headless_runner_reports_a_failing_command(tmp_path):
    runner = TmuxRunner(
        branch="feature/issue-1-y", cwd=tmp_path, force_headless=True, root=tmp_path
    )
    state = runner.wait(runner.spawn(SessionKind.impl, "exit 3"), timeout=30, poll=0.1)

    assert not state.ok
    assert state.status is SessionStatus.failed
    assert state.exit_code == 3


def test_runner_times_out_on_a_hanging_command(tmp_path):
    runner = TmuxRunner(
        branch="feature/issue-1-z", cwd=tmp_path, force_headless=True, root=tmp_path
    )
    state = runner.wait(runner.spawn(SessionKind.impl, "sleep 30"), timeout=0.5, poll=0.1)

    assert state.status is SessionStatus.timeout
    assert "no completion" in (state.error or "")
    runner.kill()


def test_stale_exit_sentinel_is_cleared_between_runs(tmp_path):
    """A leftover .exit file would make the next run look instantly complete."""
    branch = "feature/issue-1-s"
    runner = TmuxRunner(branch=branch, cwd=tmp_path, force_headless=True, root=tmp_path)
    (work_dir(branch, root=tmp_path) / "research.exit").write_text("0\n")

    state = runner.wait(runner.spawn(SessionKind.research, "exit 7"), timeout=30, poll=0.1)
    assert state.exit_code == 7


def test_agent_session_run_writes_the_prompt_and_executes(tmp_path):
    """The AgentSession contract path: run(prompt) with no file plumbing."""
    session = ClaudeSession(
        SessionKind.research,
        branch="feature/issue-1-r",
        cwd=tmp_path,
        agent="echo",  # stands in for `claude`; echoes the flags and the prompt back
        headless=True,
        root=tmp_path,
    )
    session.run("a prompt the agent will echo")
    state = session.wait(timeout=30, poll=0.1)

    assert state.ok
    assert "a prompt the agent will echo" in session.capture()


def test_run_impl_fails_clearly_without_an_artifact(tmp_path):
    state = run_impl("feature/issue-1-missing", root=tmp_path, headless=True)
    assert state.status is SessionStatus.failed
    assert "missing artifact" in (state.error or "")


@pytest.mark.parametrize(
    ("branch", "expected"),
    [("feature/issue-8-x", "do-feature-issue-8-x"), ("fix/issue-2-a.b", "do-fix-issue-2-a-b")],
)
def test_tmux_session_name_is_sanitized(branch, expected, tmp_path):
    """tmux rejects dots and handles slashes awkwardly."""
    assert TmuxRunner(branch=branch, root=tmp_path).session_name == expected


# ---------------------------------------------------------------------------
# Real tmux — the demo path. Skipped only where tmux itself is absent.
# ---------------------------------------------------------------------------


def _tmux_skip_reason() -> str | None:
    """Why the real-tmux tests cannot run here, or None if they can.

    Deliberately separates the two causes, because only one of them is normal.
    No ``tmux`` binary is a fine reason to skip — plenty of CI images lack it.
    A ``tmux`` binary *with no libtmux* is an environment bug: libtmux is a core
    dependency, so its absence means ``uv sync`` was never run or ran against a
    stale lock (see ``test_packaging.py``).

    The old single ``tmux / libtmux not installed`` reason blurred the two, so
    the second case looked routine. It was not: these tests silently skipped on
    a machine that had tmux, and a real bug — impl overwriting the research pane
    — survived a green suite because of it.
    """
    import shutil

    if not shutil.which("tmux"):
        return "no tmux binary (expected on CI images without tmux)"
    if not tmux_available():
        return (
            "tmux is installed but libtmux is NOT — libtmux is a core dependency, "
            "so this environment is broken, not merely tmux-less. Run `uv sync`."
        )
    return None


needs_tmux = pytest.mark.skipif(_tmux_skip_reason() is not None, reason=_tmux_skip_reason() or "")


@needs_tmux
def test_finished_pane_stays_visible(tmp_path):
    """Panes are exec'd, so without remain-on-exit they vanish the instant the
    agent exits — taking the output a watching dev came to see."""
    branch = "feature/issue-8-remain"
    runner = TmuxRunner(branch=branch, cwd=tmp_path, root=tmp_path)
    try:
        state = runner.wait(
            runner.spawn(SessionKind.research, "echo agent-output-to-keep"),
            timeout=30,
            poll=0.1,
        )
        assert state.ok

        pane = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", f"{runner.session_name}:{state.tmux_window}"],
            capture_output=True,
            text=True,
        )
        assert pane.returncode == 0, "window disappeared after the command finished"
        assert "agent-output-to-keep" in pane.stdout
    finally:
        runner.kill()


@needs_tmux
def test_research_and_impl_share_one_split_window(tmp_path):
    """Issue #60: one window, research left and impl right, both visible at once.

    Uses two separate ``TmuxRunner`` instances because that is what
    ``pipeline.py`` does — it builds a ``ClaudeSession`` per kind. A runner that
    decides "am I the first pane?" from its own state gets this wrong and lets
    impl overwrite the research pane, which is the exact regression this asserts
    against. Both outputs must survive.
    """
    branch = "feature/issue-60-split"
    research = TmuxRunner(branch=branch, cwd=tmp_path, root=tmp_path)
    impl = TmuxRunner(branch=branch, cwd=tmp_path, root=tmp_path)
    try:
        research.wait(
            research.spawn(SessionKind.research, "echo one-research"), timeout=30, poll=0.1
        )
        impl.wait(impl.spawn(SessionKind.impl, "echo two-impl"), timeout=30, poll=0.1)

        panes = subprocess.run(
            ["tmux", "list-panes", "-s", "-t", research.session_name, "-F", "#{pane_index}"],
            capture_output=True,
            text=True,
        ).stdout.split()
        assert len(panes) == 2, f"expected a split, got {len(panes)} pane(s): {panes}"

        windows = subprocess.run(
            ["tmux", "list-windows", "-t", research.session_name, "-F", "#{window_name}"],
            capture_output=True,
            text=True,
        ).stdout.split()
        assert len(windows) == 1, f"panes should share one window, got {windows}"

        combined = "".join(
            subprocess.run(
                ["tmux", "capture-pane", "-p", "-t", f"{research.session_name}:0.{idx}"],
                capture_output=True,
                text=True,
            ).stdout
            for idx in panes
        )
        assert "one-research" in combined
        assert "two-impl" in combined
    finally:
        research.kill()
