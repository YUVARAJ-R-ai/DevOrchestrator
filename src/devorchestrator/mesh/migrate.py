"""Supabase schema migration for the DevOrchestrator mesh.

Usage:
    python -m devorchestrator.mesh.migrate  (prints SQL to stdout)
    python -m devorchestrator.mesh.migrate --apply  (runs against Supabase)

Requires env vars SUPABASE_URL and SUPABASE_SERVICE_KEY to be set.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

SQL_PATH = Path(__file__).parent / "schema.sql"


def _read_sql() -> str:
    return SQL_PATH.read_text(encoding="utf-8")


def apply(url: str, service_key: str) -> None:
    """Run the migration SQL against Supabase's SQL endpoint."""
    sql = _read_sql()
    response = httpx.post(
        f"{url.rstrip('/')}/rest/v1/rpc/",
        json={"query": sql},
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        },
    )
    response.raise_for_status()
    print("Migration applied successfully.")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Supabase mesh migration")
    parser.add_argument("--apply", action="store_true", help="Apply migration to Supabase")
    args = parser.parse_args()

    if args.apply:
        url = os.environ.get("SUPABASE_URL") or ""
        key = os.environ.get("SUPABASE_SERVICE_KEY") or ""
        if not url or not key:
            print("Set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env", file=sys.stderr)
            sys.exit(1)
        apply(url, key)
    else:
        print(_read_sql())


if __name__ == "__main__":
    main()
