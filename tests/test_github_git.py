"""Tests for the GitHub git adapter (backlog #6)."""

from __future__ import annotations

import httpx
import pytest

from devorchestrator.contracts import BranchRef, Issue, MergeStrategy, PullRequest
from devorchestrator.integrations.github_git import GithubGit, _parse_owner_repo


def test_parse_owner_repo_from_https_url() -> None:
    assert _parse_owner_repo("https://github.com/YUVARAJ-R-ai/DevOrchestrator") == (
        "YUVARAJ-R-ai",
        "DevOrchestrator",
    )


def test_parse_owner_repo_rejects_non_github_url() -> None:
    with pytest.raises(ValueError, match="could not parse"):
        _parse_owner_repo("https://gitea.local/team/repo")


def _transport(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_create_branch_uses_start_task_naming_and_base_sha() -> None:
    issue = Issue(id="6", title="GitHub branch + PR creation")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/git/ref/heads/dev"):
            return httpx.Response(200, json={"object": {"sha": "abc123"}})
        if request.url.path.endswith("/git/refs"):
            import json

            body = json.loads(request.content)
            assert body["sha"] == "abc123"
            assert body["ref"] == f"refs/heads/feature/{issue.branch_slug()}"
            return httpx.Response(201, json={})
        raise AssertionError(f"unexpected request: {request.url}")

    git = GithubGit(url="https://github.com/acme/repo", token="t", client=_transport(handler))

    branch = git.create_branch(issue, base="dev")

    assert branch.name == f"feature/{issue.branch_slug()}"
    assert branch.issue_id == "6"
    assert branch.base == "dev"


def test_create_branch_resets_existing_branch_instead_of_crashing() -> None:
    """Re-run case: the branch already exists (422). Instead of crashing, reset
    it to base via PATCH so re-runs are idempotent."""
    issue = Issue(id="30", title="demo")
    patched = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/git/ref/heads/dev"):
            return httpx.Response(200, json={"object": {"sha": "basesha"}})
        if request.url.path.endswith("/git/refs") and request.method == "POST":
            return httpx.Response(422, json={"message": "Reference already exists"})
        if "/git/refs/heads/" in request.url.path and request.method == "PATCH":
            import json

            body = json.loads(request.content)
            patched["sha"] = body["sha"]
            patched["force"] = body["force"]
            return httpx.Response(200, json={})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    git = GithubGit(url="https://github.com/acme/repo", token="t", client=_transport(handler))

    branch = git.create_branch(issue, base="dev")

    assert branch.name == f"feature/{issue.branch_slug()}"
    assert patched == {"sha": "basesha", "force": True}  # existing branch reset to base


def test_open_pr_links_issue_and_requests_reviewer() -> None:
    branch = BranchRef(name="feature/issue-6-x", issue_id="6", base="dev")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/pulls"):
            import json

            body = json.loads(request.content)
            assert body["head"] == "feature/issue-6-x"
            assert body["base"] == "dev"
            assert "Closes #6" in body["body"]
            return httpx.Response(
                201,
                json={"number": 42, "html_url": "https://github.com/acme/repo/pull/42"},
            )
        if request.url.path.endswith("/requested_reviewers"):
            import json

            body = json.loads(request.content)
            assert body["reviewers"] == ["tharun"]
            return httpx.Response(201, json={})
        raise AssertionError(f"unexpected request: {request.url}")

    git = GithubGit(
        url="https://github.com/acme/repo",
        token="t",
        reviewer="tharun",
        client=_transport(handler),
    )

    pr = git.open_pr(branch, title="Fix thing", body="body text")

    assert pr.number == 42
    assert pr.url == "https://github.com/acme/repo/pull/42"
    assert pr.branch == "feature/issue-6-x"
    assert any(p.endswith("/requested_reviewers") for p in calls)


def test_open_pr_does_not_duplicate_closes_link() -> None:
    branch = BranchRef(name="feature/issue-6-x", issue_id="6", base="dev")

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        assert body["body"].count("#6") == 1
        return httpx.Response(
            201, json={"number": 1, "html_url": "https://github.com/acme/repo/pull/1"}
        )

    git = GithubGit(url="https://github.com/acme/repo", token="t", client=_transport(handler))

    git.open_pr(branch, title="t", body="already mentions #6 in the body")


def test_merge_pr_maps_strategy_to_merge_method() -> None:
    pr = PullRequest(number=1, title="t", url="https://x", branch="b", base="dev")

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        assert request.method == "PUT"
        body = json.loads(request.content)
        assert body["merge_method"] == "squash"
        return httpx.Response(200, json={})

    git = GithubGit(url="https://github.com/acme/repo", token="t", client=_transport(handler))

    git.merge_pr(pr, MergeStrategy.squash)


def test_list_open_prs_filters_by_requested_reviewer() -> None:
    payload = [
        {
            "number": 1,
            "title": "mine",
            "html_url": "https://x/1",
            "head": {"ref": "feature/a"},
            "base": {"ref": "dev"},
            "requested_reviewers": [{"login": "tharun"}],
        },
        {
            "number": 2,
            "title": "not mine",
            "html_url": "https://x/2",
            "head": {"ref": "feature/b"},
            "base": {"ref": "dev"},
            "requested_reviewers": [{"login": "someone-else"}],
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    git = GithubGit(url="https://github.com/acme/repo", token="t", client=_transport(handler))

    prs = git.list_open_prs(assignee="tharun")

    assert len(prs) == 1
    assert prs[0].number == 1
    assert prs[0].branch == "feature/a"


def test_list_open_prs_no_filter_returns_all() -> None:
    payload = [
        {
            "number": 1, "title": "a", "html_url": "https://x/1",
            "head": {"ref": "feature/a"}, "base": {"ref": "dev"},
            "requested_reviewers": [],
        },
    ]

    git = GithubGit(
        url="https://github.com/acme/repo", token="t",
        client=_transport(lambda r: httpx.Response(200, json=payload)),
    )

    prs = git.list_open_prs()

    assert len(prs) == 1


def test_get_diff_uses_diff_media_type() -> None:
    pr = PullRequest(number=1, title="t", url="https://x", branch="b", base="dev")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept"] == "application/vnd.github.v3.diff"
        return httpx.Response(200, text="--- a/f\n+++ b/f\n")

    git = GithubGit(url="https://github.com/acme/repo", token="t", client=_transport(handler))

    diff = git.get_diff(pr)

    assert "--- a/f" in diff


def test_get_ci_status_aggregates_check_runs() -> None:
    pr = PullRequest(number=1, title="t", url="https://x", branch="b", base="dev")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pulls/1"):
            return httpx.Response(200, json={"head": {"sha": "deadbeef"}})
        if request.url.path.endswith("/check-runs"):
            return httpx.Response(
                200,
                json={"check_runs": [
                    {"status": "completed", "conclusion": "success"},
                    {"status": "completed", "conclusion": "success"},
                ]},
            )
        raise AssertionError(f"unexpected request: {request.url}")

    git = GithubGit(url="https://github.com/acme/repo", token="t", client=_transport(handler))

    assert git.get_ci_status(pr) == "passing"


def test_get_ci_status_pending_while_running() -> None:
    pr = PullRequest(number=1, title="t", url="https://x", branch="b", base="dev")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pulls/1"):
            return httpx.Response(200, json={"head": {"sha": "deadbeef"}})
        return httpx.Response(
            200, json={"check_runs": [{"status": "in_progress", "conclusion": None}]}
        )

    git = GithubGit(url="https://github.com/acme/repo", token="t", client=_transport(handler))

    assert git.get_ci_status(pr) == "pending"


def test_get_ci_status_failing_on_failure_conclusion() -> None:
    pr = PullRequest(number=1, title="t", url="https://x", branch="b", base="dev")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pulls/1"):
            return httpx.Response(200, json={"head": {"sha": "deadbeef"}})
        return httpx.Response(
            200, json={"check_runs": [{"status": "completed", "conclusion": "failure"}]}
        )

    git = GithubGit(url="https://github.com/acme/repo", token="t", client=_transport(handler))

    assert git.get_ci_status(pr) == "failing"


def test_get_ci_status_unknown_with_no_check_runs() -> None:
    pr = PullRequest(number=1, title="t", url="https://x", branch="b", base="dev")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pulls/1"):
            return httpx.Response(200, json={"head": {"sha": "deadbeef"}})
        return httpx.Response(200, json={"check_runs": []})

    git = GithubGit(url="https://github.com/acme/repo", token="t", client=_transport(handler))

    assert git.get_ci_status(pr) == "unknown"


def test_comment_pr_posts_to_issues_comments_endpoint() -> None:
    pr = PullRequest(number=1, title="t", url="https://x", branch="b", base="dev")

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        assert request.url.path.endswith("/issues/1/comments")
        body = json.loads(request.content)
        assert body["body"] == "please fix X"
        return httpx.Response(201, json={})

    git = GithubGit(url="https://github.com/acme/repo", token="t", client=_transport(handler))

    git.comment_pr(pr, "please fix X")
