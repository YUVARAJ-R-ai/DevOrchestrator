from __future__ import annotations

import sys

import pytest

from devorchestrator.version_check import check_python_version


def test_version_above_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "version_info", (3, 13, 0, "final", 0))
    assert check_python_version((3, 12)) is True


def test_version_below_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "version_info", (3, 11, 0, "final", 0))
    assert check_python_version((3, 12)) is False


def test_version_equals_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "version_info", (3, 12, 0, "final", 0))
    assert check_python_version((3, 12)) is True
