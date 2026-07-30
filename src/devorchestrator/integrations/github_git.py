"""GitHub git server adapter (backlog #6) — Lane B (integrations).

Satisfies :class:`devorchestrator.contracts.GitAdapter` against GitHub Repos +
Pull Requests. Branch naming and the "Closes #N" PR-body convention are lifted
directly from the vendored ``.claude/skills/start-task/SKILL.md`` (Phase 5:
``feature/issue-N-slug`` branch names; Phase 10: PR body links the issue) —
wrapped here, not rewritten, per this issue's acceptance criteria.

The rest of the pipeline (``pipeline.py``, ``review.py``) only ever sees
``contracts.BranchRef`` / ``contracts.PullRequest`` — it does not know or care
that the git server happens to be GitHub.
"""

from __future__ import annotations

import re

import httpx

from devorchestrator.contracts import BranchRef, Issue, MergeStrategy, PullRequest

_GITHUB_API = "https://api.github.com"

_MERGE_METHOD = {
    MergeStrategy.merge: "merge",
    MergeStrategy.squash: "squash",
    MergeStrategy.rebase: "rebase",
}

_REPO_URL_RE = re.compile(r"github\.com[:/]+(?P<owner>[^/]+)/(?P<repo>[^/.]+)")


def _parse_owner_repo(url: str) -> tuple[str, str]:
    """Extract ``(owner, repo)`` from an HTTPS or SSH GitHub remote URL."""
    match = _REPO_URL_RE.search(url)
    if not match:
        raise ValueError(f"could not parse owner/repo from a GitHub url: {url!r}")
    return match["owner"], match["repo"]


class GithubGit:
    """Creates branches, opens/merges PRs, and serves the TL review flow on GitHub.

    Constructed by the pipeline (Lane A) from ``Config.git`` + the resolved
    token; see ``contracts.GitAdapter`` for the interface this satisfies.
    """

    def __init__(
        self,
        *,
        url: str,
        token: str,
        reviewer: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._owner, self._repo = _parse_owner_repo(url)
        self._reviewer = reviewer
        self._client = client or httpx.Client(
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=15.0,
        )

    # -- pipeline flow (start / pr) ------------------------------------------

    def create_branch(self, issue: Issue, base: str = "dev") -> BranchRef:
        """Create ``feature/{issue.branch_slug()}`` off ``base`` (start-task Phase 5)."""
        base_ref = self._client.get(
            f"{_GITHUB_API}/repos/{self._owner}/{self._repo}/git/ref/heads/{base}"
        )
        base_ref.raise_for_status()
        base_sha = base_ref.json()["object"]["sha"]

        branch_name = f"feature/{issue.branch_slug()}"
        resp = self._client.post(
            f"{_GITHUB_API}/repos/{self._owner}/{self._repo}/git/refs",
            json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        )
        resp.raise_for_status()

        return BranchRef(
            name=branch_name,
            issue_id=issue.id,
            base=base,
            url=f"https://github.com/{self._owner}/{self._repo}/tree/{branch_name}",
        )

    def open_pr(self, branch: BranchRef, title: str, body: str) -> PullRequest:
        """Open the PR; body links the issue via "Closes #N" (start-task Phase 10)."""
        full_body = body
        if branch.issue_id and f"#{branch.issue_id}" not in body:
            full_body = f"Closes #{branch.issue_id}\n\n{body}"

        resp = self._client.post(
            f"{_GITHUB_API}/repos/{self._owner}/{self._repo}/pulls",
            json={
                "title": title,
                "head": branch.name,
                "base": branch.base,
                "body": full_body,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        number = data["number"]

        if self._reviewer:
            # Best-effort: a missing/invalid reviewer must not fail PR creation.
            self._client.post(
                f"{_GITHUB_API}/repos/{self._owner}/{self._repo}/pulls/{number}/requested_reviewers",
                json={"reviewers": [self._reviewer]},
            )

        return PullRequest(
            number=number,
            title=title,
            url=data["html_url"],
            branch=branch.name,
            base=branch.base,
        )

    def merge_pr(self, pr: PullRequest, strategy: MergeStrategy) -> None:
        resp = self._client.put(
            f"{_GITHUB_API}/repos/{self._owner}/{self._repo}/pulls/{pr.number}/merge",
            json={"merge_method": _MERGE_METHOD[strategy]},
        )
        resp.raise_for_status()

    # -- review flow (TL approval gate) --------------------------------------

    def list_open_prs(self, assignee: str | None = None) -> list[PullRequest]:
        """Open PRs, optionally filtered to those where ``assignee`` is a requested reviewer.

        The contract's parameter is named ``assignee`` (fixed by the frozen
        ``contracts.GitAdapter``), but ``review.py`` uses it for "PRs awaiting
        this reviewer" — the correct semantic is GitHub's requested-reviewer
        list, not the ``assignees`` field, so that is what gets filtered here.
        """
        resp = self._client.get(
            f"{_GITHUB_API}/repos/{self._owner}/{self._repo}/pulls",
            params={"state": "open"},
        )
        resp.raise_for_status()
        prs = []
        for data in resp.json():
            if assignee is not None:
                requested = [r["login"] for r in data.get("requested_reviewers", [])]
                if assignee not in requested:
                    continue
            prs.append(
                PullRequest(
                    number=data["number"],
                    title=data["title"],
                    url=data["html_url"],
                    branch=data["head"]["ref"],
                    base=data["base"]["ref"],
                )
            )
        return prs

    def get_diff(self, pr: PullRequest) -> str:
        resp = self._client.get(
            f"{_GITHUB_API}/repos/{self._owner}/{self._repo}/pulls/{pr.number}",
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        resp.raise_for_status()
        return resp.text

    def get_ci_status(self, pr: PullRequest) -> str:
        """Aggregate check-run conclusions on the PR's head commit into one word."""
        pr_resp = self._client.get(
            f"{_GITHUB_API}/repos/{self._owner}/{self._repo}/pulls/{pr.number}"
        )
        pr_resp.raise_for_status()
        sha = pr_resp.json()["head"]["sha"]

        runs_resp = self._client.get(
            f"{_GITHUB_API}/repos/{self._owner}/{self._repo}/commits/{sha}/check-runs"
        )
        runs_resp.raise_for_status()
        runs = runs_resp.json().get("check_runs", [])

        if not runs:
            return "unknown"
        if any(r["status"] != "completed" for r in runs):
            return "pending"
        if any(r.get("conclusion") not in ("success", "skipped", "neutral") for r in runs):
            return "failing"
        return "passing"

    def comment_pr(self, pr: PullRequest, body: str) -> None:
        resp = self._client.post(
            f"{_GITHUB_API}/repos/{self._owner}/{self._repo}/issues/{pr.number}/comments",
            json={"body": body},
        )
        resp.raise_for_status()
