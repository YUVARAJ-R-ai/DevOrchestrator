"""Prompt templates for the agent sessions (issue #8).

Templates are plain Markdown files next to this module so they can be edited
and reviewed without touching Python. ``$name`` placeholders are filled with
``string.Template.safe_substitute``, so an unknown placeholder renders literally
instead of raising mid-run — a prompt typo must never abort a live demo.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from string import Template

__all__ = ["ARTIFACT_SCHEMA", "PROMPTS_DIR", "load", "render"]

PROMPTS_DIR = Path(__file__).parent


@cache
def load(name: str) -> str:
    """Read a template by stem, e.g. ``load("research")``."""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"No prompt template named {name!r} in {PROMPTS_DIR}")
    return path.read_text(encoding="utf-8")


def render(name: str, **values: object) -> str:
    """Render a template with ``$placeholder`` substitution."""
    return Template(load(name)).safe_substitute(
        {key: "" if value is None else str(value) for key, value in values.items()}
    )


def _artifact_schema() -> str:
    """The exact format the research session must emit.

    Shared by the research prompt (produce this) and
    :class:`devorchestrator.sessions.artifact.ParsedArtifact` (parse this) —
    they must stay in step, so both reference this one file.
    """
    return load("artifact_schema")


ARTIFACT_SCHEMA = _artifact_schema()
