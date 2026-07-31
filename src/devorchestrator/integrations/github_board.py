"""GitHub board adapter (backlog #5) — Lane B (integrations).

Satisfies :class:`devorchestrator.contracts.BoardAdapter` against a GitHub
repo's Issues + Project v2 board. When ``project_number`` is configured, issues
are read via the Project v2 GraphQL API so the team's custom Priority/Size
fields map onto the shared ``contracts.Issue``; without it, falls back to the
plain Issues REST API (priority/estimate stay at their defaults).

The rest of the pipeline only ever sees ``contracts.Issue`` — it does not know
or care that the board happens to be GitHub.
"""

from __future__ import annotations

import re

import httpx

from devorchestrator.contracts import Issue, IssueState, Priority

_GITHUB_API = "https://api.github.com"
_GITHUB_GRAPHQL = "https://api.github.com/graphql"

# Board's Priority field has 3 options (P0/P1/P2); contracts.Priority has 5.
# Unmapped issues (no Priority set) default to Priority.none.
_PRIORITY_MAP = {"P0": Priority.urgent, "P1": Priority.high, "P2": Priority.medium}

# Board's Size field (XS/S/M/L/XL) mapped onto story points for contracts.Issue.estimate.
_SIZE_POINTS = {"XS": 1, "S": 2, "M": 3, "L": 5, "XL": 8}

# Board's Status options -> contracts.IssueState (see docs/TEAM-WORKFLOW.md board columns).
_STATE_TO_STATUS_OPTION = {
    IssueState.backlog: "Backlog",
    IssueState.ready: "Ready",
    IssueState.in_progress: "In progress",
    IssueState.in_review: "In review",
    IssueState.done: "Done",
}

_REPO_URL_RE = re.compile(r"github\.com[:/]+(?P<owner>[^/]+)/(?P<repo>[^/.]+)")


def _parse_owner_repo(url: str) -> tuple[str, str]:
    """Extract ``(owner, repo)`` from an HTTPS or SSH GitHub remote URL."""
    match = _REPO_URL_RE.search(url)
    if not match:
        raise ValueError(f"could not parse owner/repo from a GitHub url: {url!r}")
    return match["owner"], match["repo"]


