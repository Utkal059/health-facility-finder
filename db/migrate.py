"""Apply db/migrations/*.sql in order, each exactly once.

Usage: python -m db.migrate

Each file runs in its own transaction and is recorded in schema_migrations
with a checksum, so running this again is a no-op, and editing a migration
that has already been applied is caught instead of silently ignored.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import psycopg

from db.env import database_url

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Any constant works; it just stops two processes migrating at the same time
# (for example the seed container and a developer's shell).
_LOCK_ID = 7_243_118


def _checksum(sql: str) -> str:
    # Normalise line endings so a Windows checkout and a Linux one agree.
    return hashlib.sha256(sql.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def migrate(url: str) -> list[str]:
    applied_now: list[str] = []
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_LOCK_ID,))
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version    text PRIMARY KEY,
                    checksum   char(64) NOT NULL,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            done = dict(conn.execute("SELECT version, checksum FROM schema_migrations").fetchall())

            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                sql = path.read_text(encoding="utf-8")
                version, checksum = path.stem, _checksum(sql)
                if version in done:
                    if done[version] != checksum:
                        raise SystemExit(
                            f"{path.name} was edited after it was applied. "
                            "Add a new migration instead of changing an old one."
                        )
                    continue
                with conn.transaction():
                    conn.execute(sql)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                        (version, checksum),
                    )
                applied_now.append(version)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_ID,))
    return applied_now


def main() -> None:
    applied = migrate(database_url())
    if applied:
        print("Applied migrations: " + ", ".join(applied))
    else:
        print("Database schema is up to date.")


if __name__ == "__main__":
    main()
