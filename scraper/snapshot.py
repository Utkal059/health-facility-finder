"""Export and import the raw scrape, so the data can be rebuilt without NHPR.

The snapshot holds raw responses, not parsed rows. Loading it runs the same
parser and loader as a live crawl, so `docker compose up` exercises the real
ingestion path, and a parser fix can be checked against the full scrape.

Personal details are removed on export: phone numbers, email addresses,
contact people, and the health-ID and login fields that identify whoever
registered a facility. A git repository keeps whatever goes into it forever,
and search needs none of it. The local raw table still has the full response.
"""

from __future__ import annotations

import gzip
import json
import re
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


# Field names that hold personal details, matched anywhere in the name...
_PERSONAL_HINTS = (
    "email", "mobile", "mobno", "landline", "phone", "contactper",
    "healthid", "usr", "declaredby", "identification",
)
# ...or exactly, where a substring would catch innocent fields too.
_PERSONAL_KEYS = {"facpan", "factan", "facgst", "aboutus", "bookappurl"}

# Coordinates are long runs of digits, some of which would pass for a mobile number.
_COORDINATE_KEYS = {"geolocation", "latitude", "longitude"}

# The same details also turn up inside free text such as addresses.
_PERSONAL_TEXT = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.-]+"  # email address
    r"|\b\d{2}-\d{4}-\d{4}-\d{4}\b"  # health professional / health ID
    r"|(?<!\d)(?:\+?91[\s-]?|0)?[6-9]\d{9}(?!\d)"  # mobile number
)


def is_personal_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in _PERSONAL_KEYS or any(hint in lowered for hint in _PERSONAL_HINTS)


def redact_personal(node: Any) -> Any:
    """A copy of `node` without contact details or personal identifiers."""
    if isinstance(node, dict):
        return {
            key: (None if is_personal_key(key) and value not in (None, "")
                  else value if key.lower() in _COORDINATE_KEYS
                  else redact_personal(value))
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [redact_personal(item) for item in node]
    if isinstance(node, str) and _PERSONAL_TEXT.search(node):
        return _PERSONAL_TEXT.sub("", node).strip()
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
            record["body"] = redact_personal(record["body"])
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
