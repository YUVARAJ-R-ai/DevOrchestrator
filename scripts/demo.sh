#!/usr/bin/env bash
# scripts/demo.sh — scripted equivalent of the live demo, in one shot.
#
# Runs the REAL pipeline against a seeded demo issue: task -> branch -> live
# tmux research + implementation sessions -> checks (autofix on failure) ->
# PR -> TL approval, all against real GitHub + Supabase.
#
# `devorchestrator start && devorchestrator pr && devorchestrator review`
# now does the same thing as three separate commands (Wave-3 wiring is done —
# see build_pipeline()/build_review()). This script exists for a one-shot,
# non-interactive run: it constructs Pipeline/ReviewGate directly rather than
# stopping between steps for the dev to review the code, which the real CLI
# does deliberately (see docs/research.md's two-command design).
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
import sys

from devorchestrator.config import load_config
from devorchestrator.pipeline import PipelineAborted, PipelineError, build_pipeline
from devorchestrator.review import build_review

config = load_config()

# Built by the same factories the real CLI uses, deliberately: this script used
# to construct Pipeline/ReviewGate by hand, and drifted out of step with them —
# it was missing local_git=True (so it would have opened a PR with no commits)
# and the brain's config= argument. A scripted fallback that behaves differently
# from the thing it's a fallback for is worse than no fallback.
pipeline = build_pipeline(config, on_event=lambda m: print(f"› {m}"))


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

gate = build_review(config)
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
