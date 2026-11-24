"""Loader behaviour against a real Postgres: idempotency, dedup, quarantine."""

from datetime import timedelta

import psycopg
import pytest

from conftest import FETCHED_AT, fixture_json, reset_database, save_and_load
from scraper.cli import _load_and_check, _ShapeDrift
from scraper.loader import Loader
from scraper.report import RunReport
from scraper.snapshot import export_snapshot, import_snapshot
from scraper.storage import Store

pytestmark = pytest.mark.integration


def snapshot(conn: psycopg.Connection) -> dict:
    """Everything a re-run could plausibly change, in comparable form."""
    queries = {
        "facilities": "SELECT * FROM facilities ORDER BY facility_id",
        "infrastructure": "SELECT * FROM facility_infrastructure ORDER BY facility_id",
        "specialities": "SELECT * FROM facility_specialities ORDER BY 1, 2",
        "systems": "SELECT * FROM facility_systems_of_medicine ORDER BY 1, 2",
        "quarantine": "SELECT response_id, record_index, facility_id, reasons "
                      "FROM quarantined_records ORDER BY 1, 2",
        "masters": "SELECT (SELECT count(*) FROM states), (SELECT count(*) FROM districts), "
                   "(SELECT count(*) FROM specialities), (SELECT count(*) FROM facility_types)",
    }
    return {name: conn.execute(sql).fetchall() for name, sql in queries.items()}


def test_valid_records_load_and_bad_ones_are_quarantined_with_reasons(seeded_db):
    with psycopg.connect(seeded_db) as conn:
        ids = [row[0] for row in conn.execute("SELECT facility_id FROM facilities ORDER BY 1")]
        assert ids == ["IN0399000001", "IN0399000002", "IN0399000006", "IN0399000007"]

        reasons = dict(conn.execute(
            "SELECT record_index, reasons FROM quarantined_records ORDER BY record_index"
        ).fetchall())
        assert reasons[2] == ["icu_beds_exceed_total_beds"]
        assert set(reasons[3]) == {"invalid_pincode", "coordinates_outside_india"}
        assert set(reasons[4]) == {"invalid_facility_id", "missing_name"}


def test_loading_the_same_scrape_twice_changes_nothing(seeded_db):
    with psycopg.connect(seeded_db, autocommit=True) as conn:
        before = snapshot(conn)
        report = save_and_load(conn, "search_page", "Punjab|Amritsar|all|page=0",
                               fixture_json("search_page.json"))
        assert snapshot(conn) == before
        assert report.facilities_inserted == 0
        assert report.records_quarantined == 3  # records, not reasons (two have two reasons)


def test_newer_copy_wins_but_never_erases_known_values(seeded_db):
    newer = {"content": [{
        "alternateId": "IN0399000001",
        "facName": "Sample Civil Hospital (Renamed)",
        "status": "Approved",
        "state": {"locId": "3", "locName": "Punjab"},
        "district": {"locId": "27", "locName": "Amritsar"},
        "pincode": None,  # missing this time
    }]}
    with psycopg.connect(seeded_db, autocommit=True) as conn:
        report = save_and_load(conn, "search_page", "Punjab|Amritsar|G|page=0", newer,
                               fetched_at=FETCHED_AT + timedelta(days=1))
        name, pincode, sightings, beds = conn.execute(
            """
            SELECT f.name, f.pincode,
                   (SELECT count(*) FROM facility_sightings s WHERE s.facility_id = f.facility_id),
                   fi.total_beds
            FROM facilities f JOIN facility_infrastructure fi USING (facility_id)
            WHERE f.facility_id = 'IN0399000001'
            """
        ).fetchone()
    assert name == "Sample Civil Hospital (Renamed)"
    assert pincode == "143001"
    assert beds == 120  # the newer copy published no beds, so the old ones stay
    assert sightings == 2
    assert report.facilities_updated >= 1


def test_district_from_another_state_is_quarantined(seeded_db):
    clash = {"content": [{
        "alternateId": "IN0399000099",
        "facName": "Sample Mismatch Clinic",
        "status": "Approved",
        "state": {"locId": "24", "locName": "Gujarat"},
        "district": {"locId": "27", "locName": "Amritsar"},  # Amritsar is in Punjab
    }]}
    with psycopg.connect(seeded_db, autocommit=True) as conn:
        report = save_and_load(conn, "search_page", "clash|page=0", clash)
        found = conn.execute("SELECT 1 FROM facilities WHERE facility_id = 'IN0399000099'")
        assert found.fetchone() is None
    assert report.rejected["district_not_in_state"] == 1


def test_crawl_stops_when_pages_stop_looking_like_search_results(seeded_db):
    with psycopg.connect(seeded_db, autocommit=True) as conn:
        store = Store(conn)
        response_id = store.save_response(
            kind="search_page", source_key="Punjab|Ludhiana|all|page=0",
            url="https://example.test/search", method="POST", request_body=None,
            http_status=200, body={"records": {"items": []}, "totalElements": 12},
            fetched_at=FETCHED_AT, run_id=None,
        )
        report = RunReport(command="test")
        with pytest.raises(_ShapeDrift, match="no list of facilities"):
            _load_and_check(store, Loader(conn, report), report, [response_id])
        (reasons,) = conn.execute(
            "SELECT reasons FROM quarantined_records WHERE response_id = %s", (response_id,)
        ).fetchone()
    assert reasons == ["unrecognised_page_shape"]


def test_snapshot_round_trip_rebuilds_the_same_facilities_without_contacts(seeded_db, tmp_path):
    path = tmp_path / "snapshot.jsonl.gz"
    with psycopg.connect(seeded_db, autocommit=True) as conn:
        before = conn.execute("SELECT facility_id, name FROM facilities ORDER BY 1").fetchall()
        assert export_snapshot(conn, path) == 3

    reset_database(seeded_db)
    with psycopg.connect(seeded_db, autocommit=True) as conn:
        assert import_snapshot(conn, path) == 3
        store = Store(conn)
        Loader(conn, RunReport(command="test")).load(
            store.responses(("states", "districts", "search_page"))
        )
        after = conn.execute("SELECT facility_id, name FROM facilities ORDER BY 1").fetchall()
        phones = conn.execute("SELECT count(phone) FROM facilities").fetchone()[0]
    assert after == before
    assert phones == 0  # the committed snapshot carries no phone numbers
