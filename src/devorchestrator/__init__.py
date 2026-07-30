"""DevOrchestrator — the AI-native SDLC operating layer.

A developer picks a task and reviews the result; the machine does everything in
between. This package is organized in lanes (see docs/product-backlog.md):

    spine    — CLI skeleton + configuration layer (this groundwork)
    board    — task board adapters (Plane, Azure Boards)
    git      — git server adapters (Gitea, Azure Repos)
    session  — tmux research/implementation sessions
    checks   — quality gates + autofix
    pr       — PR automation + TL approval gate
    deploy   — deploy trigger + notifications
    mesh     — shared context mesh (SQLite)
"""

__version__ = "0.1.0"
