# Spine architecture (Lane A)

_How the Spine lane is built and how the other lanes plug into it. Companion to
[TEAM-WORKFLOW.md](TEAM-WORKFLOW.md); the loop it implements is described in
[research.md](research.md)._

The **Spine** owns the load-bearing structure every other lane hangs off:

| File | Role |
|------|------|
| `contracts.py` | **Frozen** shared types + adapter Protocols — the only cross-lane surface |
| `config.py` | Strict Pydantic schema + fail-loud loader for `devOrchestrator.yaml` |
| `pipeline.py` | The SDLC loop orchestration (task → branch → research → implement → checks → PR) |
| `review.py` | The TL approval gate (`AI → Human` boundary) |
| `cli.py` | Command dispatch (`init/start/pr/review/status/mesh/decision`) |
| `pyproject.toml`, `devOrchestrator.yaml.template` | Packaging + shareable config |

## The one idea: coordinate through `contracts.py`, inject everything

`pipeline.py` and `review.py` never import another lane's code. They depend only on
the **Protocols** in `contracts.py` (`BoardAdapter`, `GitAdapter`, `AgentSession`,
`CheckRunner`, `Mesh`, `Notifier`) and receive concrete implementations by injection.

```
Pipeline(config, board=…, git=…, research=…, impl=…, checks=…, mesh=…, notifier=…)
             │
             └── calls only the small documented method surface of each Protocol
```

Consequences:
- **Testable today.** `tests/conftest.py` provides in-memory fakes that satisfy the
  Protocols structurally, so `tests/test_pipeline.py` / `test_review.py` drive the
  entire loop — happy path, conflict warning, autofix-retry, approve/reject — with
  **no real Plane/Gitea/tmux** present. 31 tests, `ruff` clean.
- **UI-free core.** `pipeline.py` emits human-facing progress through an injected
  `on_event` callback; Rich rendering lives in `cli.py` and `review.py` only.

## The Wave-3 seam

`build_pipeline(config)` / `build_review(config)` are the single place real adapters
get wired. Until Lane B/C/D land, they raise `LanePending(component, where)`, which
the CLI turns into a friendly _"waiting on the board adapter (Lane B: …)"_ message —
never a traceback. Wave-3 integration (Lane A's call) fills in the construction in
those two factories; **the `Pipeline` / `ReviewGate` classes do not change.**

Expected adapter modules (checked by the factories):
- `integrations/github_board.py`, `integrations/github_git.py` — Lane B
- `sessions/tmux_runner.py` — Lane C
- `checks/runner.py`, `mesh/store.py`, `notify.py` — Lane D

## Contract change: review-flow methods on `GitAdapter`

The full review flow needs four methods on `GitAdapter`: `list_open_prs(assignee)`,
`get_diff(pr)`, `get_ci_status(pr)`, `comment_pr(pr, body)`. These are **added to
`contracts.py`** (additive — Lane B adapters that only drive the pipeline can stub
them until review is wired). With them, `ReviewGate.open_prs()` lists the TL's PRs
and `review_pr()` pulls the diff + CI itself; `reject()` posts the reason as an
on-PR comment as well as notifying.

> Because `contracts.py` is the frozen shared file, this addition is a **coordinated
> change**: the Spine owner lands it and every lane pulls. It ships on its own branch
> so the team can review the contract delta before it merges.

## Try it

```bash
uv sync
uv run devorchestrator --help
cp devOrchestrator.yaml.template devOrchestrator.yaml
uv run devorchestrator init         # validates config + scaffolds .orchestrator/
uv run devorchestrator start        # friendly "waiting on Lane B" until adapters land
uv run pytest -q                     # 31 passing
```
