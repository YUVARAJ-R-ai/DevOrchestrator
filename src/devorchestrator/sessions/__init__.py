"""Lane C — AI sessions: the developer's AI companion (issues #8, #9, #10).

Owns: ``tmux_runner.py``, ``research.py``, ``impl.py``, ``artifact.py``,
``brain.py``, and ``prompts/``.

Two Claude Code sessions do the real work — research reads the codebase and
writes the artifact, implementation reads the artifact and writes code. The
brain (``brain.py``) is a cheap open model used only for text transformation;
it never touches the repository.

Talks to other lanes strictly through :mod:`devorchestrator.contracts`:
:class:`~devorchestrator.contracts.Issue` in, :class:`~devorchestrator.contracts.Artifact`
out, and :class:`~devorchestrator.contracts.AgentSession` as the session interface.

Deliberately re-exports nothing: importing this package must stay free of side
effects and of the optional ``libtmux``/``openai`` extras, so the CLI keeps
working before those are installed.
"""
