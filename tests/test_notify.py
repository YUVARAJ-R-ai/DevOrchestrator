from __future__ import annotations

import warnings

from devorchestrator.notify import HttpxNotifier, TeamsNotifier
from tests.mocks import MockHttpxClient


def test_notify_sends_post() -> None:
    mock = MockHttpxClient(status_code=200)
    notifier = HttpxNotifier("WEBHOOK_URL", client=mock)  # type: ignore[arg-type]
    notifier._webhook_url = "https://hooks.example.com/hook"
    notifier.notify("Hello from Lane D")
    assert len(mock.posts) == 1
    url, payload = mock.posts[0]
    assert url == "https://hooks.example.com/hook"
    assert "Hello from Lane D" in payload.get("text", "")


def test_notify_skips_when_no_url() -> None:
    mock = MockHttpxClient()
    notifier = HttpxNotifier("UNSET_VAR", client=mock)  # type: ignore[arg-type]
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        notifier.notify("skip me")
    assert len(mock.posts) == 0
    assert any("not set" in str(msg.message) for msg in w)


def test_teams_notifier_sends_adaptive_card() -> None:
    mock = MockHttpxClient(status_code=200)
    notifier = TeamsNotifier("WEBHOOK_URL", client=mock)  # type: ignore[arg-type]
    notifier._webhook_url = "https://hooks.example.com/teams"
    notifier.notify("Hello from Lane D")
    assert len(mock.posts) == 1
    url, payload = mock.posts[0]
    assert url == "https://hooks.example.com/teams"
    assert payload["type"] == "message"
    attachments = payload["attachments"]
    assert len(attachments) == 1
    content = attachments[0]["content"]
    assert content["type"] == "AdaptiveCard"
    assert content["body"][0]["text"] == "Hello from Lane D"


def test_teams_notifier_satisfies_protocol() -> None:
    from devorchestrator.contracts import Notifier

    mock = MockHttpxClient()
    assert isinstance(TeamsNotifier("WEBHOOK_URL", client=mock), Notifier)  # type: ignore[arg-type]


def test_notifier_satisfies_protocol() -> None:
    from devorchestrator.contracts import Notifier

    mock = MockHttpxClient()
    assert isinstance(HttpxNotifier("WEBHOOK_URL", client=mock), Notifier)  # type: ignore[arg-type]
