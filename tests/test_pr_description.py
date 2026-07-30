from __future__ import annotations

from pathlib import Path

import pytest

from devorchestrator import pr_description
from devorchestrator.pr_description import generate_pr_description, save_pr_description


class _FakeBrain:
    """Stand-in BrainClient: available, returns a canned completion."""

    def __init__(self, text: str, available: bool = True) -> None:
        self._text = text
        self.available = available

    async def complete(self, prompt, *, system=None, max_tokens=1024, temperature=0.2):
        return self._text


def test_generate_without_git_log(tmp_path: Path) -> None:
    desc = generate_pr_description("feature/test", cwd=str(tmp_path))
    assert "Automated PR for branch `feature/test`" in desc
    assert "Gates pass" in desc


def test_generate_with_artifact(tmp_path: Path) -> None:
    artifact_dir = tmp_path / ".orchestrator" / "feature-x" / "artifact.md"
    artifact_dir.parent.mkdir(parents=True)
    artifact_dir.write_text("Implemented the frobnicator module.")
    desc = generate_pr_description("feature-x", cwd=str(tmp_path))
    assert "frobnicator" in desc


def test_save_pr_description_creates_file(tmp_path: Path) -> None:
    out = save_pr_description("test body", "feature-y", cwd=str(tmp_path))
    assert out.exists()
    assert out.read_text(encoding="utf-8") == "test body"
    assert ".orchestrator" in str(out)


def test_save_pr_description_defaults(tmp_path: Path) -> None:
    branch = "feat/something"
    out = save_pr_description("hello", branch, cwd=str(tmp_path))
    rel = out.relative_to(tmp_path / ".orchestrator")
    assert rel == Path(branch) / "pr-description.md"
    assert out.name == "pr-description.md"


def test_uses_brain_output_when_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pr_description, "_maybe_brain",
        lambda config: _FakeBrain("## Summary\nBrain-written PR body."),
    )
    desc = generate_pr_description("feature-x", cwd=str(tmp_path), config=object())
    assert desc == "## Summary\nBrain-written PR body."


def test_falls_back_to_mechanical_when_brain_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        pr_description, "_maybe_brain", lambda config: _FakeBrain("ignored", available=False)
    )
    desc = generate_pr_description("feature-x", cwd=str(tmp_path), config=object())
    assert "Automated PR for branch `feature-x`" in desc  # mechanical


def test_falls_back_when_brain_returns_its_fallback_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = "_Generated without the orchestrator brain (provider unavailable) — ..._"
    monkeypatch.setattr(pr_description, "_maybe_brain", lambda config: _FakeBrain(marker))
    desc = generate_pr_description("feature-x", cwd=str(tmp_path), config=object())
    assert "Automated PR for branch `feature-x`" in desc  # mechanical, not the marker


def test_no_config_means_mechanical(tmp_path: Path) -> None:
    # config=None must never call out — pure mechanical, no brain construction
    desc = generate_pr_description("feature-x", cwd=str(tmp_path))
    assert "Automated PR for branch `feature-x`" in desc
