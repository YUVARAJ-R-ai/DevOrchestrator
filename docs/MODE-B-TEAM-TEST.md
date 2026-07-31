# Mode B — Shared-Mesh Team Test (single source of truth)

The real demo of the project's core idea: **multiple teammates run DevOrchestrator against one repo, each on their own issue, all reporting into one shared mesh** — so `devorchestrator mesh` shows everyone's activity in a single source of truth.

This is distinct from Mode A (each person on their own repo, proving "works on any repo", no shared state). Mode B proves the *team coordination* story.

---

## The security model — read this first

| Secret | Shared or per-person? | Reason |
|---|---|---|
| **GitHub token** | **Per-person — never share yours** | A PAT acts *as that person*. Everyone brings their own (`repo` scope). Using someone else's makes all their branches/PRs show as the token owner. |
| **Supabase URL + service key** | **Shared — this is the point** | The mesh is the shared source of truth. Everyone points at the same Supabase project. |
| **SiliconFlow key** | Optional — share one throwaway, or each their own, or skip | Only writes PR descriptions; degrades to a mechanical description without it. |

**So the only secrets you send friends are: the Supabase URL + service key (and optionally a SiliconFlow key). Everyone supplies their own GitHub token.**

---

## Values to fill in (the owner does this once)

| Placeholder | Where to get it | Value |
|---|---|---|
| `SHARED_SUPABASE_URL` | Supabase → Settings → Data API → Project URL | `https://<ref>.supabase.co` |
| `SHARED_SUPABASE_SERVICE_KEY` | Supabase → Settings → API keys → secret / service_role | `sb_secret_…` |
| `SHARED_SILICONFLOW_KEY` (optional) | siliconflow.com → API keys | `sk-…` |
| Test repo | already created | `zorokingofhell-dev/Hackathon_test_repo` |
| Friends' GitHub usernames | ask them | e.g. `ragavhariharan`, `ConTresillo`, `Haise-727` |

---

## Owner setup (once)

### 1. Create the shared Supabase schema
The mesh needs its tables. A fresh project has none, and the API key can't run DDL, so paste the schema **once**:
```bash
uv run python -m devorchestrator.mesh.migrate      # prints the SQL
```
Supabase dashboard → **SQL Editor → New query** → paste → **Run**. Creates `events` + `devs`.

### 2. Add each friend as a collaborator on the test repo
So their own GitHub token can push branches:
```bash
export GH_TOKEN=<owner token for zorokingofhell-dev>
for u in ragavhariharan ConTresillo Haise-727; do
  gh api -X PUT repos/zorokingofhell-dev/Hackathon_test_repo/collaborators/$u -f permission=push
done
```
Each friend must **accept the invite** (emailed / github.com/notifications).

### 3. Seed one issue per friend (assigned to them)
One issue each avoids branch collisions and lets `start` fetch the right task:
```bash
gh issue create --repo zorokingofhell-dev/Hackathon_test_repo \
  --title "demo: <small task for that friend>" \
  --body "<user story + acceptance criteria>" \
  --assignee <friend-username>
```

### 4. Verify the shared mesh connects
```bash
uv run python -c "
from devorchestrator.mesh.store import SupabaseMesh, create_supabase_client
m = SupabaseMesh(create_supabase_client('SHARED_SUPABASE_URL','SHARED_SUPABASE_SERVICE_KEY'))
print('mesh healthy:', m.healthy())"
```
Expect `True` once the schema is created.

---

## What each friend does

Send them: the **repo link**, the **shared Supabase URL + key**, (optionally the SiliconFlow key), and this block. They add their **own** GitHub token.

```bash
# 1. install the tool
uv tool install git+https://github.com/YUVARAJ-R-ai/DevOrchestrator

# 2. clone the shared test repo
git clone https://github.com/zorokingofhell-dev/Hackathon_test_repo
cd Hackathon_test_repo

# 3. never commit secrets
printf '.env\ndevOrchestrator.yaml\n.orchestrator/\n' > .gitignore
```

**`devOrchestrator.yaml`** (shared — same for everyone *except* `name` = their own GitHub username):
```yaml
name: <THEIR-github-username>      # must match how their issue is assigned
role: dev
agent: claude

board:
  type: github
  url: https://github.com/zorokingofhell-dev/Hackathon_test_repo
  token_env: GITHUB_TOKEN

git:
  type: github
  url: https://github.com/zorokingofhell-dev/Hackathon_test_repo
  token_env: GITHUB_TOKEN

brain:
  provider: siliconflow
  model: deepseek-ai/DeepSeek-V3
  token_env: SILICONFLOW_API_KEY

mesh:
  supabase_url: SHARED_SUPABASE_URL
  supabase_key_env: SUPABASE_SERVICE_KEY
```

**`.env`** (their own GitHub token + the shared keys):
```bash
GITHUB_TOKEN=<THEIR OWN github PAT, repo scope>
SUPABASE_SERVICE_KEY=SHARED_SUPABASE_SERVICE_KEY
SILICONFLOW_API_KEY=SHARED_SILICONFLOW_KEY        # or their own, or "placeholder"
```

**Run the loop:**
```bash
devorchestrator init            # ✓ their token valid + ✓ mesh registered
devorchestrator start           # pick their issue → AI writes code, commits, pushes
devorchestrator pr              # checks → DeepSeek PR description → opens PR
devorchestrator review          # [a] approve
```

---

## The payoff — watch the single source of truth

While friends run their tasks, anyone runs:
```bash
devorchestrator mesh
```
and sees the **combined** activity — every teammate's session events, decisions, and who's touching what, from one shared table. That's the whole point: one source of truth across everyone's Claude Code work.

`devorchestrator decision "…"` logs a shared architectural decision everyone sees.

---

## Known limitations for this test (be honest in the demo)

- **No per-project isolation** — every repo pointed at this Supabase writes to the same `events` table. Fine for one shared test; don't mix unrelated projects.
- **Milestone-level today, not session-level** — the mesh currently records `task_started` / `artifact_generated` / `pr_opened` / decisions, not live session internals. Issues **#56–#59** upgrade this to live, session-level tracking (that's the in-flight work).
- **Branch collisions** — two people on the *same* issue would collide. One issue per person avoids it (`create_branch` is now idempotent, but same-issue = same branch name).
- **Rate limits** — no account rotation; if several `claude` sessions run at once on one account's limit, some may throttle. Each friend on their own Claude login avoids this.

---

## Quick checklist

- [ ] Supabase schema created (`events` + `devs`)
- [ ] `mesh.healthy()` returns True
- [ ] Each friend added as collaborator + accepted
- [ ] One issue per friend, assigned to them
- [ ] Each friend has: repo cloned, `devOrchestrator.yaml` (with their username), `.env` (their token + shared keys), `.gitignore`
- [ ] Everyone runs `init` → `start` → `pr` → `review`
- [ ] `devorchestrator mesh` shows combined team activity ✓
