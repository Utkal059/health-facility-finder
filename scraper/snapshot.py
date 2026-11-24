"""Export and import the raw scrape, so the data can be rebuilt without NHPR.

The snapshot holds raw responses, not parsed rows. Loading it runs the same
parser and loader as a live crawl, so `docker compose up` exercises the real
ingestion path, and a parser fix can be checked against the full scrape.

Phone numbers and email addresses are removed on export. NHPR shows them
publicly, but a git repository keeps whatever goes into it forever, often
they belong to a person rather than the facility, and search doesn't need
them. A database filled by a live crawl still has the facility phone.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from scraper.storage import body_hash

_COLUMNS = (
    "kind", "source_key", "url", "method", "request_body", "http_status",
    "body", "stripped_fields", "fetched_at",
)


_CONTACT_HINTS = ("email", "mobile", "mobno", "landline", "phone", "contactper")


def is_contact_key(key: str) -> bool:
    lowered = key.lower()
    return any(hint in lowered for hint in _CONTACT_HINTS)


def redact_contacts(node: Any, replacement: Any = None) -> Any:
    """A copy of `node` with every phone/email/contact-person value replaced."""
    if isinstance(node, dict):
        return {
            key: (replacement if is_contact_key(key) and value not in (None, "")
                  else redact_contacts(value, replacement))
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [redact_contacts(item, replacement) for item in node]
    return node


def export_snapshot(conn: psycopg.Connection, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM raw_responses ORDER BY fetched_at, id"
    ).fetchall()
    # mtime=0 keeps the file byte-for-byte identical for identical data.
    with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as out:
        for row in rows:
            record = dict(zip(_COLUMNS, row, strict=True))
            record["fetched_at"] = record["fetched_at"].isoformat()
            record["body"] = redact_contacts(record["body"])
            line = json.dumps(record, ensure_ascii=False, sort_keys=True)
            out.write(line.encode("utf-8") + b"\n")
    return len(rows)


def import_snapshot(conn: psycopg.Connection, path: Path) -> int:
    count = 0
    with gzip.open(path, "rt", encoding="utf-8") as lines, conn.transaction():
        for line in lines:
            if not line.strip():
                continue
            record = json.loads(line)
            conn.execute(
                """
                INSERT INTO raw_responses (kind, source_key, url, method, request_body, http_status,
                                           body, body_sha256, stripped_fields, fetched_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (kind, source_key) DO UPDATE SET
                    url = EXCLUDED.url,
                    request_body = EXCLUDED.request_body,
                    http_status = EXCLUDED.http_status,
                    body = EXCLUDED.body,
                    body_sha256 = EXCLUDED.body_sha256,
                    stripped_fields = EXCLUDED.stripped_fields,
                    fetched_at = EXCLUDED.fetched_at
                """,
                (
                    record["kind"], record["source_key"], record["url"], record["method"],
                    Jsonb(record["request_body"]) if record["request_body"] is not None else None,
                    record["http_status"], Jsonb(record["body"]), body_hash(record["body"]),
                    Jsonb(record["stripped_fields"]), datetime.fromisoformat(record["fetched_at"]),
                ),
            )
            count += 1
    return count
