from __future__ import annotations

import sys


def check_python_version(minimum: tuple[int, int] = (3, 12)) -> bool:
    """Return True if the running interpreter is at least ``minimum`` (major, minor)."""
    return sys.version_info[:2] >= minimum
