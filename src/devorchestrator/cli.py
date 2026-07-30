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
from .pipeline import LanePending, build_pipeline
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


@app.command()
def init(ctx: typer.Context) -> None:
    """Validate config, scaffold .orchestrator/, and report connection readiness.

    The config + workspace setup (Spine) runs now; per-service connection tests
    (Plane/Gitea/mesh/...) light up as those lane adapters land.
    """
    config = _load_or_exit(ctx, check_env=False)
    config_dir: Path = ctx.obj["config_dir"]
    workdir = config_dir / ".orchestrator"
    workdir.mkdir(parents=True, exist_ok=True)
    console.print(
        f"[green]✓[/] config valid for [bold]{config.name}[/] ({config.track.value} track)"
    )
    console.print(f"[green]✓[/] workspace ready at [cyan]{workdir}[/]")
    console.print("[dim]›[/] connection tests (board/git/mesh/notify) pending their lane adapters.")


@app.command()
def start(ctx: typer.Context) -> None:
    """Pick a task, create a branch, run research + implementation sessions."""
    config = _load_or_exit(ctx)  # fail loud on bad config before touching adapters
    try:
        pipeline = build_pipeline(config, on_event=lambda m: console.print(f"[dim]›[/] {m}"))
    except LanePending as exc:
        _pending(exc)
        return
    # TODO(wave-3): ctx_ = pipeline.start(<Lane B task selector>); pipeline.prepare_pr(ctx_)
    _ = pipeline


@app.command()
def pr(
    ctx: typer.Context,
    autofix: bool = typer.Option(
        True, "--autofix/--no-autofix", help="Re-invoke the agent to fix failing checks."
    ),
) -> None:
    """Run quality gates (autofix on failure), then open a PR with an AI description."""
    config = _load_or_exit(ctx)
    try:
        pipeline = build_pipeline(config)
    except LanePending as exc:
        _pending(exc)
        return
    # TODO(wave-3): pipeline.prepare_pr(<current PipelineContext>, autofix=autofix)
    _ = (pipeline, autofix)


@app.command()
def review(ctx: typer.Context) -> None:
    """(TL) Review a PR: diff | tests | CI | artifact, then approve or reject."""
    config = _load_or_exit(ctx)
    try:
        gate = build_review(config, console=console)
    except LanePending as exc:
        _pending(exc)
        return
    # TODO(wave-3): for pr in gate.open_prs(): gate.render(...); dispatch [a]/[r]
    _ = gate


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
    table.add_row("mesh db", config.mesh.db_path)
    console.print(table)


@app.command()
def mesh() -> None:
    """Show the live team activity table from the shared context mesh."""
    _stub("mesh", owner_lane="mesh")


@app.command()
def decision(message: str = typer.Argument(..., help="The architectural decision to log.")) -> None:
    """Log an architectural decision into the shared mesh, visible to the whole team."""
    _stub("decision", owner_lane="mesh")


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
