from __future__ import annotations

import subprocess
from pathlib import Path


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


def generate_pr_description(
    branch: str,
    base: str = "dev",
    *,
    cwd: str | None = None,
) -> str:
    cwd = cwd or str(Path.cwd())
    commits = _git_log(base, cwd)
    artifact = _read_artifact(branch, cwd)

    lines = [f"## What\n\nAutomated PR for branch `{branch}`."]
    if commits:
        lines.append(f"\n### Commits\n```\n{commits}\n```")
    if artifact:
        lines.append(f"\n### Artifact\n\n{artifact[:500]}")

    lines.append(
        "\n### Quality\n"
        "- [ ] Gates pass (ruff + pytest)\n"
        "- [ ] TL review approved"
    )
    return "\n".join(lines)


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
