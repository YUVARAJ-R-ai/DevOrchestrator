from __future__ import annotations

from devorchestrator.contracts import Mesh


def warn_on_overlap(mesh: Mesh, modules: list[str], *, limit: int = 5) -> list[str]:
    """Check if *modules* have recent activity by devs other than the caller.

    Returns human-readable warning messages (one per overlapping dev+module).
    Non-blocking — caller decides whether to proceed.
    """
    seen: set[tuple[str, str]] = set()
    warnings: list[str] = []
    for module in modules:
        for act in mesh.who_is_touching(module):
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
