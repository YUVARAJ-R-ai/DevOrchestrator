"""Tests for the configuration layer (backlog #5, #6, #7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from devorchestrator.config import ConfigError, Track, load_config

VALID = """\
name: yuvaraj
role: dev
agent: claude
board:
  type: plane
  url: https://plane.local
  token_env: PLANE_API_KEY
git:
  type: gitea
  url: https://gitea.local
  token_env: GITEA_TOKEN
"""


def _write(dir_: Path, text: str) -> Path:
    (dir_ / "devOrchestrator.yaml").write_text(text, encoding="utf-8")
    return dir_


def test_valid_minimal_config_loads(tmp_path: Path) -> None:
    _write(tmp_path, VALID)
    cfg = load_config(tmp_path, check_env=False)
    assert cfg.name == "yuvaraj"
    assert cfg.track is Track.oss
    # optional sections default sensibly
    assert cfg.brain is None
    assert cfg.mesh.db_path == ".orchestrator/mesh.db"


def test_missing_file_has_hint(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path)
    assert exc.value.hint is not None
    assert "devOrchestrator.yaml" in str(exc.value)


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, VALID + "surprise: true\n")
    with pytest.raises(ConfigError, match="failed validation"):
        load_config(tmp_path, check_env=False)


def test_track_mismatch_is_caught(tmp_path: Path) -> None:
    bad = VALID.replace("type: gitea", "type: azure_repos")
    _write(tmp_path, bad)
    with pytest.raises(ConfigError, match="same track"):
        load_config(tmp_path, check_env=False)


def test_azure_track_detected(tmp_path: Path) -> None:
    azure = VALID.replace("type: plane", "type: azure_boards").replace(
        "type: gitea", "type: azure_repos"
    )
    _write(tmp_path, azure)
    cfg = load_config(tmp_path, check_env=False)
    assert cfg.track is Track.azure


def test_missing_env_var_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLANE_API_KEY", raising=False)
    monkeypatch.delenv("GITEA_TOKEN", raising=False)
    _write(tmp_path, VALID)
    with pytest.raises(ConfigError, match="environment variable"):
        load_config(tmp_path, check_env=True)


def test_env_var_present_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLANE_API_KEY", "x")
    monkeypatch.setenv("GITEA_TOKEN", "y")
    _write(tmp_path, VALID)
    cfg = load_config(tmp_path, check_env=True)
    assert cfg.git.token_env == "GITEA_TOKEN"


def test_empty_file_has_hint(tmp_path: Path) -> None:
    _write(tmp_path, "")
    with pytest.raises(ConfigError, match="empty"):
        load_config(tmp_path, check_env=False)


def test_shipped_template_is_valid(tmp_path: Path) -> None:
    """The team-shared template in the repo root must always parse and load."""
    template = Path(__file__).parent.parent / "devOrchestrator.yaml.template"
    (tmp_path / "devOrchestrator.yaml").write_text(
        template.read_text(encoding="utf-8"), encoding="utf-8"
    )
    cfg = load_config(tmp_path, check_env=False)
    assert cfg.track is Track.oss
