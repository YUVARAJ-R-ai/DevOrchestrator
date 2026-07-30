"""Lane C against the real Spine (issues #8, #10).

Everything else in the suite tests Lane C in isolation or the Spine with fakes.
This file wires Harsha's real :class:`~devorchestrator.pipeline.Pipeline` to Lane
C's real :class:`~devorchestrator.sessions.tmux_runner.ClaudeSession`, with a
stand-in agent binary in place of `claude`, so the integration seam is covered
before Wave 3 rather than discovered during it.

The contract that matters here is the one in docs/spine.md: `pipeline.py` reads
the artifact on the line after `research.run(...)` returns, so `run()` must block
until the agent has actually finished.
"""

from __future__ import annotations

import textwrap

import pytest
from conftest import FakeChecks, FakeGit, FakeMesh, FakeNotifier, make_config, passing

from devorchestrator.contracts import BranchRef, Issue
from devorchestrator.pipeline import Pipeline
from devorchestrator.sessions.tmux_runner import (
    ClaudeSession,
    SessionFailed,
    SessionKind,
    tmux_available,
)


@pytest.fixture
def agent(tmp_path):
    """A stand-in for the `claude` CLI, invoked exactly as the real one is.

    Research writes an artifact; implementation ticks its sub-tasks off.
    """
    script = tmp_path / "fake-agent"
    script.write_text(
        textwrap.dedent(
            '''
            #!/usr/bin/env python3
            import re, sys, pathlib
            prompt = sys.argv[-1]
            m = re.search(r"([^\\s`*]*/artifact\\.md)", prompt)
            if not m:
                sys.exit("no artifact path in prompt")
            target = pathlib.Path(m.group(1))
            if "implement every sub-task" in prompt:
                text = target.read_text()
                target.write_text(text.replace("- [ ]", "- [x]"))
                print("agent: implemented")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    "# Artifact: Add widget\\n\\n"
                    "## Sub-tasks\\n- [ ] build it\\n- [ ] test it\\n\\n"
                    "## Files to Create/Modify\\n"
                    "- `src/devorchestrator/widget.py` \\u2014 new widget\\n"
                    "- `tests/test_widget.py` \\u2014 tests\\n"
                )
                print("agent: wrote artifact")
            '''
        ).strip()
    )
    script.chmod(0o755)
    return str(script)


def _session(kind, tmp_path, agent, **over):
    """A ClaudeSession as build_pipeline would make one: no branch yet."""
    kwargs = dict(cwd=tmp_path, agent=agent, headless=True, root=tmp_path, timeout=60)
    kwargs.update(over)
    return ClaudeSession(kind, **kwargs)


def _pipeline(tmp_path, agent, *, checks=None, mesh=None, notifier=None):
    branch = BranchRef(name="feature/issue-9-widget", issue_id="9", base="dev")
    return Pipeline(
        make_config(),
        board=_Board([Issue(id="9", title="Add widget", description="build the widget")]),
        git=FakeGit(branch),
        research=_session(SessionKind.research, tmp_path, agent),
        impl=_session(SessionKind.impl, tmp_path, agent),
        checks=checks or FakeChecks([[passing("ruff"), passing("pytest")]]),
        mesh=mesh,
        notifier=notifier,
        workdir=tmp_path,
    )


class _Board:
    def __init__(self, issues):
        self._issues = issues

    def fetch_issues(self):
        return self._issues

    def move_issue(self, issue_id, state):
        pass


# ---------------------------------------------------------------------------


def test_pipeline_start_drives_real_lane_c_sessions(tmp_path, agent):
    """The whole inner loop: branch -> research -> artifact -> implement."""
    pipeline = _pipeline(tmp_path, agent)
    ctx = pipeline.start(select=lambda issues: issues[0])

    assert ctx.artifact is not None
    # The Spine read a populated artifact, which only happens if run() blocked.
    assert "Sub-tasks" in ctx.artifact.raw
    assert ctx.artifact.issue_id == "9"
    assert ctx.artifact.modules_affected  # Spine's own parse found the file list

    # ...and the implementation session actually ticked the boxes off.
    assert "- [x] build it" in (tmp_path / ctx.branch.name / "artifact.md").read_text()


