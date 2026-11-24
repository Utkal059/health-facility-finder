"""Shared test fixtures.

Integration tests need a throwaway Postgres at TEST_DATABASE_URL (docker
compose creates `hff_test` for this). They wipe it, apply the migrations and
load data through the real scraper loader, so they exercise the same path a
crawl does. Without TEST_DATABASE_URL they are skipped.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest

from db.env import load_dotenv
from db.migrate import migrate
from scraper.loader import Loader
from scraper.report import RunReport
from scraper.storage import Store

FIXTURES = Path(__file__).parent / "scraper" / "tests" / "fixtures"
FETCHED_AT = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def database_url() -> str:
    load_dotenv()
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    if url == os.environ.get("DATABASE_URL"):
        pytest.exit("TEST_DATABASE_URL must not be your main database: the tests wipe it.")
    return url


def reset_database(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")
    migrate(url)


def fixture_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def save_and_load(
    conn: psycopg.Connection, kind: str, key: str, body, fetched_at: datetime = FETCHED_AT
) -> RunReport:
    store = Store(conn)
    store.save_response(
        kind=kind, source_key=key, url=f"https://example.test/{key}", method="GET",
        request_body=None, http_status=200, body=body, fetched_at=fetched_at, run_id=None,
    )
    report = RunReport(command="test")
    Loader(conn, report).load(
        store.responses(("states", "districts", "facility_types", "systems_of_medicine",
                         "search_page"))
    )
    return report


@pytest.fixture
def seeded_db(database_url: str) -> str:
    """A fresh database holding the fixture search page, loaded by the real loader."""
    reset_database(database_url)
    with psycopg.connect(database_url, autocommit=True) as conn:
        save_and_load(conn, "states", "states|all", [
            {"locId": "3", "locName": "Punjab"}, {"locId": "24", "locName": "Gujarat"},
        ])
        save_and_load(conn, "districts", "districts|3", fixture_json("districts_of_state_3.json"))
        save_and_load(conn, "search_page", "Punjab|Amritsar|all|page=0",
                      fixture_json("search_page.json"))
    return database_url
