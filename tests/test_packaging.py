"""Guards against `uv.lock` drifting out of sync with `pyproject.toml`.

This exists because of a real, silent failure. `libtmux` was moved into core
``dependencies`` in ``pyproject.toml``, but nobody re-ran ``uv lock`` — so the
lock still carried it only as a member of the ``agent`` extra, not as a
dependency of ``devorchestrator`` itself. ``uv sync`` installs the default
group, correctly skipped it, and every developer who set up from the lock ended
up without libtmux.

Nothing failed. ``tmux_available()`` returned False, the real-tmux integration
tests in ``test_sessions.py`` skipped, and the suite went green — while the
split-pane path they cover was completely unexercised. A genuine bug (impl
overwriting the research pane) survived a full test run that way.

A skipped test is not a passing test. These assertions make lock drift a red
build instead of a quiet gap in coverage.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = PROJECT_ROOT / "pyproject.toml"
UV_LOCK = PROJECT_ROOT / "uv.lock"

#: Distribution name → the module you actually import. Only needed where they
#: differ; anything else is assumed to match after normalisation.
_IMPORT_NAMES = {
    "python-dotenv": "dotenv",
    "pyyaml": "yaml",
}


def _requirement_name(spec: str) -> str:
    """``"libtmux>=0.35"`` → ``"libtmux"``. Normalised the way PEP 503 does."""
    for separator in (">=", "<=", "==", "!=", "~=", ">", "<", "[", ";"):
        spec = spec.split(separator, 1)[0]
    return spec.strip().lower().replace("_", "-").replace(".", "-")


@pytest.fixture(scope="module")
def core_dependencies() -> list[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return [_requirement_name(d) for d in data["project"]["dependencies"]]


@pytest.fixture(scope="module")
def locked_project_dependencies() -> set[str]:
    """What the lock believes ``devorchestrator`` itself depends on.

    Deliberately *not* "every package in the lock" — that is the exact
    distinction the original bug turned on. libtmux was present in the lock as a
    transitive/extra entry the whole time; it just was not a dependency of this
    project, which is what ``uv sync`` installs.
    """
    data = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    for package in data["package"]:
        if package["name"] == "devorchestrator":
            return {_requirement_name(d["name"]) for d in package.get("dependencies", [])}
    pytest.fail("no 'devorchestrator' package entry in uv.lock")
    return set()  # unreachable; keeps the return type honest


def test_uv_lock_is_not_stale(core_dependencies, locked_project_dependencies):
    """Every core dependency must be locked as a dependency of this project.

    If this fails, run ``uv lock`` and commit the result. Editing
    ``pyproject.toml``'s ``dependencies`` without re-locking means ``uv sync``
    silently installs less than the project declares.
    """
    missing = sorted(set(core_dependencies) - locked_project_dependencies)
    assert not missing, (
        f"uv.lock is stale — {missing} are in pyproject's [project.dependencies] "
        f"but not locked as dependencies of devorchestrator. Run `uv lock`."
    )


def test_libtmux_is_a_core_dependency(core_dependencies):
    """Regression guard for the specific drift described in the module docstring.

    Visible tmux panes are the product's core interaction model, not an optional
    nicety — the dev watching the agent work *is* the feature. libtmux belongs in
    core dependencies, and demoting it back to an extra should be a deliberate,
    loud decision rather than a quiet edit.
    """
    assert "libtmux" in core_dependencies


def test_every_core_dependency_is_actually_importable(core_dependencies):
    """The installed environment matches what the project declares.

    Catches the developer-facing half of the bug: a lock that is correct on disk
    but an environment that predates it. Fix by running ``uv sync``.
    """
    import importlib.util

    missing = [
        name
        for name in core_dependencies
        if importlib.util.find_spec(_IMPORT_NAMES.get(name, name.replace("-", "_"))) is None
    ]
    assert not missing, f"declared but not installed: {missing}. Run `uv sync`."
