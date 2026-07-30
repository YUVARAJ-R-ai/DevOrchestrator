# Architecture: Decoupling the Adapter Layer (Ports, Adapters, Registry)

_Proposal — not yet implemented. For team review before `config.py` / `contracts.py` change._

---

## Why this doc exists

[vision.md](vision.md) and [research.md](research.md) both name a real constraint: the mesh (and every external integration) should be **customizable, not vendor-locked** — but also **not "zero infra" at any cost**. Today that constraint isn't enforced anywhere in the code; it's only true by accident, because so little is built yet. This is the moment to lock in the shape *before* Lane A wires `pipeline.py`, because the naive path (branch on `config.type` at every call site) is exactly the kind of coupling that's cheap to avoid now and expensive to unwind later.

This doc covers: what's already solid, where the coupling risk actually is, prior art from three systems that solve this exact problem, and a concrete proposed shape mapped to this repo's files.

---

## What's already correct (keep it)

[contracts.py](../src/devorchestrator/contracts.py) already does Interface Segregation and Dependency Inversion properly:

- Small, single-concern `Protocol`s per adapter kind — `BoardAdapter`, `GitAdapter`, `AgentSession`, `CheckRunner`, `Mesh`, `Notifier` — not one fat interface.
- `GithubBoard` ([github_board.py](../src/devorchestrator/integrations/github_board.py)) and `selector.py` depend only on `contracts.Issue` / `contracts.IssueState` — never on each other's internals, matching [TEAM-WORKFLOW.md](TEAM-WORKFLOW.md)'s lane-isolation rule.
- `GithubBoard.__init__` accepts an injected `client: httpx.Client | None` — constructor injection, testable without a real network call.

None of this needs to change. The proposal below routes *through* `contracts.py`, not around it.

---

## Where the coupling risk actually is

### 1. Closed enums hardcode the vendor, inconsistently

