from __future__ import annotations

from devorchestrator.contracts import Mesh


def warn_on_overlap(
    mesh: Mesh, modules: list[str], *, self_dev: str | None = None, limit: int = 5
) -> list[str]:
    """Warn about *other* devs working in *modules*.

    Args:
        mesh: the shared context mesh to query.
        modules: module names to check for in-flight activity.
        self_dev: the current developer, excluded from the results. The caller
            has usually just emitted a ``task_started`` event for these very
            modules, so without this the first thing they see is a warning that
            they are colliding with themselves. ``Pipeline._warn_on_conflicts``
            has always excluded self; the two disagreed until #50.
        limit: stop after this many warnings.

    Returns human-readable warning messages (one per overlapping dev+module).
    Non-blocking — the caller decides whether to proceed.
    """
    seen: set[tuple[str, str]] = set()
    warnings: list[str] = []
    for module in modules:
        for act in mesh.who_is_touching(module):
            if self_dev is not None and act.dev == self_dev:
                continue
            key = (act.dev, module)
            if key in seen:
                continue
            seen.add(key)
            warnings.append(
                f"[yellow]⚠ {act.dev}[/] is in [cyan]{module}[/] "
                f"([dim]{act.branch}[/], since {act.ts})"
            )
            if len(warnings) >= limit:
                return warnings
    return warnings


__all__ = ["warn_on_overlap"]
