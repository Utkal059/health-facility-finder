"""Connection pool. Endpoints are plain `def` functions, so FastAPI runs them
in its thread pool and a synchronous psycopg pool is all we need."""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
from fastapi import Request
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


def _configure_connection(conn: psycopg.Connection) -> None:
    conn.execute("SET pg_trgm.word_similarity_threshold = 0.35")


# A hosted database can take a few seconds to wake up; past that, say so.
CONNECT_WAIT_SECONDS = 10.0


def create_pool(database_url: str, size: int) -> ConnectionPool:
    return ConnectionPool(
        database_url,
        min_size=1,
        max_size=size,
        kwargs={"row_factory": dict_row, "autocommit": True},
        configure=_configure_connection,
        # Neon drops idle connections when it suspends. Without this check the
        # pool would hand them out and the next few requests would fail.
        check=ConnectionPool.check_connection,
        timeout=CONNECT_WAIT_SECONDS,
        open=False,
    )


def get_conn(request: Request) -> Iterator[psycopg.Connection]:
    with request.app.state.pool.connection() as conn:
        yield conn