class GithubBoard:
    """Fetches and moves issues on a GitHub repo's board.

    Constructed by the pipeline (Lane A) from ``Config.board`` + the resolved
    token; see ``contracts.BoardAdapter`` for the interface this satisfies.
    """

    def __init__(
        self,
        *,
        url: str,
        token: str,
        dev_name: str,
        project_number: int | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._owner, self._repo = _parse_owner_repo(url)
        self._dev_name = dev_name
        self._project_number = project_number
        self._client = client or httpx.Client(
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=15.0,
        )
        self._project_id_cache: str | None = None
        self._status_field_cache: tuple[str, dict[str, str]] | None = None

    def fetch_issues(self) -> list[Issue]:
        """Open issues assigned to ``dev_name``, enriched with Priority/Size if configured."""
        if self._project_number is not None:
            return self._fetch_via_project()
        return self._fetch_via_rest()

    def move_issue(self, issue_id: str, state: IssueState) -> None:
        """Move the issue's project Status field. No-op if no project is configured."""
        if self._project_number is None:
            return
        project_id = self._get_project_id()
        item_id = self._find_item_id(project_id, issue_id)
        if item_id is None:
            return
        status_field_id, options = self._get_status_field()
        option_id = options.get(_STATE_TO_STATUS_OPTION[state])
        if option_id is None:
            return
        self._set_single_select(project_id, item_id, status_field_id, option_id)

    # -- REST fallback (no project_number configured) -----------------------

    def _fetch_via_rest(self) -> list[Issue]:
        resp = self._client.get(
            f"{_GITHUB_API}/repos/{self._owner}/{self._repo}/issues",
            params={"assignee": self._dev_name, "state": "open"},
        )
        resp.raise_for_status()
        return [
            self._issue_from_rest(item) for item in resp.json() if "pull_request" not in item
        ]

    def _issue_from_rest(self, data: dict) -> Issue:
        return Issue(
            id=str(data["number"]),
            title=data["title"],
            description=data.get("body") or "",
            url=data["html_url"],
            assignee=self._dev_name,
        )

    # -- GraphQL + Project v2 (priority/size aware) --------------------------

    def _graphql(self, query: str, variables: dict) -> dict:
        resp = self._client.post(
            _GITHUB_GRAPHQL, json={"query": query, "variables": variables}
        )
        resp.raise_for_status()
        payload = resp.json()
        if "errors" in payload:
            errors = payload["errors"]
            # A token without the project scope fails here, not at the REST
            # calls, and GitHub's own message ("Resource not accessible by
            # personal access token") never mentions scopes — so say it plainly.
            if any(
                e.get("type") == "FORBIDDEN" or "not accessible" in str(e.get("message", ""))
                for e in errors
            ):
                raise RuntimeError(
                    "GitHub rejected the Projects (v2) query — your token is most likely "
                    "missing the 'project' (or 'read:project') scope, which is required "
                    "when board.project_number is set. Either add the scope to the token "
                    f"or remove board.project_number to use plain Issues. Raw error: {errors}"
                )
            raise RuntimeError(f"GitHub GraphQL error: {errors}")
        return payload["data"]

    def _fetch_via_project(self) -> list[Issue]:
        query = """
        query($owner: String!, $repo: String!, $number: Int!) {
          repository(owner: $owner, name: $repo) {
            projectV2(number: $number) {
              items(first: 100) {
                nodes {
                  priorityField: fieldValueByName(name: "Priority") {
                    ... on ProjectV2ItemFieldSingleSelectValue { name }
                  }
                  sizeField: fieldValueByName(name: "Size") {
                    ... on ProjectV2ItemFieldSingleSelectValue { name }
                  }
                  content {
                    ... on Issue {
                      number
                      title
                      body
                      url
                      state
                      assignees(first: 5) { nodes { login } }
                    }
                  }
                }
              }
            }
          }
        }
        """
        data = self._graphql(
            query,
            {"owner": self._owner, "repo": self._repo, "number": self._project_number},
        )
        nodes = data["repository"]["projectV2"]["items"]["nodes"]

        issues: list[Issue] = []
        for node in nodes:
            content = node.get("content")
            if not content or content.get("state") != "OPEN":
                continue
            assignees = [a["login"] for a in content["assignees"]["nodes"]]
            if self._dev_name not in assignees:
                continue
            priority_name = (node.get("priorityField") or {}).get("name")
            size_name = (node.get("sizeField") or {}).get("name")
            issues.append(
                Issue(
                    id=str(content["number"]),
                    title=content["title"],
                    description=content.get("body") or "",
                    priority=_PRIORITY_MAP.get(priority_name, Priority.none),
                    estimate=_SIZE_POINTS.get(size_name),
                    url=content["url"],
                    assignee=self._dev_name,
                )
            )
        return issues

    # -- move_issue helpers ---------------------------------------------------

    def _get_project_id(self) -> str:
        if self._project_id_cache is not None:
            return self._project_id_cache
        query = """
        query($owner: String!, $repo: String!, $number: Int!) {
          repository(owner: $owner, name: $repo) {
            projectV2(number: $number) { id }
          }
        }
        """
        data = self._graphql(
            query,
            {"owner": self._owner, "repo": self._repo, "number": self._project_number},
        )
        project_id = data["repository"]["projectV2"]["id"]
        self._project_id_cache = project_id
        return project_id

    def _get_status_field(self) -> tuple[str, dict[str, str]]:
        if self._status_field_cache is not None:
            return self._status_field_cache
        query = """
        query($id: ID!) {
          node(id: $id) {
            ... on ProjectV2 {
              fields(first: 30) {
                nodes {
                  ... on ProjectV2SingleSelectField { id name options { id name } }
                }
              }
            }
          }
        }
        """
        data = self._graphql(query, {"id": self._get_project_id()})
        for field in data["node"]["fields"]["nodes"]:
            if field.get("name") == "Status":
                options = {opt["name"]: opt["id"] for opt in field["options"]}
                result = (field["id"], options)
                self._status_field_cache = result
                return result
        raise RuntimeError("project board has no 'Status' field")

    def _find_item_id(self, project_id: str, issue_id: str) -> str | None:
        query = """
        query($id: ID!) {
          node(id: $id) {
            ... on ProjectV2 {
              items(first: 100) {
                nodes { id content { ... on Issue { number } } }
              }
            }
          }
        }
        """
        data = self._graphql(query, {"id": project_id})
        for item in data["node"]["items"]["nodes"]:
            content = item.get("content")
            if content and str(content["number"]) == str(issue_id):
                return item["id"]
        return None

    def _set_single_select(
        self, project_id: str, item_id: str, field_id: str, option_id: str
    ) -> None:
        mutation = """
        mutation($p: ID!, $i: ID!, $f: ID!, $o: String!) {
          updateProjectV2ItemFieldValue(input: {
            projectId: $p, itemId: $i, fieldId: $f,
            value: { singleSelectOptionId: $o }
          }) { projectV2Item { id } }
        }
        """
        self._graphql(mutation, {"p": project_id, "i": item_id, "f": field_id, "o": option_id})
