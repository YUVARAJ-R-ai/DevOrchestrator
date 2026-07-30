from __future__ import annotations

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


class SupabaseMesh(Mesh):
    """Mesh implementation backed by Supabase/Postgres.

    Expects two tables:
        events(id UUID PK, dev text, module text, event_type text,
               payload jsonb, ts timestamptz)
        devs(name text PK, role text, last_seen timestamptz)

    **The mesh is observability, not a critical path** — like the brain, it must
    never break the loop. A bad key, a missing table, a network blip: every
    operation swallows the error, records it on :attr:`last_error`, and returns
    a benign value (``None`` for writes, ``[]`` for reads). Callers that want to
    surface the state check :meth:`healthy`.
    """

    def __init__(self, client: SupabaseClient) -> None:
        self._client = client
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

    def list_modules(self) -> list[str]:
        try:
            result = self._client.table("events").select("module").execute()
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


__all__ = ["SupabaseMesh"]
