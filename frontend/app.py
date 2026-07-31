"""DevOrchestrator — Streamlit control panel.

A functional frontend over the *working* pieces of the system: it loads the real
config, does live connection checks (GitHub / SiliconFlow brain / Supabase mesh),
fetches your real assigned issues, exercises the DeepSeek brain, and renders the
mesh dashboard. Every panel degrades gracefully — a service being down shows a
clear status, never a stack trace.

Run:  uv run --extra ui streamlit run frontend/app.py   (from the repo root)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

# Run from the repo root so config + .env resolve, and src/ imports work.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

st.set_page_config(page_title="DevOrchestrator", page_icon="◆", layout="wide")

# ---------------------------------------------------------------------------
# Aesthetic — dark "operator console": near-black, mint accent, mono display
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;800&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

    html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
    .stApp {
      background:
        radial-gradient(1100px 500px at 12% -10%, rgba(94,234,212,.08), transparent 60%),
        radial-gradient(900px 500px at 100% 0%, rgba(240,180,41,.06), transparent 55%),
        #0b0f14;
    }
    .block-container { padding-top: 2.2rem; max-width: 1150px; }
    h1, h2, h3, code, .mono { font-family: 'JetBrains Mono', monospace; }

    .hero-kicker { font-family:'JetBrains Mono',monospace; letter-spacing:.35em;
      text-transform:uppercase; font-size:.7rem; color:#5eead4; opacity:.9; }
    .hero-title { font-family:'JetBrains Mono',monospace; font-weight:800;
      font-size:2.7rem; line-height:1.05; margin:.2rem 0 .3rem;
      background:linear-gradient(92deg,#e6edf3,#5eead4); -webkit-background-clip:text;
      -webkit-text-fill-color:transparent; }
    .hero-sub { color:#93a1b0; font-size:1.02rem; max-width:60ch; }

    .pill { display:inline-block; padding:.15rem .6rem; border-radius:999px;
      font-family:'JetBrains Mono',monospace; font-size:.72rem; font-weight:600;
      border:1px solid rgba(255,255,255,.12); }
    .ok   { color:#5eead4; background:rgba(94,234,212,.10); border-color:rgba(94,234,212,.35);}
    .warn { color:#f0b429; background:rgba(240,180,41,.10); border-color:rgba(240,180,41,.35);}
    .bad  { color:#ff7b72; background:rgba(255,123,114,.10); border-color:rgba(255,123,114,.35);}

    .card { background:linear-gradient(180deg,rgba(255,255,255,.03),rgba(255,255,255,.01));
      border:1px solid rgba(255,255,255,.08); border-radius:14px; padding:1.05rem 1.15rem;
      height:100%; }
    .card h4 { margin:.1rem 0 .35rem; font-family:'JetBrains Mono',monospace; font-size:.85rem;
      color:#c9d4df; letter-spacing:.02em; }
    .card .big { font-family:'JetBrains Mono',monospace; font-size:1.15rem; font-weight:700; }
    .muted { color:#6b7a89; font-size:.8rem; }

    .stage { border:1px solid rgba(255,255,255,.08); border-left:3px solid #5eead4;
      border-radius:10px; padding:.7rem .9rem; background:rgba(255,255,255,.02); }
    .stage .n { font-family:'JetBrains Mono',monospace; color:#5eead4; font-weight:700; }
    .stage .t { font-weight:600; }
    .stage .d { color:#8a97a6; font-size:.82rem; }
    .human { border-left-color:#f0b429; }
    .human .n { color:#f0b429; }

    div[data-testid="stHorizontalBlock"] { gap:.8rem; }
    code { background:rgba(94,234,212,.08); color:#5eead4; padding:.08rem .35rem;
      border-radius:5px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Data access — every call is guarded; the UI shows status, never a traceback
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _load_config():
    from devorchestrator.config import load_config
    return load_config(check_env=False)


def _status_github(cfg) -> tuple[str, str]:
    import httpx
    tok = os.environ.get(cfg.git.token_env, "")
    if not tok:
        return "warn", f"${cfg.git.token_env} not set"
    try:
        r = httpx.get("https://api.github.com/user",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        if r.status_code == 200:
            return "ok", f"@{r.json().get('login')}"
        return "bad", f"{r.status_code} rejected"
    except Exception as e:  # noqa: BLE001
        return "bad", type(e).__name__


def _status_brain(cfg) -> tuple[str, str]:
    if cfg.brain is None:
        return "warn", "not configured"
    key = os.environ.get(cfg.brain.token_env, "")
    if not key:
        return "warn", f"${cfg.brain.token_env} not set"
    return "ok", f"{cfg.brain.provider}/{cfg.brain.model.split('/')[-1]}"


def _status_mesh(cfg) -> tuple[str, str]:
    key = os.environ.get(cfg.mesh.supabase_key_env, "")
    if not cfg.mesh.supabase_url or not key:
        return "warn", "not configured"
    try:
        from devorchestrator.mesh.store import SupabaseMesh, create_supabase_client
        m = SupabaseMesh(create_supabase_client(cfg.mesh.supabase_url, key),
                         project=getattr(cfg, "project_key", ""))
        return ("ok", "healthy") if m.healthy() else ("bad", "unreachable")
    except Exception as e:  # noqa: BLE001
        return "bad", type(e).__name__


def _pill(state: str, label: str) -> str:
    return f'<span class="pill {state}">{label}</span>'


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown('<div class="hero-kicker">the ai-native sdlc operating layer</div>',
            unsafe_allow_html=True)
st.markdown('<div class="hero-title">DevOrchestrator</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="hero-sub">You pick a task and review the result. The machine does '
    "everything in between — research, implementation, quality gates, PR, review, and a "
    "shared source of truth across every teammate's Claude Code sessions.</div>",
    unsafe_allow_html=True,
)
st.write("")

try:
    cfg = _load_config()
except Exception as exc:  # noqa: BLE001
    st.error(
        f"No valid devOrchestrator.yaml in {ROOT} — run `devorchestrator init`.\n\n{exc}"
    )
    st.stop()

# ---------------------------------------------------------------------------
# System status — live connection checks (the "it really works" proof)
# ---------------------------------------------------------------------------
st.markdown("### system status")
c1, c2, c3, c4 = st.columns(4)
checks = [
    (c1, "config", "ok", f"{cfg.name} · {cfg.board.type}"),
    (c2, "github", *_status_github(cfg)),
    (c3, "brain (deepseek)", *_status_brain(cfg)),
    (c4, "mesh (supabase)", *_status_mesh(cfg)),
]
for col, title, state, detail in checks:
    with col:
        st.markdown(
            f'<div class="card"><h4>{title}</h4>{_pill(state, state.upper())}'
            f'<div class="big" style="margin-top:.5rem">{detail}</div></div>',
            unsafe_allow_html=True,
        )

st.write("")

# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------
st.markdown("### the loop")
stages = [
    ("1", "Task", "Pick from your GitHub board", True),
    ("2", "Research", "Claude reads the codebase → artifact.md", False),
    ("3", "Implement", "Claude writes the code, live in tmux", False),
    ("4", "Gate + PR", "ruff + pytest, autofix, DeepSeek PR body", False),
    ("5", "Review", "Diff → approve → merge", True),
]
cols = st.columns(5)
for col, (n, t, d, human) in zip(cols, stages, strict=False):
    with col:
        cls = "stage human" if human else "stage"
        tag = " 👤" if human else ""
        st.markdown(
            f'<div class="{cls}"><div class="n">{n}{tag}</div>'
            f'<div class="t">{t}</div><div class="d">{d}</div></div>',
            unsafe_allow_html=True,
        )
st.markdown(
    '<div class="muted">👤 = the only two human moments: pick a task, approve the PR.</div>',
    unsafe_allow_html=True,
)
st.write("")

# ---------------------------------------------------------------------------
# Live: your board  +  brain playground
# ---------------------------------------------------------------------------
left, right = st.columns([1.15, 1])

with left:
    st.markdown("### your board  ·  live")
    if st.button("↻ fetch my assigned issues", use_container_width=True):
        st.cache_data.clear()
    try:
        from devorchestrator.integrations.github_board import GithubBoard
        board = GithubBoard(
            url=cfg.board.url, token=os.environ.get(cfg.git.token_env, ""),
            dev_name=cfg.name, project_number=cfg.board.project_number,
        )
        issues = board.fetch_issues()
        if not issues:
            st.info("No open issues assigned to you.")
        else:
            st.dataframe(
                [{"#": i.id, "title": i.title, "priority": i.priority.value,
                  "size": i.estimate or "-"} for i in issues],
                use_container_width=True, hide_index=True,
            )
            st.caption(f"{len(issues)} issue(s) assigned to {cfg.name} — fetched live from GitHub.")
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Board unavailable: {exc}")

with right:
    st.markdown("### deepseek brain  ·  live")
    prompt = st.text_area("Ask the orchestrator brain (SiliconFlow / DeepSeek):",
                          value="Summarize what a good PR description contains, in 2 lines.",
                          height=90)
    if st.button("▶ run completion", use_container_width=True):
        try:
            import asyncio

            from devorchestrator.sessions.brain import build_brain
            brain = build_brain(cfg)
            with st.spinner("thinking…"):
                out = asyncio.run(brain.complete(prompt, max_tokens=200))
            st.success("verified" if getattr(brain, "verified", False) else "fallback")
            st.markdown(out)
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Brain unavailable: {exc}")

st.write("")

# ---------------------------------------------------------------------------
# Mesh — the shared source of truth
# ---------------------------------------------------------------------------
st.markdown("### shared mesh  ·  single source of truth")
mesh_state, mesh_detail = _status_mesh(cfg)
if mesh_state != "ok":
    st.markdown(
        f'{_pill(mesh_state, mesh_detail)} &nbsp; the mesh records every teammate\'s '
        "session events (started / heartbeat / ended), decisions, and who-touches-what. "
        "It degrades gracefully — the loop runs without it.",
        unsafe_allow_html=True,
    )
    st.caption("To activate: point mesh.supabase_url at the project your key belongs to, "
               "then run `python -m devorchestrator.mesh.migrate` and paste the SQL.")
else:
    try:
        from devorchestrator.mesh.store import SupabaseMesh, create_supabase_client
        m = SupabaseMesh(
            create_supabase_client(cfg.mesh.supabase_url,
                                   os.environ.get(cfg.mesh.supabase_key_env, "")),
            project=getattr(cfg, "project_key", ""),
        )
        active = getattr(m, "active_sessions", lambda: [])()
        st.markdown("**Active sessions right now**")
        if active:
            st.dataframe(
                [{"dev": s.dev, "branch": s.branch, "kind": s.kind, "state": s.state,
                  "last seen": s.last_seen} for s in active],
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("No active sessions.")
        decisions = m.recent_decisions(limit=8)
        if decisions:
            st.markdown("**Recent decisions**")
            st.dataframe([{"dev": d.dev, "decision": d.description, "when": d.ts or ""}
                          for d in decisions], use_container_width=True, hide_index=True)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Mesh read failed: {exc}")

st.write("")
st.markdown("### run it")
st.code(
    "devorchestrator init      # scaffold config + test connections\n"
    "devorchestrator start     # pick a task → research + impl sessions (live tmux)\n"
    "devorchestrator pr        # quality gate + DeepSeek PR description → open PR\n"
    "devorchestrator review    # diff → approve → merge\n"
    "devorchestrator mesh -w   # live team dashboard",
    language="bash",
)
st.caption("DevOrchestrator · built for the hackathon · every panel above reads the real system.")
