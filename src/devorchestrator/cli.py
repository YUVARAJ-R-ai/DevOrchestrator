"""DevOrchestrator command-line interface.

This is the *spine*: the command dispatch skeleton every other lane hooks into.
Commands are declared here as stubs; the owning lane fills in the body. Keeping
the surface stable now means later PRs touch one command body, not the wiring.

Entry point (see pyproject.toml [project.scripts]): ``devorchestrator.cli:main``.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from . import __version__
from .config import Config, ConfigError, load_config

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


@app.command()
def init(
    ctx: typer.Context,
    migrate: bool = typer.Option(False, "--migrate", help="Run Supabase schema migration."),
) -> None:
    """Test all connections, register the dev in the mesh, scaffold .orchestrator/."""
    config = _load_or_exit(ctx, check_env=False)
    console.print("[bold]DevOrchestrator init[/]")

    if not config.mesh.supabase_url:
        console.print("[yellow]⚠  mesh.supabase_url not configured — skipping mesh setup[/]")
    else:
        console.print(f"[green]✓ mesh url: {config.mesh.supabase_url}[/]")
        console.print(f"[dim]  key env: {config.mesh.supabase_key_env}[/]")

    if migrate and config.mesh.supabase_url:
        from .mesh.migrate import apply as _apply_migration
        key = __import__("os").environ.get(config.mesh.supabase_key_env, "")
        if key:
            _apply_migration(config.mesh.supabase_url, key)
            console.print("[green]✓ migration applied[/]")
        else:
            console.print(f"[red]✗ ${config.mesh.supabase_key_env} not set — cannot migrate[/]")

    # Scaffold .orchestrator/ directory
    _orch = Path(".orchestrator")
    _orch.mkdir(exist_ok=True)
    console.print(f"[green]✓ scaffolded {_orch}[/]")
    console.print("[green]✓ init complete[/]")


@app.command()
def start() -> None:
    """Pick a task, create a branch, run research + implementation sessions."""
    _stub("start", owner_lane="board+session")


@app.command()
def pr(
    ctx: typer.Context,
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
        results = _autofix(SubprocessCheckRunner(all_checks=all_checks))
    else:
        runner = SubprocessCheckRunner(all_checks=all_checks)
        results = runner.run_all()
        SubprocessCheckRunner.render(results)

    from supabase import create_client

    from .mesh.store import SupabaseMesh
    from .pr_description import generate_pr_description, save_pr_description

    branch = _detect_branch()
    if not results or all(r.passed for r in results):
        mesh = SupabaseMesh(create_client(config.mesh.supabase_url, ""))
        mesh.emit("pr_pass", "pr", {"dev": config.name})

    desc = generate_pr_description(branch)
    out = save_pr_description(desc, branch)
    console.print(f"[green]PR description saved to {out}[/]")


def _detect_branch() -> str:
    try:
        import subprocess
        proc = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                              capture_output=True, text=True)
        return proc.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


@app.command()
def review() -> None:
    """(TL) Review a PR: diff | tests | CI | artifact, then approve or reject."""
    _stub("review", owner_lane="pr")


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
def mesh(ctx: typer.Context) -> None:
    """Show the live team activity table from the shared context mesh."""
    config = _load_or_exit(ctx, check_env=False)
    from supabase import create_client

    from .mesh.dashboard import render_dashboard
    from .mesh.store import SupabaseMesh

    client = create_client(config.mesh.supabase_url, "")
    mesh_inst = SupabaseMesh(client)
    render_dashboard(mesh_inst)


@app.command()
def decision(
    ctx: typer.Context,
    message: str = typer.Argument(..., help="The architectural decision to log."),
    module: str = typer.Option("unknown", "--module", "-m", help="Affected module name."),
) -> None:
    """Log an architectural decision into the shared mesh, visible to the whole team."""
    config = _load_or_exit(ctx, check_env=False)
    from supabase import create_client

    from .mesh.store import SupabaseMesh

    client = create_client(config.mesh.supabase_url, "")
    mesh_inst = SupabaseMesh(client)
    mesh_inst.emit("decision", module, {
        "dev": config.name,
        "description": message,
        "modules": [module],
    })
    console.print(f"[green]Decision logged:[/] {message}")


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
