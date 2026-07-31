"""DevOrchestrator command-line interface.

This is the *spine*: the command dispatch skeleton every other lane hooks into.
Commands are declared here as stubs; the owning lane fills in the body. Keeping
the surface stable now means later PRs touch one command body, not the wiring.

Entry point (see pyproject.toml [project.scripts]): ``devorchestrator.cli:main``.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from pathlib import Path

import httpx
import typer
import yaml
from rich.console import Console

from . import __version__
from .config import CONFIG_FILENAME, Config, ConfigError, load_config
from .pipeline import (
    LanePending,
    PipelineAborted,
    PipelineError,
    build_pipeline,
    load_pipeline_context,
)
from .review import build_review

app = typer.Typer(
    name="devorchestrator",
    help="The AI-native SDLC operating layer — task to deployed code.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _stub(command: str, owner_lane: str) -> None:
    """Uniform 'not implemented yet' notice so the CLI is runnable today."""
    console.print(f"[yellow]›[/] [bold]{command}[/] is not implemented yet.")
    console.print(f"  Owned by lane [cyan]{owner_lane}[/]. Tracked in docs/product-backlog.md.")
    raise typer.Exit(code=0)


def _pending(exc: LanePending) -> None:
    """Report that the Spine is ready but a lane's adapter hasn't landed yet."""
    console.print(
        f"[yellow]›[/] Spine is wired and ready — waiting on the [bold]{exc.component}[/] adapter."
    )
    console.print(f"  Provided by [cyan]{exc.where}[/]. Available once that lane merges.")
    raise typer.Exit(code=0)


def _mesh_or_exit(config: Config):
    """Build a SupabaseMesh, or exit with a readable reason.

    The mesh commands used to construct the client inline with no guard: an
    unconfigured mesh, a bad key, or an unreachable host all surfaced as a raw
    httpx traceback. `init` already reports connection problems this way; these
    now match it.
    """
    if not config.mesh.supabase_url:
        console.print(
            "[red]✗[/] no mesh configured — [cyan]mesh.supabase_url[/] is empty in "
            f"{CONFIG_FILENAME}.\n"
            "  → run [bold]devorchestrator init[/] and answer yes to the Supabase prompt."
        )
        raise typer.Exit(code=2)

    key = os.environ.get(config.mesh.supabase_key_env, "")
    if not key:
        console.print(
            f"[red]✗[/] [cyan]${config.mesh.supabase_key_env}[/] is not set — "
            "can't reach the mesh.\n  → add it to your .env."
        )
        raise typer.Exit(code=2)

    from .mesh.store import SupabaseMesh, create_supabase_client

    try:
        return SupabaseMesh(
            create_supabase_client(config.mesh.supabase_url, key),
            project=config.project_key,
        )
    except Exception as exc:  # noqa: BLE001 - client construction, any failure is fatal here
        console.print(f"[red]✗[/] could not connect to the mesh: {exc}")
        raise typer.Exit(code=1) from exc


def _mesh_call(what: str, fn, *args, **kwargs):
    """Run one mesh operation, turning backend failures into a readable line."""
    try:
        return fn(*args, **kwargs)
    except httpx.HTTPError as exc:
        console.print(f"[red]✗[/] mesh unreachable while trying to {what}: {exc}")
        raise typer.Exit(code=1) from exc
    except Exception as exc:  # noqa: BLE001 - supabase-postgrest raises its own types
        console.print(f"[red]✗[/] mesh error while trying to {what}: {exc}")
        raise typer.Exit(code=1) from exc


def _load_or_exit(ctx: typer.Context, *, check_env: bool = True) -> Config:
    """Load the config for the current invocation, or exit cleanly with the hint.

    Downstream lanes call this from their command bodies instead of importing the
    loader directly, so config-dir handling and error rendering stay in one place.
    """
    config_dir: Path = ctx.obj["config_dir"]
    try:
        return load_config(config_dir, check_env=check_env)
    except ConfigError as exc:
        console.print(f"[red]✗ config error[/]\n{exc}")
        raise typer.Exit(code=2) from exc


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"devorchestrator {__version__}")
        raise typer.Exit(code=0)


@app.callback()
def _root(
    ctx: typer.Context,
    config_dir: Path | None = typer.Option(
        None, "--config-dir", "-C",
        help="Directory holding devOrchestrator.yaml and .env (default: current dir).",
    ),
    _version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """DevOrchestrator — run `devorchestrator <command> --help` for details."""
    ctx.obj = {"config_dir": config_dir or Path.cwd()}


def _scaffold_yaml(path: Path) -> None:
    """Interactively write a github-typed devOrchestrator.yaml — the only board/git
    backend actually implemented in this repo (see docs/GAPS.md)."""
    console.print(f"[yellow]›[/] No {CONFIG_FILENAME} found at [cyan]{path}[/] — let's create one.")
    name = typer.prompt("Your name (used in mesh + notifications)")
    repo_url = typer.prompt("GitHub repo URL", default="https://github.com/OWNER/REPO")
    project_raw = typer.prompt(
        "GitHub Project (v2) number for Priority/Size fields (Enter to skip)",
        default="", show_default=False,
    )
    use_mesh = typer.confirm("Configure the Supabase mesh now?", default=False)
    supabase_url = typer.prompt("Supabase project URL", default="") if use_mesh else ""

    data: dict = {
        "name": name,
        "role": "dev",
        "agent": "claude",
        "board": {"type": "github", "url": repo_url, "token_env": "GITHUB_TOKEN"},
        "git": {"type": "github", "url": repo_url, "token_env": "GITHUB_TOKEN"},
        "brain": {
            "provider": "openrouter", "model": "deepseek/deepseek-v4-flash",
            "token_env": "OPENROUTER_API_KEY",
        },
        "notify": {"type": "mattermost", "webhook_env": "MATTERMOST_WEBHOOK"},
        "mesh": {"supabase_url": supabase_url, "supabase_key_env": "SUPABASE_SERVICE_KEY"},
    }
    if project_raw.strip():
        data["board"]["project_number"] = int(project_raw.strip())

    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    console.print(f"[green]✓[/] wrote {path}")


def _load_raw_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _required_env_vars(raw: dict) -> list[tuple[str, str, bool, str]]:
    """(env_var, prompt label, is_secret, default-if-left-blank) for whatever this
    config actually references — derived from the raw yaml, not a fixed list, so
    it works whether the yaml was just scaffolded or hand-edited."""
    out: list[tuple[str, str, bool, str]] = []
    board, git = raw.get("board") or {}, raw.get("git") or {}
    if board.get("token_env"):
        out.append((board["token_env"], "GitHub token (repo + project scopes)", True, ""))
    if git.get("token_env") and git["token_env"] != board.get("token_env"):
        out.append((git["token_env"], "Git token", True, ""))
    brain = raw.get("brain")
    if brain and brain.get("token_env"):
        provider = brain.get("provider", "brain")
        out.append((
            brain["token_env"],
            f"{provider} API key for the brain (Enter for a placeholder — "
            "brain falls back to a mechanical PR description without it)",
            True, "placeholder",
        ))
    notify = raw.get("notify")
    if notify and notify.get("webhook_env"):
        out.append((
            notify["webhook_env"], "Notify webhook URL (Enter for a placeholder)",
            False, "https://example.com/placeholder",
        ))
    mesh = raw.get("mesh") or {}
    if mesh.get("supabase_url") and mesh.get("supabase_key_env"):
        out.append((
            mesh["supabase_key_env"], "Supabase service key (Enter to skip the mesh)",
            True, "",
        ))
    return out


_PLACEHOLDER_MARKERS = ("replace_me", "your_token", "your-token", "xxxx", "<", "changeme")


def _looks_like_placeholder(value: str) -> bool:
    """True for obvious not-a-real-secret values, so 'Enter to keep' won't
    preserve them and the connection test can warn instead of trusting them.
    'placeholder' is intentionally allowed for brain/notify vars that genuinely
    just need to be non-empty — only reject it for secret-shaped values."""
    low = value.lower()
    return any(marker in low for marker in _PLACEHOLDER_MARKERS)


def _scaffold_env(env_path: Path, required: list[tuple[str, str, bool, str]]) -> None:
    """Prompt for every var this config references, every time.

    Shows whether one's already set so Enter keeps it — but always asks,
    rather than silently trusting whatever's already in .env. A stale or
    placeholder value sitting there (e.g. a token that was never actually
    filled in) would otherwise never get surfaced or corrected.
    """
    existing: dict[str, str] = {}
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key, _, value = stripped.partition("=")
                existing[key.strip()] = value.strip()

    changed = False
    for var, label, secret, default in required:
        current = existing.get(var, "")
        # A leftover placeholder must NOT count as a keepable value, or "Enter to
        # keep" silently preserves junk (exactly the trap that shipped before).
        keepable = current and not _looks_like_placeholder(current)
        suffix = " [Enter to keep the current value]" if keepable else ""
        value = typer.prompt(f"{label}{suffix}", default="", show_default=False, hide_input=secret)
        if value:
            if value != current:
                changed = True
            existing[var] = value
        elif keepable:
            pass  # keep the real existing value, no rewrite
        else:
            existing[var] = default
            changed = True

    if changed:
        env_path.write_text(
            "\n".join(f"{k}={v}" for k, v in existing.items()) + "\n", encoding="utf-8"
        )
        console.print(f"[green]✓[/] wrote {env_path}")


def _check_project_scope(config: Config, who: httpx.Response, headers: dict[str, str]) -> None:
    """Warn if the token can't read Projects v2 but the config needs it.

    Only matters when ``board.project_number`` is set — that is what switches
    GithubBoard onto the GraphQL path. Without it the plain Issues REST API is
    used and ``repo`` alone is enough.

    Classic PATs report what they were granted in ``X-OAuth-Scopes``; fine-grained
    tokens don't send it, so those get a real (cheap) GraphQL probe instead of a
    guess.
    """
    if config.board.project_number is None:
        return

    granted = who.headers.get("X-OAuth-Scopes")
    if granted is not None:
        scopes = {s.strip() for s in granted.split(",") if s.strip()}
        if scopes & {"project", "read:project"}:
            console.print("[green]✓ token has the project scope[/] (Projects v2 readable)")
        else:
            console.print(
                f"[red]✗ ${config.git.token_env} is missing the [bold]project[/bold] scope[/] — "
                f"board.project_number is set ({config.board.project_number}), which reads "
                "Priority/Size via the Projects v2 GraphQL API.\n"
                "  → add 'project' (or 'read:project') to the token, or remove "
                "board.project_number to fall back to plain Issues."
            )
        return

    # Fine-grained token: no scope header, so ask GitHub directly.
    try:
        probe = httpx.post(
            "https://api.github.com/graphql",
            headers=headers,
            json={"query": "query { viewer { login } }"},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        console.print(f"[yellow]⚠  could not verify Projects v2 access: {exc}[/]")
        return

    if probe.status_code == 200 and "errors" not in probe.json():
        console.print("[green]✓ token can reach the GraphQL API[/] (Projects v2 should work)")
    else:
        console.print(
            "[yellow]⚠  token may not be able to read Projects v2 — "
            "board.project_number is set, so grant it Projects read access if "
            "`devorchestrator start` fails to list issues.[/]"
        )


def _test_github_connection(config: Config) -> None:
    """Actually verify the token works and can see the configured repo — not just
    'the field is non-empty', which is all config validation checks."""
    from .integrations.github_board import _parse_owner_repo

    token = os.environ.get(config.git.token_env, "")
    if not token:
        console.print("[yellow]⚠  no GitHub token set — skipping connection test[/]")
        return
    if _looks_like_placeholder(token):
        console.print(
            f"[red]✗ ${config.git.token_env} is still a placeholder ({token!r}) — "
            "put a real GitHub token (repo + project scopes) in .env before running start[/]"
        )
        return

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    try:
        who = httpx.get("https://api.github.com/user", headers=headers, timeout=10.0)
    except httpx.HTTPError as exc:
        console.print(f"[red]✗ could not reach GitHub API: {exc}[/]")
        return
    if who.status_code != 200:
        console.print(f"[red]✗ GitHub token rejected ({who.status_code}) — check scopes/expiry[/]")
        return
    console.print(f"[green]✓ GitHub token valid[/] (as [bold]{who.json().get('login')}[/])")

    try:
        owner, repo = _parse_owner_repo(config.board.url)
    except ValueError:
        console.print("[yellow]⚠  could not parse owner/repo from board.url[/]")
        return
    repo_resp = httpx.get(
        f"https://api.github.com/repos/{owner}/{repo}", headers=headers, timeout=10.0
    )
    if repo_resp.status_code == 200:
        console.print(f"[green]✓ repo access confirmed:[/] {owner}/{repo}")
        _check_project_scope(config, who, headers)
    else:
        console.print(
            f"[red]✗ cannot access {owner}/{repo} ({repo_resp.status_code}) "
            "— check the token has access to this repo[/]"
        )


@app.command()
def init(
    ctx: typer.Context,
    migrate: bool = typer.Option(False, "--migrate", help="Run Supabase schema migration."),
) -> None:
    """Scaffold devOrchestrator.yaml + .env if missing, validate, test connections, migrate."""
    config_dir: Path = ctx.obj["config_dir"]
    yaml_path = config_dir / CONFIG_FILENAME
    env_path = config_dir / ".env"

    if not yaml_path.is_file():
        _scaffold_yaml(yaml_path)
    _scaffold_env(env_path, _required_env_vars(_load_raw_yaml(yaml_path)))

    config = _load_or_exit(ctx, check_env=True)
    workdir = config_dir / ".orchestrator"
    workdir.mkdir(parents=True, exist_ok=True)
    console.print(
        f"[green]✓[/] config valid for [bold]{config.name}[/] ({config.track.value} track)"
    )
    console.print(f"[green]✓[/] workspace ready at [cyan]{workdir}[/]")

    _test_github_connection(config)

    if config.brain is not None:
        from .sessions.brain import build_brain
        console.print(f"[green]✓ brain:[/] {build_brain(config).describe()}")

    if not config.mesh.supabase_url:
        console.print("[yellow]⚠  mesh.supabase_url not configured — skipping mesh setup[/]")
    else:
        console.print(f"[green]✓ mesh url: {config.mesh.supabase_url}[/]")
        console.print(f"[dim]  key env: {config.mesh.supabase_key_env}[/]")

        key = os.environ.get(config.mesh.supabase_key_env, "")
        if not key:
            console.print(
                f"[yellow]⚠  ${config.mesh.supabase_key_env} not set — mesh registration skipped[/]"
            )
        else:
            from .mesh.store import SupabaseMesh, create_supabase_client
            mesh = SupabaseMesh(
            create_supabase_client(config.mesh.supabase_url, key),
            project=config.project_key,
        )
            if mesh.healthy():
                mesh.emit("dev_joined", "init", {"dev": config.name})
                # The event is the audit trail; the devs row is the roster
                # (carries role + last_seen, and one row per dev rather than
                # one per join).
                mesh.register_dev(config.name, config.role.value)
                console.print(f"[green]✓ registered [bold]{config.name}[/] in mesh[/]")
            else:
                console.print(
                    f"[yellow]⚠  mesh unreachable — {mesh.last_error}[/]\n"
                    "    (key likely belongs to a different project than mesh.supabase_url, "
                    "or the tables aren't created yet. The loop runs fine without the mesh.)"
                )

    if migrate and config.mesh.supabase_url:
        dsn = os.environ.get("SUPABASE_DSN", "")
        if dsn:
            from .mesh.migrate import apply as _apply_migration
            _apply_migration(dsn)
            console.print("[green]✓ migration applied[/]")
        else:
            console.print(f"[red]✗ ${config.mesh.supabase_key_env} not set — cannot migrate[/]")


@app.command()
def start(ctx: typer.Context) -> None:
    """Pick a task, create a branch, run research + implementation sessions.

    Stops after the implementation session — checks + PR creation are a
    separate step (`devorchestrator pr`) so the dev reviews the code first.
    """
    config = _load_or_exit(ctx)  # fail loud on bad config before touching adapters
    try:
        pipeline = build_pipeline(config, on_event=lambda m: console.print(f"[dim]›[/] {m}"))
    except LanePending as exc:
        _pending(exc)
        return

    from .integrations.selector import select_issue

    try:
        pctx = pipeline.start(lambda issues: select_issue(issues, console))
    except PipelineAborted as exc:
        console.print(f"[yellow]›[/] {exc}")
        raise typer.Exit(code=0) from exc
    except PipelineError as exc:
        console.print(f"[red]✗ pipeline error:[/] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]✓[/] Implementation done on [cyan]{pctx.branch.name}[/]. "
        "Review the code, then run [bold]devorchestrator pr[/] when ready."
    )


@app.command()
def pr(
    ctx: typer.Context,
    base: str = typer.Option("dev", "--base", help="Branch to open the PR against."),
    all_checks: bool = typer.Option(
        False, "--all-checks", help="Run all checks even if one fails.",
    ),
    autofix_on: bool = typer.Option(
        True, "--autofix/--no-autofix", help="Auto-fix on check failure.",
    ),
) -> None:
    """Run quality gates (autofix on failure), then open a PR with an AI description.

    Everything here runs through Pipeline.prepare_pr — the same checks → autofix →
    describe → open_pr → mesh → notify sequence the pipeline tests cover. It used
    to be reimplemented inline, which meant the autofix path went through a
    checks/autofix.py helper that only logged that it would re-invoke the agent
    and never did (since deleted, #49), instead of the pipeline's loop that
    actually re-runs the session.
    """
    config = _load_or_exit(ctx, check_env=False)
    try:
        pipeline = build_pipeline(
            config,
            on_event=lambda m: console.print(f"[dim]›[/] {m}"),
            all_checks=all_checks,
        )
    except LanePending as exc:
        _pending(exc)
        return

    branch = _detect_branch()
    # Cheap guard first: catches the common "I'm still on dev" mistake with a
    # message naming the branch, before we go looking for a saved context.
    if branch == base or branch in {"dev", "main", "master", "unknown"}:
        console.print(
            f"[red]✗ you're on '{branch}', not a feature branch[/] — can't open a PR "
            f"from '{branch}' into '{base}'.\n"
            "    Run [bold]devorchestrator start[/] first (it creates + checks out a "
            "feature branch, runs the AI sessions, and commits the work); then run "
            "[bold]devorchestrator pr[/] from that branch."
        )
        raise typer.Exit(code=1)

    pctx = load_pipeline_context(branch)
    if pctx is None:
        console.print(
            f"[red]✗[/] No saved task context for [cyan]{branch}[/].\n"
            "  → run [bold]devorchestrator start[/] first (it records the issue this "
            "branch belongs to)."
        )
        raise typer.Exit(code=1)
    if base != pctx.branch.base:
        # --base overrides what start() recorded.
        pctx.branch = replace(pctx.branch, base=base)

    try:
        pctx = pipeline.prepare_pr(pctx, autofix=autofix_on)
    except PipelineError as exc:
        console.print(f"[red]✗[/] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]✓ PR opened:[/] {pctx.pull_request.url}")


def _detect_branch() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True
        )
        return proc.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


# _issue_id_from_branch / _title_from_branch lived here to reconstruct an
# approximate issue title from the branch slug. The PR now carries the real
# issue title, read from the context.json that start() saves.


@app.command()
def review(ctx: typer.Context) -> None:
    """(TL) Review a PR: diff | tests | CI | artifact, then approve or reject."""
    config = _load_or_exit(ctx)
    try:
        gate = build_review(config, console=console)
    except LanePending as exc:
        _pending(exc)
        return

    prs = gate.open_prs()
    if not prs:
        console.print("[dim]No PRs awaiting your review.[/]")
        return

    for pull_request in prs:
        gate.review_pr(pull_request, checks=[])
        prompt = "[a] approve & merge  [r] reject  [q] quit"
        choice = typer.prompt(prompt, default="q").strip().lower()
        if choice == "a":
            decision = gate.approve(pull_request)
            console.print(f"[green]✓ {decision.action}:[/] {decision.pr.url}")
        elif choice == "r":
            reason = typer.prompt("Rejection reason")
            decision = gate.reject(pull_request, reason)
            console.print(f"[yellow]✓ {decision.action}:[/] {decision.reason}")
        else:
            console.print("[dim]Skipped.[/]")
            if choice == "q":
                break


@app.command()
def status(ctx: typer.Context) -> None:
    """Show the resolved config for this workspace (spine slice of full status).

    The full command will also surface active sessions, cooldowns, and a mesh
    summary once those lanes land; for now it proves config loading end-to-end.
    """
    from rich.table import Table

    config = _load_or_exit(ctx, check_env=False)
    table = Table(title="DevOrchestrator status", show_header=False, title_justify="left")
    table.add_column(style="cyan")
    table.add_column()
    table.add_row("dev", config.name)
    table.add_row("role", config.role.value)
    table.add_row("agent", config.agent.value)
    table.add_row("track", config.track.value)
    table.add_row("board", f"{config.board.type.value} @ {config.board.url}")
    table.add_row("git", f"{config.git.type.value} @ {config.git.url}")
    table.add_row("brain", config.brain.model if config.brain else "[dim]—[/]")
    table.add_row("notify", config.notify.type.value if config.notify else "[dim]—[/]")
    table.add_row("mesh url", config.mesh.supabase_url or "[dim]not configured[/]")
    console.print(table)


@app.command()
def mesh(
    ctx: typer.Context,
    check: list[str] = typer.Option(
        [], "--check", "-c", help="Check if any of these modules have overlapping activity.",
    ),
    watch: bool = typer.Option(
        False, "--watch", "-w",
        help="Live, auto-refreshing view of active sessions (Ctrl-C to exit).",
    ),
    interval: float = typer.Option(
        3.0, "--interval", help="Refresh interval in seconds for --watch.",
    ),
) -> None:
    """Show the team activity from the shared context mesh (add --watch for live)."""
    config = _load_or_exit(ctx, check_env=False)
    from .mesh.conflict import warn_on_overlap
    from .mesh.dashboard import render_dashboard, render_dashboard_live

    mesh_inst = _mesh_or_exit(config)

    if check:
        warnings = _mesh_call(
            "check module overlap", warn_on_overlap, mesh_inst, check,
            self_dev=config.name,
        )
        if warnings:
            console.print("[bold]Module overlap warnings:[/]")
            for w in warnings:
                console.print(w)
            console.print()
        else:
            console.print("[green]✓ No overlapping activity detected[/]\n")

    if watch:
        render_dashboard_live(mesh_inst, console=console, interval=interval)
    else:
        _mesh_call("read team activity", render_dashboard, mesh_inst)


@app.command()
def decision(
    ctx: typer.Context,
    message: str = typer.Argument(..., help="The architectural decision to log."),
    module: str = typer.Option("unknown", "--module", "-m", help="Affected module name."),
) -> None:
    """Log an architectural decision into the shared mesh, visible to the whole team."""
    config = _load_or_exit(ctx, check_env=False)
    mesh_inst = _mesh_or_exit(config)

    _mesh_call("log the decision", mesh_inst.emit, "decision", module, {
        "dev": config.name,
        "description": message,
        "modules": [module],
    })
    console.print(f"[green]Decision logged:[/] {message}")

    from .mesh.conflict import warn_on_overlap
    warnings = _mesh_call(
        "check module overlap", warn_on_overlap, mesh_inst, [module],
        self_dev=config.name,
    )
    if warnings:
        console.print()
        console.print("[yellow]Note: overlapping activity on this module:[/]")
        for w in warnings:
            console.print(w)


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
