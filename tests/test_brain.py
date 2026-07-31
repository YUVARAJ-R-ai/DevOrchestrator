"""Brain tests (issue #9).

The acceptance criterion that matters most is negative: the brain must never
raise, whatever the provider does. Every failure mode below asserts we degrade
to fallback text instead of propagating an exception into the loop.

Uses ``asyncio.run`` rather than pytest-asyncio — the project's dev dependencies
are pytest + ruff only, and a test helper is not worth widening them.
"""

from __future__ import annotations

import asyncio

import pytest

from devorchestrator.sessions.brain import (
    BASE_URLS,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    FAILURE_BUDGET,
    Brain,
    BrainClient,
    build_brain,
)


def run(coro):
    return asyncio.run(coro)


class _Response:
    def __init__(self, text: str):
        message = type("M", (), {"content": text})()
        self.choices = [type("C", (), {"message": message})()]


class _FakeClient:
    """Minimal stand-in for AsyncOpenAI."""

    def __init__(self, *, text: str = "ok", error: Exception | None = None, delay: float = 0.0):
        self.calls = 0
        self._text, self._error, self._delay = text, error, delay
        self.chat = type("Chat", (), {"completions": self})()

    async def create(self, **kwargs):
        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error:
            raise self._error
        return _Response(self._text)


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_brain_satisfies_its_protocol():
    assert isinstance(Brain(api_key=None), BrainClient)


# ---------------------------------------------------------------------------
# Success + failure modes
# ---------------------------------------------------------------------------


def test_returns_provider_text_on_success():
    brain = Brain(client=_FakeClient(text="a real completion"))
    assert run(brain.complete("summarize this")) == "a real completion"
    assert brain.verified


def test_falls_back_when_no_api_key():
    brain = Brain(api_key=None)
    assert not brain.available
    assert "fallback" in run(brain.complete("write a PR description")).lower()


def test_falls_back_on_provider_error_without_raising():
    brain = Brain(client=_FakeClient(error=RuntimeError("502 upstream")), retries=0)
    assert "fallback" in run(brain.complete("anything")).lower()
    assert "502" in (brain.last_error or "")


def test_falls_back_on_timeout():
    brain = Brain(client=_FakeClient(delay=0.5), timeout=0.05, retries=0)
    assert "fallback" in run(brain.complete("anything")).lower()
    assert "timeout" in (brain.last_error or "")


def test_empty_completion_is_treated_as_failure():
    brain = Brain(client=_FakeClient(text="   "), retries=0)
    assert "fallback" in run(brain.complete("anything")).lower()


def test_retries_then_gives_up():
    client = _FakeClient(error=RuntimeError("boom"))
    run(Brain(client=client, retries=2).complete("anything"))
    assert client.calls == 3  # initial + 2 retries


def test_circuit_breaker_stops_calling_a_dead_provider():
    """Without this, every step of the loop would pay the full timeout again."""
    client = _FakeClient(error=RuntimeError("down"))
    brain = Brain(client=client, retries=0)

    for _ in range(FAILURE_BUDGET):
        run(brain.complete("x"))
    assert not brain.available

    calls_before = client.calls
    run(brain.complete("x"))
    assert client.calls == calls_before  # no further network attempts


def test_success_resets_the_failure_count():
    class Flaky(_FakeClient):
        async def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transient")
            return _Response("recovered")

    brain = Brain(client=Flaky(), retries=0)
    run(brain.complete("x"))
    assert run(brain.complete("x")) == "recovered"
    assert brain.available


def test_fallback_text_is_labelled_not_passed_off_as_generated():
    """Unattributed model-looking prose must never reach a PR description."""
    assert "provider unavailable" in run(Brain(api_key=None).complete("Summarize the diff"))


# ---------------------------------------------------------------------------
# Config wiring
# ---------------------------------------------------------------------------


def test_build_brain_without_config_is_fallback_only(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    brain = build_brain()
    assert brain.model == DEFAULT_MODEL
    assert "fallback only" in brain.describe()


@pytest.mark.parametrize("provider", ["siliconflow", "openrouter"])
def test_base_url_is_derived_from_the_provider_name(provider, monkeypatch):
    """config.BrainConfig carries no base_url, so Lane C maps it."""
    monkeypatch.delenv("DEVORCH_BRAIN_BASE_URL", raising=False)
    block = type("B", (), {"provider": provider, "model": "m", "token_env": "TOK"})()
    config = type("Cfg", (), {"brain": block})()
    assert build_brain(config).base_url == BASE_URLS[provider]


def test_base_url_override_wins(monkeypatch):
    monkeypatch.setenv("DEVORCH_BRAIN_BASE_URL", "http://localhost:8000/v1")
    assert build_brain().base_url == "http://localhost:8000/v1"


def test_api_key_is_read_from_the_configured_token_env(monkeypatch):
    monkeypatch.setenv("MY_BRAIN_KEY", "sk-test")
    block = type("B", (), {"provider": "siliconflow", "model": "m", "token_env": "MY_BRAIN_KEY"})()
    config = type("Cfg", (), {"brain": block})()
    # No openai extra installed in CI -> client is None; describe() says why.
    assert "fallback only" in build_brain(config).describe() or build_brain(config).available


# ---------------------------------------------------------------------------
# Provider/model coherence — issue #53
# ---------------------------------------------------------------------------


def test_default_model_uses_the_default_providers_naming_convention():
    """Model ids are provider-specific, and mismatching them fails *silently*.

    SiliconFlow serves ``deepseek-ai/DeepSeek-V4-Flash``; OpenRouter spells the
    same model ``deepseek/deepseek-v4-flash``. Pointing one at the other returns
    400 "Model does not exist", which ``Brain.complete`` swallows into the local
    fallback — so the loop keeps running and nobody learns the brain is dead.

    That is not hypothetical: the default was ``Nanbeige/Nanbeige2-16B-Chat``,
    a model SiliconFlow does not serve at all, and it had therefore never once
    produced real output. This pins the default to its provider's namespace.
    """
    assert DEFAULT_PROVIDER == "siliconflow"
    org, _, name = DEFAULT_MODEL.partition("/")
    assert name, f"{DEFAULT_MODEL!r} should be '<org>/<model>'"
    assert org == "deepseek-ai", (
        f"{DEFAULT_MODEL!r} is not a SiliconFlow id — 'deepseek/…' is the "
        "OpenRouter spelling and fails silently against SiliconFlow"
    )
