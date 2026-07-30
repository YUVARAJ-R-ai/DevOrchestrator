"""Tests for the board/git adapter registry (docs/architecture-decoupling.md, backlog #5)."""

from __future__ import annotations

import pytest

from devorchestrator import registry
from devorchestrator.config import BoardConfig, BoardType, ConfigError, GitConfig, GitType
from devorchestrator.integrations.github_board import GithubBoard
from devorchestrator.registry import build_board, build_git, register_git


@pytest.fixture(autouse=True)
def _isolate_git_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test gets its own copy of the git registry so ``register_git`` calls
    in one test can't leak into another (module-level dict is otherwise shared)."""
    monkeypatch.setattr(registry, "_GIT_BACKENDS", dict(registry._GIT_BACKENDS))


def test_build_board_resolves_registered_github_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    config = BoardConfig(
        type=BoardType.github, url="https://github.com/acme/repo", token_env="GITHUB_TOKEN"
    )

    board = build_board(config, dev_name="yuvaraj")

    assert isinstance(board, GithubBoard)


def test_build_board_unknown_type_raises_config_error() -> None:
    config = BoardConfig(type=BoardType.plane, url="https://plane.local", token_env="X")

    with pytest.raises(ConfigError, match="no board backend registered"):
        build_board(config, dev_name="yuvaraj")


def test_build_git_unknown_type_raises_config_error() -> None:
    config = GitConfig(type=GitType.gitea, url="https://gitea.local", token_env="X")

    with pytest.raises(ConfigError, match="no git backend registered"):
        build_git(config, dev_name="yuvaraj")


def test_build_git_resolves_after_registration() -> None:
    register_git("gitea", lambda cfg, dev_name: object())  # minimal stand-in adapter
    config = GitConfig(type=GitType.gitea, url="https://gitea.local", token_env="X")

    # Open/Closed: registering a new backend needs no change to build_git itself.
    result = build_git(config, dev_name="yuvaraj")

    assert result is not None
