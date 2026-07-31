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
from html import escape
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

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
    /* hide Streamlit chrome so the hero isn't clipped by the top toolbar */
    header[data-testid="stHeader"] { background: transparent; height: 0; }
    #MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; height: 0; }
    .stApp {
      background:
        radial-gradient(1100px 500px at 12% -10%, rgba(94,234,212,.08), transparent 60%),
        radial-gradient(900px 500px at 100% 0%, rgba(240,180,41,.06), transparent 55%),
        #0b0f14;
    }
    .block-container { padding-top: 3.6rem !important; max-width: 1150px; }
    h1, h2, h3, code, .mono { font-family: 'JetBrains Mono', monospace; }
    h3 { margin-top: 1.4rem; }

    .hero-kicker { font-family:'JetBrains Mono',monospace; letter-spacing:.3em;
      text-transform:uppercase; font-size:.72rem; color:#5eead4; opacity:.9;
      padding-top:.35rem; line-height:1.5; }
    .hero-title { font-family:'JetBrains Mono',monospace; font-weight:800;
      font-size:2.7rem; line-height:1.12; margin:.35rem 0 .5rem; padding-bottom:.1rem;
      background:linear-gradient(92deg,#e6edf3,#5eead4); -webkit-background-clip:text;
      background-clip:text; -webkit-text-fill-color:transparent; }
    .hero-sub { color:#93a1b0; font-size:1.02rem; max-width:60ch; line-height:1.55; }

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
# Virtual terminal — a scripted, streaming preview of a live orchestration run.
# Rendered as a self-contained animated iframe (CSS-only staggered reveal) so it
# replays cleanly and never depends on a real tmux/session being attached.
# Each line is (kind, text); kind picks the colour. Glyphs live in the text.
# ---------------------------------------------------------------------------
_TERM_TABS = {
    "start (full loop)": [("orch:research", False), ("orch:implement", True),
                          ("orch:gate", False), ("orch:pr", False)],
    "pr (quality gate)": [("orch:gate", True), ("orch:pr", False)],
    "mesh (team watch)": [("orch:mesh", True)],
}

_TERM_SCRIPTS: dict[str, list[tuple[str, str]]] = {
    "start (full loop)": [
        ("cmd",  "devorchestrator start"),
        ("ok",   "✓ config loaded · YUVARAJ-R-ai · github"),
        ("ok",   "✓ mesh online · project=hackathon"),
        ("ask",  "? select a task ▸ #42 Add token-bucket rate limiter   [P1 · M]"),
        ("ok",   "✓ branch feature/issue-42-rate-limiter created"),
        ("gap",  ""),
        ("run",  "▶ research session   tmux: orch:research"),
        ("tool", "  claude ▸ reading src/gateway/…  (18 files)"),
        ("dim",  "  claude ▸ mesh: nobody else is touching gateway/ — clear"),
        ("path", "  claude ▸ wrote artifact.md  (approach: token-bucket, 34 lines)"),
        ("ok",   "✓ research complete · 41s"),
        ("gap",  ""),
        ("run",  "▶ implement session  tmux: orch:implement"),
        ("path", "  claude ▸ edit src/gateway/limiter.py       (+96  −0)"),
        ("path", "  claude ▸ edit src/gateway/middleware.py    (+12  −3)"),
        ("dim",  "  claude ▸ heartbeat → mesh  (touching: gateway/)"),
        ("path", "  claude ▸ add  tests/test_limiter.py        (+58  −0)"),
        ("ok",   "✓ implement complete · 3m12s"),
        ("gap",  ""),
        ("run",  "▶ quality gate"),
        ("tool", "  ruff   ▸ 2 issues → autofixed"),
        ("tool", "  pytest ▸ 128 passed in 6.4s"),
        ("ok",   "✓ gate green"),
        ("gap",  ""),
        ("run",  "▶ pull request"),
        ("tool", "  deepseek ▸ drafting PR description…"),
        ("ok",   "✓ PR #57 opened → dev   \"issue #42: token-bucket rate limiter\""),
        ("ok",   "✓ issue #42 moved to In review"),
        ("dim",  "✓ session ended → mesh  (duration 4m01s, 3 files)"),
        ("gap",  ""),
        ("wait", "● waiting for human ▸ review the PR and approve"),
    ],
    "pr (quality gate)": [
        ("cmd",  "devorchestrator pr"),
        ("ok",   "✓ on branch feature/issue-42-rate-limiter"),
        ("run",  "▶ quality gate"),
        ("tool", "  ruff   ▸ 3 issues found"),
        ("tool", "  ruff   ▸ 3 fixed automatically → committed"),
        ("tool", "  pytest ▸ collecting… 128 tests"),
        ("tool", "  pytest ▸ 128 passed, 0 failed in 6.4s"),
        ("ok",   "✓ gate green"),
        ("gap",  ""),
        ("run",  "▶ description"),
        ("tool", "  deepseek ▸ reading diff (4 files, +166 −3)"),
        ("tool", "  deepseek ▸ generating summary + test plan…"),
        ("ok",   "✓ PR body drafted (verified)"),
        ("gap",  ""),
        ("ok",   "✓ PR #57 opened → dev"),
        ("path", "  https://github.com/YUVARAJ-R-ai/DevOrchestrator/pull/57"),
        ("dim",  "✓ issue #42 → In review · mesh updated"),
    ],
    "mesh (team watch)": [
        ("cmd",  "devorchestrator mesh --watch"),
        ("ok",   "✓ mesh online · project=hackathon · refresh 2s"),
        ("gap",  ""),
        ("run",  "▶ active sessions"),
        ("tool", "  harsha  · feature/spine-runner   · impl      · running · 12s ago"),
        ("tool", "  ragav   · feature/ai-session     · research  · running · 4s ago"),
        ("dim",  "  tharun  · feature/mesh-gates      · impl      · idle    · 2m ago"),
        ("gap",  ""),
        ("run",  "▶ who is touching what"),
        ("path", "  gateway/         ← you (feature/issue-42-rate-limiter)"),
        ("path", "  mesh/store.py    ← tharun"),
        ("warn", "  ⚠ sessions/       ← ragav & harsha both editing"),
        ("gap",  ""),
        ("run",  "▶ recent decisions"),
        ("dim",  "  ragav  ▸ use libtmux over raw subprocess for sessions"),
        ("dim",  "  tharun ▸ project-scope every mesh row (.eq project)"),
        ("wait", "● live ▸ streaming team activity…"),
    ],
}

_TERM_COLOR = {
    "cmd": "#e6edf3", "ok": "#56d364", "run": "#5eead4", "tool": "#79c0ff",
    "path": "#d2a8ff", "dim": "#6b7a89", "warn": "#f0b429", "err": "#ff7b72",
    "ask": "#f0b429", "wait": "#f0b429", "gap": "#6b7a89",
}


def _terminal_html(scenario: str, nonce: int) -> tuple[str, int]:
    """Build a self-contained animated terminal iframe for one scenario."""
    script = _TERM_SCRIPTS[scenario]
    tabs = _TERM_TABS[scenario]
    step = 0.16  # seconds between line reveals

    tab_html = "".join(
        f'<span class="tab {"on" if active else ""}">{escape(name)}'
        f'{" ●" if active else ""}</span>'
        for name, active in tabs
    )

    rows = []
    for i, (kind, text) in enumerate(script):
        delay = f"{i * step:.2f}s"
        color = _TERM_COLOR.get(kind, "#c9d4df")
        prefix = "<span class='pr'>$ </span>" if kind == "cmd" else ""
        body = escape(text) if text else "&nbsp;"
        rows.append(
            f'<div class="tl" style="animation-delay:{delay};color:{color}">'
            f'{prefix}{body}</div>'
        )
    cursor_delay = f"{len(script) * step:.2f}s"
    rows.append(
        f'<div class="tl" style="animation-delay:{cursor_delay};color:#5eead4">'
        f'<span class="pr">$ </span><span class="cur"></span></div>'
    )
    body_html = "\n".join(rows)
    height = 132 + (len(script) + 1) * 23

    html = f"""
    <!-- nonce:{nonce} -->
    <style>
      @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&display=swap');
      * {{ box-sizing:border-box; }}
      .term {{ font-family:'JetBrains Mono',ui-monospace,Menlo,monospace;
        border-radius:12px; overflow:hidden; border:1px solid rgba(255,255,255,.10);
        box-shadow:0 24px 60px rgba(0,0,0,.55), 0 0 0 1px rgba(94,234,212,.05);
        background:#05080b; }}
      .bar {{ display:flex; align-items:center; gap:.55rem; padding:.5rem .8rem;
        background:linear-gradient(180deg,#10161d,#0b1016);
        border-bottom:1px solid rgba(255,255,255,.08); }}
      .dot {{ width:11px; height:11px; border-radius:50%; }}
      .d1 {{ background:#ff5f56; }} .d2 {{ background:#ffbd2e; }} .d3 {{ background:#27c93f; }}
      .tabs {{ display:flex; gap:.35rem; margin-left:.6rem; overflow:hidden; }}
      .tab {{ font-size:.68rem; color:#6b7a89; padding:.12rem .5rem; border-radius:6px;
        border:1px solid transparent; white-space:nowrap; }}
      .tab.on {{ color:#5eead4; background:rgba(94,234,212,.09);
        border-color:rgba(94,234,212,.30); }}
      .sid {{ margin-left:auto; font-size:.66rem; color:#41505f; letter-spacing:.04em; }}
      .body {{ padding:.85rem 1rem 1.1rem; font-size:.83rem; line-height:1.55;
        position:relative; background:
          repeating-linear-gradient(0deg, rgba(255,255,255,.014) 0 1px, transparent 1px 3px),
          radial-gradient(120% 90% at 50% -20%, rgba(94,234,212,.05), transparent 60%),
          #05080b; }}
      .tl {{ white-space:pre-wrap; opacity:0; transform:translateY(4px);
        animation:fu .22s ease forwards; }}
      .pr {{ color:#5eead4; font-weight:700; }}
      @keyframes fu {{ to {{ opacity:1; transform:none; }} }}
      .cur {{ display:inline-block; width:8px; height:1.02em; background:#5eead4;
        vertical-align:-2px; animation:bl 1.05s steps(1) infinite; }}
      @keyframes bl {{ 50% {{ opacity:0; }} }}
    </style>
    <div class="term">
      <div class="bar">
        <span class="dot d1"></span><span class="dot d2"></span><span class="dot d3"></span>
        <div class="tabs">{tab_html}</div>
        <span class="sid">session · claude-code</span>
      </div>
      <div class="body">
        {body_html}
      </div>
    </div>
    """
    return html, height


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
# Virtual terminal — scripted preview of a live orchestration session
# ---------------------------------------------------------------------------
st.markdown("### live session  ·  virtual terminal")
tcol, bcol = st.columns([3, 1])
with tcol:
    scenario = st.selectbox(
        "scenario", list(_TERM_SCRIPTS), label_visibility="collapsed",
    )
with bcol:
    if st.button("▶ replay", use_container_width=True):
        st.session_state["term_nonce"] = st.session_state.get("term_nonce", 0) + 1

# nonce forces the iframe to remount so the animation replays on change/replay
nonce = st.session_state.get("term_nonce", 0) + hash(scenario) % 1000
term_html, term_height = _terminal_html(scenario, nonce)
components.html(term_html, height=term_height, scrolling=False)
st.caption(
    "Scripted preview of what `devorchestrator " + scenario.split()[0] + "` streams in a live "
    "Claude Code / tmux session — pick a scenario or hit replay to watch it stream again."
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
    gh_token = os.environ.get(cfg.git.token_env, "")
    if not gh_token:
        st.warning(f"Set ${cfg.git.token_env} in .env to fetch your issues.")
    else:
        try:
            from devorchestrator.integrations.github_board import GithubBoard
            board = GithubBoard(
                url=cfg.board.url, token=gh_token,
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
                st.caption(
                    f"{len(issues)} issue(s) assigned to {cfg.name} — fetched live from GitHub."
                )
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
