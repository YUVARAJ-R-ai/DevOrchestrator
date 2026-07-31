"""Tests for `devorchestrator init`'s scaffolding + connection-test helpers.

docs/GAPS.md flagged that `init` used to just validate an existing config —
it never scaffolded devOrchestrator.yaml/.env or tested a real connection,
despite the README promising exactly that. These test the fix.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from devorchestrator.cli import (
    _looks_like_placeholder,
    _required_env_vars,
    _scaffold_env,
    _scaffold_yaml,
    _test_github_connection,
)
from devorchestrator.config import Config


def test_scaffold_yaml_writes_github_typed_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = iter(["yuvaraj", "https://github.com/acme/repo", "", "n"])
    monkeypatch.setattr("typer.prompt", lambda *a, **kw: next(answers))
    monkeypatch.setattr("typer.confirm", lambda *a, **kw: next(answers) == "y")

    path = tmp_path / "devOrchestrator.yaml"
    _scaffold_yaml(path)

    assert path.is_file()
    cfg = Config.model_validate(__import__("yaml").safe_load(path.read_text()))
    assert cfg.name == "yuvaraj"
    assert cfg.board.type == "github"
    assert cfg.git.type == "github"
    assert cfg.board.url == "https://github.com/acme/repo"
    assert cfg.board.project_number is None
    assert cfg.mesh.supabase_url == ""


def test_scaffold_yaml_with_project_number_and_mesh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = iter(["yuvaraj", "https://github.com/acme/repo", "10", "https://x.supabase.co"])
    monkeypatch.setattr("typer.prompt", lambda *a, **kw: next(answers))
    monkeypatch.setattr("typer.confirm", lambda *a, **kw: True)

    path = tmp_path / "devOrchestrator.yaml"
    _scaffold_yaml(path)

    cfg = Config.model_validate(__import__("yaml").safe_load(path.read_text()))
    assert cfg.board.project_number == 10
    assert cfg.mesh.supabase_url == "https://x.supabase.co"


def test_required_env_vars_derives_from_raw_yaml() -> None:
    raw = {
        "board": {"token_env": "GITHUB_TOKEN"},
        "git": {"token_env": "GITHUB_TOKEN"},  # same as board -> not duplicated
        "brain": {"token_env": "OPENROUTER_API_KEY"},
        "notify": {"webhook_env": "MATTERMOST_WEBHOOK"},
        "mesh": {
            "supabase_url": "https://x.supabase.co",
            "supabase_key_env": "SUPABASE_SERVICE_KEY",
        },
    }
    required = _required_env_vars(raw)
    names = [r[0] for r in required]

    assert names.count("GITHUB_TOKEN") == 1  # board+git dedup
    assert "OPENROUTER_API_KEY" in names
    assert "MATTERMOST_WEBHOOK" in names
    assert "SUPABASE_SERVICE_KEY" in names


def test_required_env_vars_skips_mesh_when_not_configured() -> None:
    raw = {
        "board": {"token_env": "GITHUB_TOKEN"},
        "git": {"token_env": "GITHUB_TOKEN"},
        "mesh": {"supabase_url": "", "supabase_key_env": "SUPABASE_SERVICE_KEY"},
    }
    names = [r[0] for r in _required_env_vars(raw)]
    assert "SUPABASE_SERVICE_KEY" not in names


def test_scaffold_env_prompts_for_every_var_even_if_already_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale/placeholder value already in .env must not silently skip the prompt
    (this was the actual bug — a leftover placeholder token was trusted instead
    of surfaced)."""
    env_path = tmp_path / ".env"
    env_path.write_text("GITHUB_TOKEN=REPLACE_ME_PLACEHOLDER\n", encoding="utf-8")

    prompted: list[str] = []

    def fake_prompt(label, **kw):
        prompted.append(label)
        return "a-real-token"  # simulate the user actually typing a new value

    monkeypatch.setattr("typer.prompt", fake_prompt)

    required = [
        ("GITHUB_TOKEN", "GitHub token", True, ""),
        ("OPENROUTER_API_KEY", "Brain key", True, "placeholder"),
    ]
    _scaffold_env(env_path, required)

    assert len(prompted) == 2  # both prompted, even though GITHUB_TOKEN had a value
    content = env_path.read_text(encoding="utf-8")
    assert "GITHUB_TOKEN=a-real-token" in content  # replaced, not kept
    assert "OPENROUTER_API_KEY=a-real-token" in content


def test_scaffold_env_blank_answer_keeps_a_real_existing_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("GITHUB_TOKEN=ghp_realtoken\n", encoding="utf-8")
    original_mtime = env_path.stat().st_mtime_ns

    monkeypatch.setattr("typer.prompt", lambda *a, **kw: "")  # user just presses Enter

    _scaffold_env(env_path, [("GITHUB_TOKEN", "GitHub token", True, "")])

    assert env_path.stat().st_mtime_ns == original_mtime  # kept, file untouched
    assert "GITHUB_TOKEN=ghp_realtoken" in env_path.read_text(encoding="utf-8")


