from __future__ import annotations

import os
from typing import Any

import httpx

from devorchestrator.contracts import Notifier


class HttpxNotifier(Notifier):
    """Send notifications via webhook URLs (Mattermost generic JSON format).

    Expects the webhook URL in an env var (name passed to constructor).
    """

    def __init__(
        self,
        webhook_env: str,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._webhook_url = os.environ.get(webhook_env, "")
        self._client = client or httpx.Client()
        self._webhook_env = webhook_env

    def _payload(self, message: str) -> dict[str, Any]:
        return {"text": message}

    def notify(self, message: str) -> None:
        if not self._webhook_url:
            from warnings import warn

            warn(
                f"${self._webhook_env} is not set — notification skipped.",
                stacklevel=2,
            )
            return

        response = self._client.post(self._webhook_url, json=self._payload(message))
        response.raise_for_status()


class TeamsNotifier(HttpxNotifier):
    """Send notifications via Teams webhook (Adaptive Card format)."""

    def _payload(self, message: str) -> dict[str, Any]:
        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": message,
                                "wrap": True,
                            }
                        ],
                    },
                }
            ],
        }


__all__ = ["HttpxNotifier", "TeamsNotifier"]
