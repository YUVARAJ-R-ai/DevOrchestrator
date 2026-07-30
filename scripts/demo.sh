#!/usr/bin/env bash
# scripts/demo.sh — the 18h hackathon live demo driver.
#
# Runs the REAL pipeline against a seeded demo issue: task -> branch -> live
# tmux research + implementation sessions -> checks (autofix on failure) ->
# PR -> TL approval, all against real GitHub + Supabase.
#
# WHY THIS SCRIPT EXISTS INSTEAD OF `devorchestrator start`:
# pipeline.build_pipeline() and review.build_review() are still Wave-3 stubs
# (see pipeline.py's own "TODO(wave-3): instantiate concrete adapters from
# config here" — confirmed unconditional on every branch as of issue #7).
# This script constructs Pipeline/ReviewGate directly from the adapters that
# already exist and work: GithubBoard (#5), GithubGit (#6), ClaudeSession x2
# (#8), SubprocessCheckRunner (#11), SupabaseMesh (Lane D). Once harsha
# finishes Wave-3 wiring, this whole script collapses to two commands:
#   devorchestrator start && devorchestrator pr && devorchestrator review
#
# See docs/DEMO.md for the full runbook, the one-line pitch, and the
# fallback plan if a live API misbehaves on stage.

set -euo pipefail
cd "$(dirname "$0")/.."

echo "── DevOrchestrator demo — pre-flight checks ──────────────────────"

if [ ! -f devOrchestrator.yaml ]; then
  echo "✗ devOrchestrator.yaml not found. Copy devOrchestrator.yaml.template and fill it in."
  exit 1
fi

: "${GITHUB_TOKEN:?GITHUB_TOKEN must be set (board + git token)}"

command -v tmux >/dev/null 2>&1 || { echo "✗ tmux not found — required for the live demo panes."; exit 1; }
command -v claude >/dev/null 2>&1 || { echo "✗ claude CLI not found — run \`claude auth login\` first."; exit 1; }

echo "✓ config present, GITHUB_TOKEN set, tmux + claude CLI on PATH"

if [ -z "${SUPABASE_SERVICE_KEY:-}" ]; then
  echo "⚠ SUPABASE_SERVICE_KEY not set — demo will run WITHOUT the mesh"
  echo "  (no conflict detection, no decision log; the task->PR loop still works)"
fi

echo
echo "── Running the pipeline against the seeded demo issue ─────────────"
echo "  (watch the tmux panes: tmux attach -t do-<branch>)"
echo

uv run python - <<'PYEOF'
import os
import sys

from devorchestrator.checks.runner import SubprocessCheckRunner
from devorchestrator.config import load_config
from devorchestrator.integrations.github_board import GithubBoard
from devorchestrator.integrations.github_git import GithubGit
from devorchestrator.pipeline import Pipeline, PipelineAborted, PipelineError
from devorchestrator.pr_description import generate_pr_description
from devorchestrator.review import ReviewGate
from devorchestrator.sessions.tmux_runner import ClaudeSession, SessionKind

config = load_config()

board = GithubBoard(
    url=config.board.url,
    token=os.environ[config.board.token_env],
    dev_name=config.name,
    project_number=config.board.project_number,
)
git = GithubGit(
    url=config.git.url,
    token=os.environ[config.git.token_env],
    reviewer=os.environ.get("DEMO_REVIEWER"),
)
research = ClaudeSession(SessionKind.research, agent=config.agent.value)
impl = ClaudeSession(SessionKind.impl, agent=config.agent.value)
checks = SubprocessCheckRunner()

mesh = None
key = os.environ.get(config.mesh.supabase_key_env, "")
if config.mesh.supabase_url and key:
    from devorchestrator.mesh.store import SupabaseMesh, create_supabase_client

    mesh = SupabaseMesh(create_supabase_client(config.mesh.supabase_url, key))

pipeline = Pipeline(
    config,
    board=board,
    git=git,
    research=research,
    impl=impl,
    checks=checks,
    mesh=mesh,
    describe_pr=lambda ctx: generate_pr_description(ctx.branch.name, base=ctx.branch.base),
    on_event=lambda m: print(f"› {m}"),
)


def pick_demo_issue(issues):
    """Auto-pick the seeded demo issue (title contains 'demo'); else the first one."""
    for issue in issues:
        if "demo" in issue.title.lower():
            return issue
    return issues[0] if issues else None


try:
    ctx = pipeline.start(pick_demo_issue)
    ctx = pipeline.prepare_pr(ctx, autofix=True)
except PipelineAborted as exc:
    print(f"✗ aborted: {exc}")
    sys.exit(1)
except PipelineError as exc:
    print(f"✗ pipeline error: {exc}")
    sys.exit(1)

print(f"\n✓ PR opened: {ctx.pull_request.url}")
print("\n── TL approval gate — the human moment ─────────────────────────")

gate = ReviewGate(config, git=git, mesh=mesh)
gate.review_pr(ctx.pull_request, ctx.checks, ctx.artifact)

choice = input("\n[a] approve & merge   [r] reject   [q] quit: ").strip().lower()
if choice == "a":
    decision = gate.approve(ctx.pull_request)
    print(f"✓ {decision.action}: {decision.pr.url}")
elif choice == "r":
    reason = input("Rejection reason: ").strip()
    decision = gate.reject(ctx.pull_request, reason)
    print(f"✓ {decision.action}: {decision.reason}")
else:
    print("Skipped — PR left open for manual review.")
PYEOF
