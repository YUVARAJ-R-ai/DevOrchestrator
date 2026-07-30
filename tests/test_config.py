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
    assert cfg.mesh.supabase_url == ""
    assert cfg.mesh.supabase_key_env == ""


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


def test_github_track_detected(tmp_path: Path) -> None:
    github = VALID.replace("type: plane", "type: github").replace("type: gitea", "type: github")
    _write(tmp_path, github)
    cfg = load_config(tmp_path, check_env=False)
    assert cfg.track is Track.github


def test_github_track_mismatch_with_gitea_is_caught(tmp_path: Path) -> None:
    bad = VALID.replace("type: plane", "type: github")  # git.type stays gitea
    _write(tmp_path, bad)
    with pytest.raises(ConfigError, match="same track"):
        load_config(tmp_path, check_env=False)


def test_project_number_is_optional_and_parses(tmp_path: Path) -> None:
    github = VALID.replace("type: plane", "type: github").replace("type: gitea", "type: github")
    github = github.replace(
        "token_env: PLANE_API_KEY", "token_env: PLANE_API_KEY\n  project_number: 10"
    )
    _write(tmp_path, github)
    cfg = load_config(tmp_path, check_env=False)
    assert cfg.board.project_number == 10


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
    assert cfg.track is Track.github
    assert cfg.board.project_number == 10


def test_notify_config_build_notifier_with_env(  # noqa: E501
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from devorchestrator.config import Config
    monkeypatch.setenv("TEAMS_HOOK", "https://hooks.example.com/team")
    cfg = Config.model_validate({
        "name": "test", "role": "dev", "agent": "claude",
        "board": {"type": "plane", "url": "https://plane.local", "token_env": "P"},
        "git": {"type": "gitea", "url": "https://gitea.local", "token_env": "G"},
        "notify": {"type": "teams", "webhook_env": "TEAMS_HOOK"},
    })
    notifier = cfg.notify.build_notifier()  # type: ignore[union-attr]
    assert notifier is not None
    assert notifier._webhook_url == "https://hooks.example.com/team"


def test_notify_config_build_notifier_without_env(  # noqa: E501
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("UNSET_HOOK", raising=False)
    from devorchestrator.config import Config
    cfg = Config.model_validate({
        "name": "test", "role": "dev", "agent": "claude",
        "board": {"type": "plane", "url": "https://plane.local", "token_env": "P"},
        "git": {"type": "gitea", "url": "https://gitea.local", "token_env": "G"},
        "notify": {"type": "mattermost", "webhook_env": "UNSET_HOOK"},
    })
    notifier = cfg.notify.build_notifier()  # type: ignore[union-attr]
    assert notifier is None
