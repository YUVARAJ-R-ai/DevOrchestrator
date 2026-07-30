from __future__ import annotations

from pathlib import Path

from devorchestrator.pr_description import generate_pr_description, save_pr_description


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
