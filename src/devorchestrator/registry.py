"""Adapter registry for board/git backends — Lane B (integrations).

See docs/architecture-decoupling.md for the original rationale (that doc also
proposed a mesh registry; dropped here since Lane D already shipped a working,
concrete Supabase mesh directly wired into cli.py — a second, competing mesh
resolution path would just be confusing dead code, not an improvement).

``pipeline.build_pipeline``'s own TODO says "instantiate concrete adapters
from config here" — this module is exactly that seam for board/git, ready for
Lane A to call in Wave-3 integration if useful. Not wired in yet; this file
does not change anything about how the pipeline currently runs.

A new board/git backend registers itself via ``register_board``/``register_git``
— no existing line here changes when one is added (Open/Closed). Unknown keys
fail loud via the same :class:`ConfigError` the rest of the config layer uses.
"""

from __future__ import annotations

from collections.abc import Callable

from devorchestrator.config import BoardConfig, ConfigError, GitConfig
from devorchestrator.contracts import BoardAdapter, GitAdapter

_BOARD_BACKENDS: dict[str, Callable[[BoardConfig, str], BoardAdapter]] = {}
_GIT_BACKENDS: dict[str, Callable[[GitConfig, str], GitAdapter]] = {}


def register_board(key: str, factory: Callable[[BoardConfig, str], BoardAdapter]) -> None:
    _BOARD_BACKENDS[key] = factory


def register_git(key: str, factory: Callable[[GitConfig, str], GitAdapter]) -> None:
    _GIT_BACKENDS[key] = factory


def build_board(config: BoardConfig, dev_name: str) -> BoardAdapter:
    try:
        factory = _BOARD_BACKENDS[config.type]
    except KeyError as exc:
        raise ConfigError(
            f"no board backend registered for board.type={config.type!r}.",
            hint=f"known: {sorted(_BOARD_BACKENDS)}",
        ) from exc
    return factory(config, dev_name)


def build_git(config: GitConfig, dev_name: str) -> GitAdapter:
    try:
        factory = _GIT_BACKENDS[config.type]
    except KeyError as exc:
        raise ConfigError(
            f"no git backend registered for git.type={config.type!r}.",
            hint=f"known: {sorted(_GIT_BACKENDS)}",
        ) from exc
    return factory(config, dev_name)


def _resolve_token(token_env: str) -> str:
    """Read a token env var. Presence is already validated by ``config._check_env_vars``."""
    import os

    return os.environ.get(token_env, "")


def _register_builtins() -> None:
    """Seed the registry with the board adapter shipped in this repo."""
    from devorchestrator.integrations.github_board import GithubBoard

    register_board(
        "github",
        lambda cfg, dev_name: GithubBoard(
            url=cfg.url,
            token=_resolve_token(cfg.token_env),
            dev_name=dev_name,
            project_number=cfg.project_number,
        ),
    )
    # git ("github") registers in devorchestrator.integrations.github_git (backlog #6).


_register_builtins()
