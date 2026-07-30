"""Tests for the GitHub board adapter (backlog #5)."""

from __future__ import annotations

import httpx
import pytest

from devorchestrator.contracts import IssueState, Priority
from devorchestrator.integrations.github_board import GithubBoard, _parse_owner_repo


def test_parse_owner_repo_from_https_url() -> None:
    assert _parse_owner_repo("https://github.com/YUVARAJ-R-ai/DevOrchestrator") == (
        "YUVARAJ-R-ai",
        "DevOrchestrator",
    )


def test_parse_owner_repo_from_ssh_url() -> None:
    assert _parse_owner_repo("git@github.com:YUVARAJ-R-ai/DevOrchestrator.git") == (
        "YUVARAJ-R-ai",
        "DevOrchestrator",
    )


def test_parse_owner_repo_rejects_non_github_url() -> None:
    with pytest.raises(ValueError, match="could not parse"):
        _parse_owner_repo("https://gitea.local/team/repo")


def _rest_transport(payload: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/issues")
        assert request.url.params["assignee"] == "yuvaraj"
        assert request.url.params["state"] == "open"
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


def test_fetch_via_rest_maps_issues_and_excludes_prs() -> None:
    payload = [
        {"number": 5, "title": "Fetch issues", "body": "desc", "html_url": "https://x/5"},
        {"number": 99, "title": "not an issue", "html_url": "https://x/99", "pull_request": {}},
    ]
    board = GithubBoard(
        url="https://github.com/acme/repo",
        token="t",
        dev_name="yuvaraj",
        client=httpx.Client(transport=_rest_transport(payload)),
    )

    issues = board.fetch_issues()

    assert len(issues) == 1
    assert issues[0].id == "5"
    assert issues[0].title == "Fetch issues"
    assert issues[0].assignee == "yuvaraj"
    # no project configured -> priority/estimate stay at contract defaults
    assert issues[0].priority is Priority.none
    assert issues[0].estimate is None


def _project_transport(nodes: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": {"repository": {"projectV2": {"items": {"nodes": nodes}}}}},
        )

    return httpx.MockTransport(handler)


def test_fetch_via_project_maps_priority_and_size_and_filters_by_assignee() -> None:
    nodes = [
        {
            "priorityField": {"name": "P0"},
            "sizeField": {"name": "M"},
            "content": {
                "number": 5,
                "title": "Fetch issues",
                "body": "",
                "url": "https://x/5",
                "state": "OPEN",
                "assignees": {"nodes": [{"login": "yuvaraj"}]},
            },
        },
        {
            "priorityField": None,
            "sizeField": None,
            "content": {
                "number": 6,
                "title": "not mine",
                "body": "",
                "url": "https://x/6",
                "state": "OPEN",
                "assignees": {"nodes": [{"login": "someoneelse"}]},
            },
        },
        {
            "priorityField": {"name": "P1"},
            "sizeField": {"name": "S"},
            "content": {
                "number": 7,
                "title": "closed already",
                "body": "",
                "url": "https://x/7",
                "state": "CLOSED",
                "assignees": {"nodes": [{"login": "yuvaraj"}]},
            },
        },
    ]
    board = GithubBoard(
        url="https://github.com/acme/repo",
        token="t",
        dev_name="yuvaraj",
        project_number=10,
        client=httpx.Client(transport=_project_transport(nodes)),
    )

    issues = board.fetch_issues()

    assert len(issues) == 1  # not-mine and closed both excluded
    assert issues[0].id == "5"
    assert issues[0].priority is Priority.urgent
    assert issues[0].estimate == 3


def test_move_issue_is_a_noop_without_project_number() -> None:
    board = GithubBoard(
        url="https://github.com/acme/repo",
        token="t",
        dev_name="yuvaraj",
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))),
    )

    # must not raise, must not hit the network
    board.move_issue("5", IssueState.ready)
