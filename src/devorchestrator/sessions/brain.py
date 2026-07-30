"""The orchestrator brain — a cheap open model for text work (issue #9).

Nanbeige via SiliconFlow, spoken to through the OpenAI SDK's ``AsyncOpenAI``
with a custom ``base_url``, so switching providers is a config change rather
than a code change.

The brain is deliberately *not* where the intelligence lives. Claude Code
sessions read the codebase and write the code; the brain only does cheap text
transformation that needs no repository access — PR descriptions (#13), routing
decisions, mesh summaries.

**The load-bearing property of this module is that it cannot break the loop.**
:meth:`Brain.complete` never raises: on any provider error, timeout, or missing
key it returns deterministic local fallback text and flips :attr:`Brain.available`
to False. A flaky third-party API must degrade the output, never stop the demo.

``openai`` is an optional extra (``pip install devorchestrator[brain]``); without
it the brain simply runs in permanent fallback.
"""

from __future__ import annotations

import asyncio
import os
import textwrap
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "BASE_URLS",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "Brain",
    "BrainClient",
    "build_brain",
]

#: Provider name (``config.brain.provider``) -> OpenAI-compatible endpoint.
#: ``config.BrainConfig`` intentionally carries no ``base_url``, so the mapping
#: lives here rather than in the frozen config schema.
BASE_URLS: dict[str, str] = {
    "siliconflow": "https://api.siliconflow.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

DEFAULT_PROVIDER = "siliconflow"
DEFAULT_BASE_URL = BASE_URLS[DEFAULT_PROVIDER]
DEFAULT_MODEL = "Nanbeige/Nanbeige2-16B-Chat"
DEFAULT_TOKEN_ENV = "SILICONFLOW_API_KEY"

#: Short on purpose. A demo cannot stall a minute on an unresponsive provider —
#: falling back fast beats being right slowly.
DEFAULT_TIMEOUT_S = 20.0
DEFAULT_RETRIES = 1

#: After this many consecutive failures the brain stops calling out at all.
#: Without it, every step of the loop would pay the full timeout again.
FAILURE_BUDGET = 2


@runtime_checkable
class BrainClient(Protocol):
    """The narrow interface other lanes code against (Lane D's #13 uses it).

    Deliberately one method: the brain never touches the codebase, so
    string-in/string-out covers every current use. Implementations MUST NOT
    raise on provider failure — they degrade to a local fallback.
    """

    @property
    def available(self) -> bool: ...

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> str: ...


def _default_fallback(prompt: str, system: str | None = None) -> str:
    """Deterministic stand-in used when no live provider is reachable.

    Says so out loud on purpose: silently returning invented prose that looks
    model-generated would put unattributed text into a PR description.
    """
    head = textwrap.shorten(" ".join(prompt.split()), width=280, placeholder=" …")
    return (
        "_Generated without the orchestrator brain (provider unavailable) — "
        "this is a local fallback summary._\n\n"
        f"{head}"
    )


class Brain:
    """A :class:`BrainClient` implementation with a hard local fallback."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        provider: str = DEFAULT_PROVIDER,
        timeout: float = DEFAULT_TIMEOUT_S,
        retries: int = DEFAULT_RETRIES,
        fallback: Callable[[str, str | None], str] | None = None,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.provider = provider
        self.timeout = timeout
        self.retries = max(0, retries)
        self._api_key = api_key
        self._fallback = fallback or _default_fallback
        self._client = client
        self._failures = 0
        self._last_error: str | None = None
        #: True once a call has actually succeeded — lets the CLI distinguish
        #: "configured" from "verified working".
        self.verified = False

        if client is None and api_key:
            self._client = self._build_client()

    def _build_client(self) -> Any | None:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            self._last_error = "openai SDK not installed (pip install devorchestrator[brain])"
            return None
        try:
            return AsyncOpenAI(
                api_key=self._api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=0,  # retries are handled here, against our own budget
            )
        except Exception as exc:  # noqa: BLE001 — construction must not break startup
            self._last_error = f"{type(exc).__name__}: {exc}"
            return None

    # -- BrainClient -------------------------------------------------------

    @property
    def available(self) -> bool:
        """True when a client exists and the failure budget is not spent."""
        return self._client is not None and self._failures < FAILURE_BUDGET

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> str:
        """Return completion text — or fallback text. Never raises."""
        if not self.available:
            return self._fallback(prompt, system)

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        for attempt in range(self.retries + 1):
            try:
                response = await asyncio.wait_for(
                    self._client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    ),
                    timeout=self.timeout,
                )
                text = (response.choices[0].message.content or "").strip()
                if not text:
                    raise ValueError("provider returned an empty completion")
                self._failures = 0
                self.verified = True
                return text
            except TimeoutError:
                self._last_error = f"timeout after {self.timeout:.0f}s"
            except Exception as exc:  # noqa: BLE001 — any provider failure degrades
                self._last_error = f"{type(exc).__name__}: {exc}"

            if attempt < self.retries:
                await asyncio.sleep(0.5 * (attempt + 1))

        self._failures += 1
        return self._fallback(prompt, system)

    # -- diagnostics -------------------------------------------------------

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def describe(self) -> str:
        """One-line status for the CLI and the demo narration."""
        if self._client is None:
            reason = self._last_error or f"no API key (set {DEFAULT_TOKEN_ENV})"
            return f"fallback only — {reason}"
        if self._failures >= FAILURE_BUDGET:
            return (
                f"{self.provider}/{self.model} — disabled after "
                f"{self._failures} failures ({self._last_error})"
            )
        return f"{self.provider}/{self.model} ({'verified' if self.verified else 'configured'})"


def build_brain(config: Any | None = None, *, client: Any | None = None) -> Brain:
    """Construct the brain from a :class:`devorchestrator.config.Config`.

    ``config.brain`` is optional in the schema, so a config without it (or no
    config at all) yields a fallback-only brain rather than an error. The
    ``base_url`` is derived from the provider name via :data:`BASE_URLS`, and
    can be overridden with ``DEVORCH_BRAIN_BASE_URL`` for a self-hosted endpoint.
    """
    block = getattr(config, "brain", None) if config is not None else None

    def field(name: str, default: str) -> str:
        if block is None:
            return default
        value = getattr(block, name, None)
        if value is None and isinstance(block, dict):
            value = block.get(name)
        return str(value) if value else default

    provider = field("provider", DEFAULT_PROVIDER)
    token_env = field("token_env", DEFAULT_TOKEN_ENV)
    base_url = os.environ.get("DEVORCH_BRAIN_BASE_URL") or BASE_URLS.get(
        provider.lower(), DEFAULT_BASE_URL
    )

    return Brain(
        provider=provider,
        model=field("model", DEFAULT_MODEL),
        base_url=base_url,
        api_key=os.environ.get(token_env) or None,
        client=client,
    )
