"""Configuration layer for DevOrchestrator (backlog #5, #6, #7).

Single Lane-A module (see docs/TEAM-WORKFLOW.md file list). It does three things:

1. **Schema** — a strict Pydantic v2 model of ``devOrchestrator.yaml``. Unknown
   keys are rejected so a typo fails loud at startup, never silently mid-run.
2. **Loading** — read the YAML from a directory, merge that directory's ``.env``,
   and validate the result.
3. **Fail-loud errors** — every failure raises :class:`ConfigError` carrying a
   one-line, actionable ``hint`` the developer can act on without reading source.

Secrets never live in the config: the ``token_env`` / ``webhook_env`` fields hold
the *name of an environment variable*. The loader resolves them and reports which
variable is unset — the values stay in ``.env``.

Public surface other lanes import:

    from devorchestrator.config import load_config, Config, ConfigError
"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from devorchestrator.notify import HttpxNotifier

CONFIG_FILENAME = "devOrchestrator.yaml"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class _Strict(BaseModel):
    """Base model: reject unknown keys, strip whitespace on strings."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Role(StrEnum):
    dev = "dev"
    tl = "tl"


class Agent(StrEnum):
    claude = "claude"
    agy = "agy"


class BoardType(StrEnum):
    plane = "plane"
    azure_boards = "azure_boards"


class GitType(StrEnum):
    gitea = "gitea"
    azure_repos = "azure_repos"


class NotifyType(StrEnum):
    mattermost = "mattermost"
    teams = "teams"


class Track(StrEnum):
    """Which backend family the config targets, derived from board/git type."""

    oss = "oss"
    azure = "azure"


class BoardConfig(_Strict):
    type: BoardType
    url: str
    token_env: str = Field(description="Name of the env var holding the board API token.")


class GitConfig(_Strict):
    type: GitType
    url: str
    token_env: str = Field(description="Name of the env var holding the git server token.")


class BrainConfig(_Strict):
    """External LLM used for lightweight text tasks (e.g. PR descriptions)."""

    provider: str = "openrouter"
    model: str = "deepseek/deepseek-v4-flash"
    token_env: str = Field(description="Name of the env var holding the provider API key.")


class NotifyConfig(_Strict):
    type: NotifyType
    webhook_env: str = Field(description="Name of the env var holding the notify webhook URL.")

    def build_notifier(self) -> HttpxNotifier | None:
        """Build a notifier from this config, or None if the webhook env is unset."""
        url = os.environ.get(self.webhook_env)
        if not url:
            return None
        from devorchestrator.notify import HttpxNotifier
        return HttpxNotifier(self.webhook_env)


class MeshConfig(_Strict):
    """Shared context mesh (Supabase/Postgres). Required fields: url + key_env."""

    supabase_url: str = ""
    supabase_key_env: str = ""


class Config(_Strict):
    """Top-level ``devOrchestrator.yaml`` model."""

    name: str = Field(description="The developer's name; used in mesh + notifications.")
    role: Role = Role.dev
    agent: Agent = Agent.claude

    board: BoardConfig
    git: GitConfig
    brain: BrainConfig | None = None
    notify: NotifyConfig | None = None
    mesh: MeshConfig = Field(default_factory=MeshConfig)

    autofix_retries: int = Field(
        default=2, ge=0,
        description="How many times the pipeline re-invokes the agent to fix failing checks.",
    )

    @property
    def track(self) -> Track:
        """Backend family, auto-detected from the board type.

        board/git types are expected to agree (both OSS or both Azure); the
        loader validates that. The board is treated as the source of truth.
        """
        return Track.azure if self.board.type is BoardType.azure_boards else Track.oss


# ---------------------------------------------------------------------------
# Loading + validation
# ---------------------------------------------------------------------------

# board.type <-> git.type must belong to the same backend family.
_OSS_GIT = {GitType.gitea}
_AZURE_GIT = {GitType.azure_repos}


class ConfigError(Exception):
    """Raised for any configuration problem, with an actionable hint.

    Attributes:
        hint: a short, imperative fix suggestion shown to the developer.
    """

    def __init__(self, message: str, hint: str | None = None) -> None:
        self.hint = hint
        super().__init__(message if hint is None else f"{message}\n  → {hint}")


def _format_validation_error(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        lines.append(f"    {loc}: {err['msg']}")
    return "\n".join(lines)


def _check_track_agrees(config: Config) -> None:
    """Board and git must target the same backend family."""
    board_is_azure = config.board.type is BoardType.azure_boards
    git_family = _AZURE_GIT if board_is_azure else _OSS_GIT
    if config.git.type not in git_family:
        expected = "azure_repos" if board_is_azure else "gitea"
        raise ConfigError(
            f"board.type is '{config.board.type.value}' but git.type is "
            f"'{config.git.type.value}' — they must be the same track.",
            hint=f"set git.type to '{expected}', or switch board.type to match your git server.",
        )


def _check_env_vars(config: Config) -> None:
    """Every referenced ``*_env`` variable must be present in the environment."""
    required: list[tuple[str, str]] = [
        ("board.token_env", config.board.token_env),
        ("git.token_env", config.git.token_env),
    ]
    if config.brain is not None:
        required.append(("brain.token_env", config.brain.token_env))
    if config.notify is not None:
        required.append(("notify.webhook_env", config.notify.webhook_env))

    missing = [(field_name, var) for field_name, var in required if not os.environ.get(var)]
    if missing:
        details = "; ".join(f"{field_name} -> ${var}" for field_name, var in missing)
        first_var = missing[0][1]
        raise ConfigError(
            f"required environment variable(s) not set: {details}.",
            hint=f"add them to your .env, e.g. `{first_var}=...`",
        )


def load_config(directory: str | Path | None = None, *, check_env: bool = True) -> Config:
    """Load and fully validate the config from ``directory`` (default: CWD).

    Args:
        directory: where to find ``devOrchestrator.yaml`` and ``.env``.
        check_env: when True, verify referenced env vars are set. Pass False in
            tests or dry runs that only inspect config shape.

    Raises:
        ConfigError: if the file is missing, malformed, invalid, on a mismatched
            track, or references an unset environment variable.
    """
    base = Path(directory) if directory is not None else Path.cwd()
    config_path = base / CONFIG_FILENAME

    if not config_path.is_file():
        raise ConfigError(
            f"no {CONFIG_FILENAME} found in {base}.",
            hint=f"copy devOrchestrator.yaml.template to {CONFIG_FILENAME} and fill it in.",
        )

    # Load .env from the same directory so token_env lookups resolve.
    load_dotenv(base / ".env")

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"{CONFIG_FILENAME} is not valid YAML: {exc}.",
            hint="check indentation and quoting; YAML is whitespace-sensitive.",
        ) from exc

    if raw is None:
        raise ConfigError(f"{CONFIG_FILENAME} is empty.", hint="fill it in from the template.")
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{CONFIG_FILENAME} must be a mapping at the top level, got {type(raw).__name__}.",
            hint="the file should start with `name:`, `role:`, etc. — not a list or scalar.",
        )

    try:
        config = Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(
            f"{CONFIG_FILENAME} failed validation:\n{_format_validation_error(exc)}",
            hint="fix the fields listed above; see docs/research.md for the full config example.",
        ) from exc

    _check_track_agrees(config)
    if check_env:
        _check_env_vars(config)

    return config
