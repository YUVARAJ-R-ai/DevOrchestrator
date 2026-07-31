from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from supabase import Client as SupabaseClient
from supabase import ClientOptions, create_client

from devorchestrator.contracts import Decision, DevActivity, Mesh


def create_supabase_client(url: str, key: str) -> SupabaseClient:
    """Build a Supabase client forced to HTTP/1.1 (avoids HTTP/2 stream resets)."""
    return create_client(
        url, key,
        options=ClientOptions(
            httpx_client=httpx.Client(transport=httpx.HTTPTransport()),
        ),
    )


@dataclass(frozen=True, slots=True)
class SessionActivity:
    """Who is running (or has run) which agent session, read from the mesh.

    Lives here rather than ``contracts.py`` because that file is frozen (see
    docs/spine.md §2) — only the Spine owner adds new shared types.
    """

    dev: str
    branch: str
    kind: str
    state: str
    last_seen: str
    started_at: str
    finished_at: str | None = None


def _ts_seconds(value: str | None) -> float | None:
    """Best-effort ISO-8601 timestamp → epoch seconds. None if unparseable."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return None


class SupabaseMesh(Mesh):
    """Mesh implementation backed by Supabase/Postgres.

    Expects three tables:
        events(id UUID PK, project text, dev text, module text, event_type text,
               payload jsonb, ts timestamptz)
        devs(project text, name text, role text, last_seen timestamptz)
        sessions(project text, dev text, branch text, kind text, state text,
                 last_seen timestamptz, started_at timestamptz,
                 finished_at timestamptz, payload jsonb,
                 PK (project, dev, branch, kind))

    Every row is scoped by ``project``. The tables are shared by everything
    pointing at the same Supabase instance, so without it two repos that both
    have a module called ``cli.py`` would see each other's activity as a
    conflict.

    **The mesh is observability, not a critical path** — like the brain, it must
    never break the loop. A bad key, a missing table, a network blip: every
    operation swallows the error, records it on :attr:`last_error`, and returns
    a benign value (``None`` for writes, ``[]`` for reads). Callers that want to
    surface the state check :meth:`healthy`.
    """

    def __init__(self, client: SupabaseClient, project: str = "") -> None:
        """``project`` scopes every read and write — see Config.project_key.

        Defaults to empty so an un-scoped instance still works (and reads only
        un-scoped rows), but callers should always pass it.
        """
        self._client = client
        self._project = project
        self.last_error: str | None = None

    def healthy(self) -> bool:
        """True if a trivial read succeeds — used by the CLI to report status
        honestly instead of pretending a misconfigured mesh works."""
        try:
            self._client.table("events").select("id").limit(1).execute()
            self.last_error = None
            return True
        except Exception as exc:  # noqa: BLE001 — any failure means "not usable"
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False

    def emit(self, event_type: str, module: str, payload: dict) -> None:
        try:
            self._client.table("events").insert({
                "project": self._project,
                "event_type": event_type,
                "module": module,
                "payload": payload,
                "ts": datetime.now(UTC).isoformat(),
                "dev": payload.get("dev", "unknown"),
            }).execute()
            self.last_error = None
        except Exception as exc:  # noqa: BLE001 — mesh writes never break the loop
            self.last_error = f"{type(exc).__name__}: {exc}"

    def who_is_touching(self, module: str) -> list[DevActivity]:
        try:
            result = (
                self._client.table("events")
                .select("dev", "module", "event_type", "ts")
                .eq("project", self._project)
                .eq("module", module)
                .order("ts", desc=True)
                .limit(20)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001 — reads degrade to empty
            self.last_error = f"{type(exc).__name__}: {exc}"
            return []
        return [
            DevActivity(
                dev=row["dev"],
                module=row["module"],
                branch=row.get("branch", ""),
                event_type=row["event_type"],
                ts=row["ts"],
            )
            for row in (result.data or [])
        ]

    def register_dev(self, name: str, role: str = "dev") -> None:
        """Upsert this developer into ``devs`` and refresh ``last_seen``.

        The table shipped in schema.sql from the start but nothing ever wrote to
        it, so the roster it exists for had to be inferred from distinct ``dev``
        values in ``events`` — which only lists people who happen to have run a
        task, and cannot carry a role. Called by ``devorchestrator init``.
        """
        try:
            self._client.table("devs").upsert(
                {
                    "project": self._project,
                    "name": name,
                    "role": role,
                    "last_seen": datetime.now(UTC).isoformat(),
                },
                on_conflict="project,name",
            ).execute()
        except Exception as exc:  # noqa: BLE001 — roster is metadata, never fatal
            self.last_error = f"{type(exc).__name__}: {exc}"

    def team_roster(self) -> list[tuple[str, str, str]]:
        """(name, role, last_seen) for everyone registered, most recent first."""
        try:
            result = (
                self._client.table("devs")
                .select("name", "role", "last_seen")
                .eq("project", self._project)
                .order("last_seen", desc=True)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001 — reads degrade to empty
            self.last_error = f"{type(exc).__name__}: {exc}"
            return []
        return [(r["name"], r["role"], r["last_seen"]) for r in (result.data or [])]

    def list_modules(self) -> list[str]:
        try:
            result = (
                self._client.table("events")
                .select("module")
                .eq("project", self._project)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001 — reads degrade to empty
            self.last_error = f"{type(exc).__name__}: {exc}"
            return []
        seen: list[str] = []
        for row in (result.data or []):
            mod = row["module"]
            if mod not in seen:
                seen.append(mod)
        return seen

    def recent_decisions(self, limit: int = 10) -> list[Decision]:
        try:
            result = (
                self._client.table("events")
                .select("*")
                .eq("project", self._project)
                .eq("event_type", "decision")
                .order("ts", desc=True)
                .limit(limit)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001 — reads degrade to empty
            self.last_error = f"{type(exc).__name__}: {exc}"
            return []
        return [
            Decision(
                description=row["payload"].get("description", ""),
                dev=row["dev"],
                affected_modules=tuple(row["payload"].get("modules", [])),
                ts=row["ts"],
            )
            for row in (result.data or [])
        ]

    def active_sessions(self, within_seconds: int = 60) -> list[SessionActivity]:
        """Sessions still live right now — ``state == 'running'`` and ``last_seen``
        fresh enough that the session is likely still alive. Newest first."""
        try:
            result = (
                self._client.table("sessions")
                .select("*")
                .eq("project", self._project)
                .order("last_seen", desc=True)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001 — reads degrade to empty
            self.last_error = f"{type(exc).__name__}: {exc}"
            return []
        cutoff = datetime.now(UTC).timestamp() - within_seconds
        active: list[SessionActivity] = []
        for row in (result.data or []):
            if row.get("state") != "running":
                continue
            last_seen = _ts_seconds(row.get("last_seen"))
            if last_seen is None or last_seen < cutoff:
                continue
            active.append(_row_to_session(row))
        return active

    def session_history(self, limit: int = 10) -> list[SessionActivity]:
        """Recent finished sessions (anything not running/pending), newest first."""
        try:
            result = (
                self._client.table("sessions")
                .select("*")
                .eq("project", self._project)
                .order("last_seen", desc=True)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001 — reads degrade to empty
            self.last_error = f"{type(exc).__name__}: {exc}"
            return []
        finished = [
            _row_to_session(row)
            for row in (result.data or [])
            if row.get("state") not in ("running", "pending")
        ]
        return finished[:limit]


def _row_to_session(row: dict) -> SessionActivity:
    return SessionActivity(
        dev=row.get("dev", "unknown"),
        branch=row.get("branch", ""),
        kind=row.get("kind", ""),
        state=row.get("state", ""),
        last_seen=row.get("last_seen", ""),
        started_at=row.get("started_at", ""),
        finished_at=row.get("finished_at"),
    )


__all__ = ["SupabaseMesh", "SessionActivity"]