[config.py:54-67](../src/devorchestrator/config.py#L54)
```python
class BoardType(StrEnum):
    github = "github"   # comment: "GitHub-only for the hackathon MVP"
class GitType(StrEnum):
    github = "github"
```
A `StrEnum` with one member is a closed set — adding Plane or Gitea means editing this file *and* every place that switches on it. Compare `BrainConfig.provider: str = "openrouter"` ([config.py:105](../src/devorchestrator/config.py#L105)), which is already a plain open string. The inconsistency shows nobody chose a convention on purpose.

### 2. `MeshConfig` bakes SQLite's shape into its field name

[config.py:115-118](../src/devorchestrator/config.py#L115)
```python
class MeshConfig(_Strict):
    db_path: str = ".orchestrator/mesh.db"
```
A field literally named `db_path` cannot hold a Postgres connection string without lying about itself. This is what turned "should we use Postgres" into "add a new field" instead of "point it somewhere else" — see the earlier discussion on the mesh being spec'd as SQLite over a Tailscale network mount ([sprint-3.md:69](sprint-3.md#L69)), which is also the concrete risk this schema shape currently hides.

### 3. No composition root exists yet — which is the point to fix this, not after

`cli.py` commands are still `_stub()` ([cli.py:72-93](../src/devorchestrator/cli.py#L72)); nothing constructs a `GithubBoard` today. The moment `start`/`init` get wired, the path of least resistance is:
```python
if config.board.type == "github":
    board = GithubBoard(...)
elif config.board.type == "plane":
    board = PlaneBoard(...)
```
inline in `pipeline.py`. This is a textbook Open/Closed violation: every new backend edits an existing function instead of adding a new one, and the branch duplicates across every place a backend needs to be resolved (board, git, mesh, notify, brain — five of these waiting to happen). Catching it before it's written costs a registry module; unwinding it later costs a refactor across every call site that grew a branch.

---

## Prior art — this is a solved problem

| System | Pattern | Source |
|---|---|---|
| **Dapr** | Fixed API ("building block", e.g. `state.Store`) + swappable "component" (Redis/Postgres/CosmosDB), selected by a YAML-declared name; app code never branches on backend | [Dapr components](https://docs.dapr.io/concepts/components-concept/) |
| **SQLAlchemy** | A connection is a URL — `sqlite:///file.db` vs `postgresql://host/db` — the scheme dispatches to a registered dialect via `entry_points` or `registry.register()`; zero call-site branching | [sqlalchemy/README.dialects.rst](https://github.com/sqlalchemy/sqlalchemy/blob/main/README.dialects.rst) |
| **Mem0** | One memory API routes to Qdrant / Neo4j / PostgreSQL / Chroma interchangeably by config; open-source lib supports swapping any of vector/graph/kv independently | [mem0ai/mem0](https://github.com/mem0ai/mem0) |

Same shape every time: **a fixed port (protocol/interface) + swappable adapters + one registry mapping a string to a constructor + one composition root that is the only place allowed to import concrete classes.** That last part is Dependency Inversion made literal — high-level code (pipeline, CLI) depends only on the abstraction; only one narrow seam knows the concretions.

---

## Proposed shape for this repo

### 1. `config.py` — open identifiers + DSN, not closed enums + bespoke field names

```python
class BoardConfig(_Strict):
    type: str = "github"          # was: BoardType enum — now a registry key
    url: str
    token_env: str
    project_number: int | None = None

class MeshConfig(_Strict):
    dsn: str = "sqlite:///.orchestrator/mesh.db"   # was: db_path
```
Validation moves from "is this a valid enum member" (Pydantic, load time) to "is this key registered" (registry lookup, also load time) — same fail-loud philosophy `ConfigError` already uses ([config.py:145](../src/devorchestrator/config.py#L145)), just resolved against an open registry instead of a closed enum. SQLite stays the zero-config default; Postgres — or later a graph store — is a one-line DSN change.

### 2. New `src/devorchestrator/registry.py`

```python
_MESH_BACKENDS: dict[str, Callable[[str], Mesh]] = {}

def register_mesh(scheme: str, factory: Callable[[str], Mesh]) -> None:
    _MESH_BACKENDS[scheme] = factory

def build_mesh(dsn: str) -> Mesh:
    scheme = dsn.split("://", 1)[0]
    try:
        return _MESH_BACKENDS[scheme](dsn)
    except KeyError:
        raise ConfigError(f"no mesh backend registered for scheme {scheme!r}",
                           hint=f"known: {sorted(_MESH_BACKENDS)}")
```
One of these per adapter kind (board, git, mesh, notify, brain), each seeded with today's built-in at import time (`github` board/git, `sqlite` mesh). A future teammate adds `register_mesh("postgresql", PostgresMesh)` without touching an existing line — the Open/Closed piece.

### 3. One composition root (Lane A's `pipeline.py`)

The *only* file allowed to `import GithubBoard`, `import SqliteMesh`, etc. Everything downstream — `cli.py`, every pipeline stage — touches only `contracts.BoardAdapter` / `contracts.Mesh`. This is what makes the "hive mind knowledge base" ambition tractable later: swapping the mesh for a graph-native store (Kùzu, Neo4j) for real knowledge-graph queries becomes one new adapter file registered under a new DSN scheme — zero changes to `cli.py`, `pipeline.py`, or the frozen `contracts.py`.

---

## Honest trade-off

This adds one layer of indirection (a registry lookup) versus importing `GithubBoard` directly. For a 4-person team that's a small, deliberate amount of ceremony — but it's a real schema change to `MeshConfig` / `BoardConfig` that touches a shared surface under [TEAM-WORKFLOW.md](TEAM-WORKFLOW.md)'s frozen-file rule, so it should land as a reviewed change, not a silent one.

## Status

Documented for team review. Not yet implemented — no changes made to `config.py`, `contracts.py`, or any adapter file as part of this doc.