def test_run_blocks_until_the_agent_has_finished(tmp_path, agent):
    """docs/spine.md: the work must be done by the time run() returns."""
    session = _session(SessionKind.research, tmp_path, agent)
    artifact = tmp_path / "feature/issue-9-widget/artifact.md"

    session.run(f"research session — write the plan to {artifact}")

    assert artifact.is_file(), "run() returned before the agent wrote the artifact"
    assert not session.is_alive()


def test_session_binds_its_branch_from_the_prompt(tmp_path, agent):
    """build_pipeline constructs sessions before any branch exists."""
    session = _session(SessionKind.research, tmp_path, agent)
    assert session.branch is None

    session.run(f"research session — write to {tmp_path}/feature/issue-9-widget/artifact.md")
    assert session.branch == "feature/issue-9-widget"


def test_explicit_bind_is_honoured(tmp_path, agent):
    session = _session(SessionKind.research, tmp_path, agent)
    session.bind("fix/issue-3-thing")
    assert session.branch == "fix/issue-3-thing"
    assert session.runner is not None
    assert session.runner.session_name == "do-fix-issue-3-thing"


def test_unresolvable_branch_fails_with_a_clear_message(tmp_path, agent):
    session = _session(SessionKind.research, tmp_path, agent)
    with pytest.raises(SessionFailed, match="bind"):
        session.run("a prompt that names no artifact path at all")


def test_failed_session_raises_instead_of_returning_quietly(tmp_path):
    """A silent failure would let the Spine implement an empty artifact."""
    session = _session(SessionKind.research, tmp_path, agent="false")
    with pytest.raises(SessionFailed, match="research session failed"):
        session.run(f"write to {tmp_path}/feature/issue-9-widget/artifact.md")


def test_autofix_retry_loop_reinvokes_the_impl_session(tmp_path, agent):
    """The Spine's autofix budget drives Lane C's impl session again."""
    from conftest import failing

    checks = FakeChecks([[failing("pytest")], [passing("pytest")]])
    pipeline = _pipeline(tmp_path, agent, checks=checks)
    ctx = pipeline.start(select=lambda issues: issues[0])
    ctx = pipeline.prepare_pr(ctx)

    assert checks.calls == 2  # failed, autofixed, passed
    assert ctx.pull_request is not None


def test_mesh_events_carry_lane_c_artifact_modules(tmp_path, agent):
    mesh, notifier = FakeMesh(), FakeNotifier()
    pipeline = _pipeline(tmp_path, agent, mesh=mesh, notifier=notifier)
    pipeline.start(select=lambda issues: issues[0])

    generated = [e for e in mesh.events if e[0] == "artifact_generated"]
    assert generated, mesh.events
    assert generated[0][2]["modules_affected"]


@pytest.mark.skipif(not tmux_available(), reason="tmux / libtmux not installed")
def test_pipeline_works_through_real_tmux(tmp_path, agent):
    """The demo path: same loop, real panes."""
    branch = BranchRef(name="feature/issue-9-widget", issue_id="9", base="dev")
    research = _session(SessionKind.research, tmp_path, agent, headless=False)
    impl = _session(SessionKind.impl, tmp_path, agent, headless=False)
    pipeline = Pipeline(
        make_config(),
        board=_Board([Issue(id="9", title="Add widget", description="d")]),
        git=FakeGit(branch),
        research=research,
        impl=impl,
        checks=FakeChecks([[passing()]]),
        workdir=tmp_path,
    )
    try:
        ctx = pipeline.start(select=lambda issues: issues[0])
        assert "Sub-tasks" in ctx.artifact.raw
        assert research.state.tmux_session == "do-feature-issue-9-widget"
    finally:
        research.kill()
        impl.kill()
