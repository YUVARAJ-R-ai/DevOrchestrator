"""DevOrchestrator command-line interface.

This is the *spine*: the command dispatch skeleton every other lane hooks into.
Commands are declared here as stubs; the owning lane fills in the body. Keeping
the surface stable now means later PRs touch one command body, not the wiring.

Entry point (see pyproject.toml [project.scripts]): ``devorchestrator.cli:main``.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import httpx
import typer
import yaml
from rich.console import Console

from . import __version__
from .config import CONFIG_FILENAME, Config, ConfigError, load_config
from .pipeline import LanePending, PipelineAborted, PipelineError, build_pipeline
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
        out.append((
            brain["token_env"], "Brain/OpenRouter API key (Enter for a placeholder)",
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


def _scaffold_env(env_path: Path, required: list[tuple[str, str, bool, str]]) -> None:
    """Prompt only for vars this config references that aren't already in .env."""
    existing: dict[str, str] = {}
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key, _, value = stripped.partition("=")
                existing[key.strip()] = value.strip()

    changed = False
    for var, label, secret, default in required:
        if existing.get(var):
            continue
        value = typer.prompt(label, default="", show_default=False, hide_input=secret)
        existing[var] = value or default
        changed = True

    if changed:
        env_path.write_text(
            "\n".join(f"{k}={v}" for k, v in existing.items()) + "\n", encoding="utf-8"
        )
        console.print(f"[green]✓[/] wrote {env_path}")


def _test_github_connection(config: Config) -> None:
    """Actually verify the token works and can see the configured repo — not just
    'the field is non-empty', which is all config validation checks."""
    from .integrations.github_board import _parse_owner_repo

    token = os.environ.get(config.git.token_env, "")
    if not token:
        console.print("[yellow]⚠  no GitHub token set — skipping connection test[/]")
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

    if not config.mesh.supabase_url:
        console.print("[yellow]⚠  mesh.supabase_url not configured — skipping mesh setup[/]")
    else:
        console.print(f"[green]✓ mesh url: {config.mesh.supabase_url}[/]")
        console.print(f"[dim]  key env: {config.mesh.supabase_key_env}[/]")

        key = os.environ.get(config.mesh.supabase_key_env, "")
        if key:
            from .mesh.store import SupabaseMesh, create_supabase_client
            mesh = SupabaseMesh(create_supabase_client(config.mesh.supabase_url, key))
            mesh.emit("dev_joined", "init", {"dev": config.name})
            console.print(f"[green]✓ registered [bold]{config.name}[/] in mesh[/]")
        else:
            console.print(
                f"[yellow]⚠  ${config.mesh.supabase_key_env} not set — mesh registration skipped[/]"
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
    """Run quality gates (autofix on failure), then open a PR with an AI description."""
    config = _load_or_exit(ctx, check_env=False)
    from .checks.runner import SubprocessCheckRunner
    if autofix_on:
        from .checks.autofix import autofix as _autofix
        results = _autofix(
            SubprocessCheckRunner(all_checks=all_checks), max_retries=config.autofix_retries
        )
    else:
        runner = SubprocessCheckRunner(all_checks=all_checks)
        results = runner.run_all()
        SubprocessCheckRunner.render(results)

    if results and not all(r.passed for r in results):
        console.print("[red]✗ checks still failing — not opening a PR.[/]")
        raise typer.Exit(code=1)

    branch = _detect_branch()
    issue_id = _issue_id_from_branch(branch)

    from .pr_description import generate_pr_description, save_pr_description

    desc = generate_pr_description(branch, base=base)
    out = save_pr_description(desc, branch)
    console.print(f"[dim]PR description saved to {out}[/]")

    from .contracts import BranchRef
    from .integrations.github_git import GithubGit

    git = GithubGit(url=config.git.url, token=os.environ[config.git.token_env])
    branch_ref = BranchRef(name=branch, issue_id=issue_id or "", base=base)
    title = _title_from_branch(branch, issue_id)
    pull_request = git.open_pr(branch_ref, title=title, body=desc)
    console.print(f"[green]✓ PR opened:[/] {pull_request.url}")

    key = os.environ.get(config.mesh.supabase_key_env, "")
    if config.mesh.supabase_url and key:
        from .mesh.store import SupabaseMesh, create_supabase_client

        mesh = SupabaseMesh(create_supabase_client(config.mesh.supabase_url, key))
        mesh.emit("pr_opened", branch, {
            "dev": config.name, "pr_url": pull_request.url, "pr_number": pull_request.number,
        })

    if config.notify:
        notifier = config.notify.build_notifier()
        if notifier:
            notifier.notify(f"PR ready: {title} — {pull_request.url} ({config.name})")


def _detect_branch() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True
        )
        return proc.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _issue_id_from_branch(branch: str) -> str | None:
    """Recover the issue number from `feature/issue-N-slug` (Issue.branch_slug())."""
    match = re.search(r"issue-(\d+)-", branch)
    return match.group(1) if match else None


def _title_from_branch(branch: str, issue_id: str | None) -> str:
    """Best-effort human title from the branch slug (no per-number issue fetch yet)."""
    slug = branch.removeprefix("feature/").removeprefix("fix/")
    if issue_id:
        slug = re.sub(rf"^issue-{issue_id}-", "", slug)
    words = slug.replace("-", " ").strip()
    prefix = f"issue #{issue_id}: " if issue_id else ""
    return f"{prefix}{words}" if words else branch


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
) -> None:
    """Show the live team activity table from the shared context mesh."""
    config = _load_or_exit(ctx, check_env=False)
    from .mesh.conflict import warn_on_overlap
    from .mesh.dashboard import render_dashboard
    from .mesh.store import SupabaseMesh, create_supabase_client

    key = os.environ.get(config.mesh.supabase_key_env, "")
    client = create_supabase_client(config.mesh.supabase_url, key)
    mesh_inst = SupabaseMesh(client)

    if check:
        warnings = warn_on_overlap(mesh_inst, check)
        if warnings:
            console.print("[bold]Module overlap warnings:[/]")
            for w in warnings:
                console.print(w)
            console.print()
        else:
            console.print("[green]✓ No overlapping activity detected[/]\n")

    render_dashboard(mesh_inst)


@app.command()
def decision(
    ctx: typer.Context,
    message: str = typer.Argument(..., help="The architectural decision to log."),
    module: str = typer.Option("unknown", "--module", "-m", help="Affected module name."),
) -> None:
    """Log an architectural decision into the shared mesh, visible to the whole team."""
    config = _load_or_exit(ctx, check_env=False)
    from .mesh.store import SupabaseMesh, create_supabase_client

    key = os.environ.get(config.mesh.supabase_key_env, "")
    client = create_supabase_client(config.mesh.supabase_url, key)
    mesh_inst = SupabaseMesh(client)
    mesh_inst.emit("decision", module, {
        "dev": config.name,
        "description": message,
        "modules": [module],
    })
    console.print(f"[green]Decision logged:[/] {message}")

    from .mesh.conflict import warn_on_overlap
    warnings = warn_on_overlap(mesh_inst, [module])
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
