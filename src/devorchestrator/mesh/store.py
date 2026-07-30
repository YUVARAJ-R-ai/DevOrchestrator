from __future__ import annotations

from datetime import UTC, datetime

from supabase import Client as SupabaseClient

from devorchestrator.contracts import Decision, DevActivity, Mesh


class SupabaseMesh(Mesh):
    """Mesh implementation backed by Supabase/Postgres.

    Expects two tables:
        events(id UUID PK, dev text, module text, event_type text,
               payload jsonb, ts timestamptz)
        devs(name text PK, role text, last_seen timestamptz)
    """

    def __init__(self, client: SupabaseClient) -> None:
        self._client = client

    def emit(self, event_type: str, module: str, payload: dict) -> None:
        self._client.table("events").insert({
            "event_type": event_type,
            "module": module,
            "payload": payload,
            "ts": datetime.now(UTC).isoformat(),
            "dev": payload.get("dev", "unknown"),
        }).execute()

    def who_is_touching(self, module: str) -> list[DevActivity]:
        result = (
            self._client.table("events")
            .select("dev", "module", "event_type", "ts")
            .eq("module", module)
            .order("ts", desc=True)
            .limit(20)
            .execute()
        )
        return [
            DevActivity(
                dev=row["dev"],
                module=row["module"],
                branch=row.get("branch", ""),
                event_type=row["event_type"],
                ts=row["ts"],
            )
            for row in (result.get("data") or [])
        ]

    def recent_decisions(self, limit: int = 10) -> list[Decision]:
        result = (
            self._client.table("events")
            .select("*")
            .eq("event_type", "decision")
            .order("ts", desc=True)
            .limit(limit)
            .execute()
        )
        return [
            Decision(
                description=row["payload"].get("description", ""),
                dev=row["dev"],
                affected_modules=tuple(row["payload"].get("modules", [])),
                ts=row["ts"],
            )
            for row in (result.get("data") or [])
        ]


__all__ = ["SupabaseMesh"]
