"""PR description generation (backlog #13 + #26).

Two layers:
- a deterministic *mechanical* description (git log + artifact), which always
  works with no external dependency, and
- an optional pass through the **orchestrator brain** (SiliconFlow / DeepSeek,
  see sessions/brain.py) that rewrites those raw facts into a readable PR body.

The brain can never break this: :meth:`Brain.complete` returns local fallback
text on any provider error, and building the brain without a key / without the
``openai`` extra yields a fallback-only brain — so a missing or flaky provider
just means you get the mechanical description, never a crash.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

_PR_SYSTEM = (
    "You are a senior engineer writing a concise, accurate GitHub pull-request "
    "description. Use only the facts given (commit log + implementation artifact). "
    "Do not invent changes. Output GitHub-flavored Markdown with a short summary, "
    "a bullet list of what changed, and a testing note."
)


def _git_log(branch: str = "dev", cwd: str | None = None) -> str:
    try:
        proc = subprocess.run(
            ["git", "log", f"origin/{branch}..HEAD", "--oneline"],
            cwd=cwd or Path.cwd(),
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()
    except Exception:
        return ""


def _read_artifact(branch: str, cwd: str | None = None) -> str:
    path = Path(cwd or Path.cwd()) / ".orchestrator" / branch / "artifact.md"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


def _mechanical_description(branch: str, commits: str, artifact: str) -> str:
    """The always-available description — no external provider needed."""
    lines = [f"## What\n\nAutomated PR for branch `{branch}`."]
    if commits:
        lines.append(f"\n### Commits\n```\n{commits}\n```")
    if artifact:
        lines.append(f"\n### Artifact\n\n{artifact[:500]}")
    lines.append("\n### Quality\n- [ ] Gates pass (ruff + pytest)\n- [ ] TL review approved")
    return "\n".join(lines)


def _brain_prompt(branch: str, commits: str, artifact: str) -> str:
    return (
        f"Write a PR description for branch `{branch}`.\n\n"
        f"## Commit log\n{commits or '(no commits listed)'}\n\n"
        f"## Implementation artifact (the plan that was executed)\n"
        f"{artifact[:2000] or '(no artifact)'}\n"
    )


def generate_pr_description(
    branch: str,
    base: str = "dev",
    *,
    cwd: str | None = None,
    config: Any | None = None,
) -> str:
    """Return a PR description — brain-written if a brain is configured/reachable,
    else the deterministic mechanical one.

    ``config`` is the loaded :class:`~devorchestrator.config.Config`; when omitted
    (or when its ``brain`` block / key / the ``openai`` extra is absent) this
    returns the mechanical description without ever calling out.
    """
    cwd = cwd or str(Path.cwd())
    commits = _git_log(base, cwd)
    artifact = _read_artifact(branch, cwd)
    mechanical = _mechanical_description(branch, commits, artifact)

    brain = _maybe_brain(config)
    if brain is None or not brain.available:
        return mechanical

    try:
        text = asyncio.run(
            brain.complete(_brain_prompt(branch, commits, artifact), system=_PR_SYSTEM,
                           max_tokens=800)
        )
    except Exception:
        return mechanical
    # Brain.complete returns its own fallback marker text on provider failure;
    # keep the mechanical body in that case rather than shipping the marker.
    if not text or text.startswith("_Generated without the orchestrator brain"):
        return mechanical
    return text


def _maybe_brain(config: Any | None):
    """Build the brain from config, or None if it can't be built (never raises)."""
    if config is None:
        return None
    try:
        from .sessions.brain import build_brain

        return build_brain(config)
    except Exception:
        return None


def save_pr_description(
    description: str,
    branch: str,
    *,
    cwd: str | None = None,
) -> Path:
    out_dir = Path(cwd or Path.cwd()) / ".orchestrator" / branch
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "pr-description.md"
    out.write_text(description, encoding="utf-8")
    return out


__all__ = ["generate_pr_description", "save_pr_description"]
