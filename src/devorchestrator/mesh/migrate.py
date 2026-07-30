"""Supabase schema migration for the DevOrchestrator mesh.

Usage:
    python -m devorchestrator.mesh.migrate
        Prints the SQL — paste it into Supabase Dashboard > SQL Editor.

    python -m devorchestrator.mesh.migrate --apply
        Runs via direct Postgres connection ($SUPABASE_DSN in .env).

    SUPABASE_DSN format:
        postgresql://user:password@host:port/dbname
        (password may contain @; handled internally)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

SQL_PATH = Path(__file__).parent / "schema.sql"


def _read_sql() -> str:
    return SQL_PATH.read_text(encoding="utf-8")


def _parse_dsn(dsn: str) -> dict[str, str]:
    """Parse a Postgres DSN into keyword args, handling URL-encoded passwords."""
    parsed = urlparse(dsn)
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port) if parsed.port else "5432",
        "dbname": parsed.path.lstrip("/") if parsed.path else "postgres",
        "user": unquote(parsed.username) if parsed.username else "postgres",
        "password": unquote(parsed.password) if parsed.password else "",
    }


def apply(dsn: str) -> None:
    try:
        import psycopg2
    except ImportError:
        print(
            "psycopg2 not installed. Paste schema.sql into Supabase SQL Editor instead.",
            file=sys.stderr,
        )
        sys.exit(1)

    sql = _read_sql()
    params = _parse_dsn(dsn)
    conn = psycopg2.connect(**params)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        print("Migration applied successfully.")
    finally:
        conn.close()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Supabase mesh migration")
    parser.add_argument("--apply", nargs="?", const="env", metavar="DSN")
    args = parser.parse_args()

    if args.apply:
        dsn = args.apply if args.apply != "env" else os.environ.get("SUPABASE_DSN", "")
        if not dsn:
            print("Set SUPABASE_DSN in .env, or paste schema.sql into Supabase SQL Editor.", file=sys.stderr)  # noqa: E501
            sys.exit(1)
        apply(dsn)
    else:
        print("# Paste this SQL into Supabase Dashboard > SQL Editor > New query.\n")
        print(_read_sql())


if __name__ == "__main__":
    main()
