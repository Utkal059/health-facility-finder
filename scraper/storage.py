"""Raw responses, crawl tasks and run records: the scraper's own bookkeeping."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from scraper.sources import OWNERSHIP_LABELS, RESULTS_DISPLAY_CAP

# Some NHPR records embed the facility photo as a base64 string. Storing those
# would make the raw table mostly JPEG, so long base64 strings are cut out and
# replaced by a note of where they were, how long they were and their hash.
_BASE64 = re.compile(r"^[A-Za-z0-9+/=\s]+$")
_MIN_BLOB_LENGTH = 512


def strip_blobs(body: Any) -> tuple[Any, list[dict]]:
    stripped: list[dict] = []

    def walk(node: Any, path: str) -> Any:
        if isinstance(node, dict):
            return {key: walk(value, f"{path}.{key}" if path else key) for key, value in node.items()}
        if isinstance(node, list):
            return [walk(value, f"{path}[{i}]") for i, value in enumerate(node)]
        if isinstance(node, str) and len(node) >= _MIN_BLOB_LENGTH and _BASE64.match(node):
            stripped.append({
                "path": path,
                "length": len(node),
                "sha256": hashlib.sha256(node.encode()).hexdigest(),
            })
            return None
        return node

    return walk(body, ""), stripped


def body_hash(body: Any) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CrawlTask:
    state_name: str
    district_name: str
    ownership: str | None = None  # None means every ownership type

    @property
    def key(self) -> str:
        return f"{self.state_name}|{self.district_name}|{self.ownership or 'all'}"

    @property
    def label(self) -> str:
        suffix = f" ({OWNERSHIP_LABELS[self.ownership]} only)" if self.ownership else ""
        return f"{self.district_name}, {self.state_name}{suffix}"


@dataclass(frozen=True)
class StoredResponse:
    id: int
    kind: str
    source_key: str
    body: Any
    fetched_at: datetime


class Store:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    # -- runs ---------------------------------------------------------------

    def start_run(self, command: str) -> int:
        row = self.conn.execute(
            "INSERT INTO crawl_runs (command) VALUES (%s) RETURNING id", (command,)
        ).fetchone()
        return row[0]

    def finish_run(self, run_id: int, status: str, report: dict) -> None:
        self.conn.execute(
            "UPDATE crawl_runs SET finished_at = now(), status = %s, report = %s WHERE id = %s",
            (status, Jsonb(report), run_id),
        )

    # -- raw responses ------------------------------------------------------

    def save_response(
        self,
        *,
        kind: str,
        source_key: str,
        url: str,
        method: str,
        request_body: Any,
        http_status: int,
        body: Any,
        fetched_at: datetime,
        run_id: int | None,
    ) -> int:
        body, stripped = strip_blobs(body)
        row = self.conn.execute(
            """
            INSERT INTO raw_responses (kind, source_key, url, method, request_body, http_status,
                                       body, body_sha256, stripped_fields, fetched_at, crawl_run_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (kind, source_key) DO UPDATE SET
                url = EXCLUDED.url,
                method = EXCLUDED.method,
                request_body = EXCLUDED.request_body,
                http_status = EXCLUDED.http_status,
                body = EXCLUDED.body,
                body_sha256 = EXCLUDED.body_sha256,
                stripped_fields = EXCLUDED.stripped_fields,
                fetched_at = EXCLUDED.fetched_at,
                crawl_run_id = EXCLUDED.crawl_run_id
            RETURNING id
            """,
            (kind, source_key, url, method,
             Jsonb(request_body) if request_body is not None else None,
             http_status, Jsonb(body), body_hash(body), Jsonb(stripped), fetched_at, run_id),
        ).fetchone()
        return row[0]

    def responses(self, kinds: tuple[str, ...], ids: list[int] | None = None) -> list[StoredResponse]:
        """Stored responses in the order they were fetched (oldest first)."""
        query = "SELECT id, kind, source_key, body, fetched_at FROM raw_responses WHERE kind = ANY(%s)"
        params: list[Any] = [list(kinds)]
        if ids is not None:
            query += " AND id = ANY(%s)"
            params.append(ids)
        query += " ORDER BY fetched_at, id"
        return [StoredResponse(*row) for row in self.conn.execute(query, params).fetchall()]

    # -- crawl tasks --------------------------------------------------------

    def register_tasks(self, tasks: list[CrawlTask]) -> None:
        with self.conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO crawl_tasks (task_key, state_name, district_name, ownership_filter)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (task_key) DO NOTHING
                """,
                [(t.key, t.state_name, t.district_name, t.ownership) for t in tasks],
            )

    def done_task_keys(self) -> set[str]:
        """Searches that have everything the site shows for them.

        A search recorded as done with fewer facilities than that counts as
        unfinished and runs again.
        """
        rows = self.conn.execute(
            "SELECT task_key FROM crawl_tasks WHERE status = 'done' "
            "AND records_seen >= least(coalesce(total_results, 0), %s)",
            (RESULTS_DISPLAY_CAP,),
        )
        return {row[0] for row in rows.fetchall()}

    def begin_task(self, task: CrawlTask) -> None:
        self.conn.execute(
            "UPDATE crawl_tasks SET status = 'in_progress', attempts = attempts + 1, "
            "updated_at = now() WHERE task_key = %s",
            (task.key,),
        )

    def update_task(self, task: CrawlTask, **fields: Any) -> None:
        assignments = ", ".join(f"{name} = %s" for name in fields)
        self.conn.execute(
            f"UPDATE crawl_tasks SET {assignments}, updated_at = now() WHERE task_key = %s",
            (*fields.values(), task.key),
        )

    def task_overview(self) -> list[tuple]:
        return self.conn.execute(
            """
            SELECT state_name, district_name, coalesce(ownership_filter, 'all'), status,
                   pages_fetched, records_seen, total_results, hit_display_cap, last_error
            FROM crawl_tasks
            ORDER BY state_name, district_name, ownership_filter NULLS FIRST
            """
        ).fetchall()