def test_scaffold_env_blank_answer_does_not_keep_a_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The actual live trap: a placeholder value + Enter must NOT be preserved —
    it falls back to the default (empty), so a later connection test / config
    check surfaces it rather than silently trusting junk."""
    env_path = tmp_path / ".env"
    env_path.write_text("GITHUB_TOKEN=REPLACE_ME_WITH_A_REAL_TOKEN\n", encoding="utf-8")

    monkeypatch.setattr("typer.prompt", lambda *a, **kw: "")  # user presses Enter

    _scaffold_env(env_path, [("GITHUB_TOKEN", "GitHub token", True, "")])

    # placeholder replaced with the empty default, not kept
    assert "REPLACE_ME" not in env_path.read_text(encoding="utf-8")


def test_looks_like_placeholder() -> None:
    assert _looks_like_placeholder("REPLACE_ME_WITH_A_REAL_TOKEN")
    assert _looks_like_placeholder("your_token_here")
    assert _looks_like_placeholder("ghp_xxxxxxxx")
    assert _looks_like_placeholder("<paste-here>")
    assert not _looks_like_placeholder("ghp_1a2b3c4d5e6f7g8h9i0j")
    assert not _looks_like_placeholder("")


def test_github_connection_flags_placeholder_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "REPLACE_ME_WITH_A_REAL_TOKEN")

    def fail_if_called(*a, **kw):
        raise AssertionError("should not hit the network for an obvious placeholder")

    monkeypatch.setattr("devorchestrator.cli.httpx.get", fail_if_called)

    _test_github_connection(_config())

    assert "placeholder" in capsys.readouterr().out.lower()


def _config(**board_overrides) -> Config:
    return Config.model_validate({
        "name": "tester",
        "board": {
            "type": "github", "url": "https://github.com/acme/repo",
            "token_env": "GITHUB_TOKEN", **board_overrides,
        },
        "git": {
            "type": "github", "url": "https://github.com/acme/repo", "token_env": "GITHUB_TOKEN",
        },
    })


def test_github_connection_reports_valid_token_and_repo_access(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "t")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/user":
            return httpx.Response(200, json={"login": "yuvaraj"})
        return httpx.Response(200, json={})

    monkeypatch.setattr(
        "devorchestrator.cli.httpx.get",
        lambda url, **kw: httpx.Client(transport=httpx.MockTransport(handler)).get(url, **kw),
    )

    _test_github_connection(_config())

    out = capsys.readouterr().out
    assert "yuvaraj" in out
    assert "repo access confirmed" in out


def test_github_connection_reports_rejected_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "bad")
    monkeypatch.setattr(
        "devorchestrator.cli.httpx.get",
        lambda url, **kw: httpx.Response(401),
    )

    _test_github_connection(_config())

    assert "rejected" in capsys.readouterr().out


def test_github_connection_skips_when_no_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    _test_github_connection(_config())

    assert "skipping connection test" in capsys.readouterr().out


# --- #54: project scope detection -------------------------------------------


def _cfg(project_number: int | None):
    data = {
        "name": "t", "role": "dev", "agent": "claude",
        "board": {"type": "github", "url": "https://github.com/acme/repo",
                  "token_env": "GITHUB_TOKEN"},
        "git": {"type": "github", "url": "https://github.com/acme/repo",
                "token_env": "GITHUB_TOKEN"},
    }
    if project_number is not None:
        data["board"]["project_number"] = project_number
    return Config.model_validate(data)


class _Resp:
    def __init__(self, headers=None):
        self.headers = headers or {}


def test_project_scope_missing_is_reported(capsys):
    from devorchestrator.cli import _check_project_scope

    _check_project_scope(_cfg(10), _Resp({"X-OAuth-Scopes": "repo, gist"}), {})

    out = capsys.readouterr().out
    assert "missing the" in out and "project" in out


def test_project_scope_present_is_confirmed(capsys):
    from devorchestrator.cli import _check_project_scope

    _check_project_scope(_cfg(10), _Resp({"X-OAuth-Scopes": "repo, project"}), {})

    assert "project scope" in capsys.readouterr().out


def test_project_scope_not_checked_without_project_number(capsys):
    """Plain Issues REST only needs repo — don't nag about a scope nothing uses."""
    from devorchestrator.cli import _check_project_scope

    _check_project_scope(_cfg(None), _Resp({"X-OAuth-Scopes": "repo"}), {})

    assert capsys.readouterr().out == ""


def test_fine_grained_token_falls_back_to_a_graphql_probe(monkeypatch, capsys):
    """Fine-grained PATs send no X-OAuth-Scopes header, so guessing is wrong."""
    from devorchestrator.cli import _check_project_scope

    class _Probe:
        status_code = 200

        def json(self):
            return {"data": {"viewer": {"login": "x"}}}

    monkeypatch.setattr("httpx.post", lambda *a, **kw: _Probe())
    _check_project_scope(_cfg(10), _Resp({}), {})

    assert "GraphQL" in capsys.readouterr().out
