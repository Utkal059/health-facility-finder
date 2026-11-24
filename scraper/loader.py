"""Write parsed records into the normalised tables.

Loading is idempotent: replaying the same raw responses, in the same order,
always leaves the database in the same state. That is what lets us re-parse
everything after fixing a parser bug without crawling again.

How duplicates merge (also in the README): a facility is identified by its
NHPR facility ID alone. Responses are applied oldest first, so the most
recently fetched copy of a facility wins, except that a missing value never
erases a known one. Beds, coordinates and speciality lists are replaced as a
whole, never mixed field by field, so a merge can't invent a combination
(say ICU beds from one copy and total beds from another) that NHPR never
published.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from scraper.parser import (
    FacilityRecord,
    PageShapeError,
    Place,
    parse_facility,
    parse_lgd_list,
    parse_named_list,
    parse_search_page,
)
from scraper.report import STRUCTURAL_REASONS, RunReport
from scraper.storage import StoredResponse

MASTER_KINDS = ("states", "districts", "facility_types", "systems_of_medicine")

_UPSERT_FACILITY = """
INSERT INTO facilities AS f (
    facility_id, name, status, ownership_code, facility_type_id,
    state_lgd_code, district_lgd_code, sub_district_lgd_code,
    village_city_town_name, village_city_town_lgd_code, address, pincode,
    latitude, longitude, abdm_software, type_of_service, phone, website,
    source_response_id, first_seen_at, last_seen_at
) VALUES (
    %(facility_id)s, %(name)s, %(status)s, %(ownership_code)s, %(facility_type_id)s,
    %(state)s, %(district)s, %(sub_district)s,
    %(village_name)s, %(village_code)s, %(address)s, %(pincode)s,
    %(latitude)s, %(longitude)s, %(abdm_software)s, %(type_of_service)s, %(phone)s, %(website)s,
    %(response_id)s, %(seen_at)s, %(seen_at)s
)
ON CONFLICT (facility_id) DO UPDATE SET
    name                       = EXCLUDED.name,
    status                     = EXCLUDED.status,
    ownership_code             = COALESCE(EXCLUDED.ownership_code, f.ownership_code),
    facility_type_id           = COALESCE(EXCLUDED.facility_type_id, f.facility_type_id),
    state_lgd_code             = EXCLUDED.state_lgd_code,
    district_lgd_code          = EXCLUDED.district_lgd_code,
    -- An old sub-district only survives if the district hasn't changed.
    sub_district_lgd_code      = CASE
        WHEN EXCLUDED.sub_district_lgd_code IS NOT NULL THEN EXCLUDED.sub_district_lgd_code
        WHEN f.district_lgd_code = EXCLUDED.district_lgd_code THEN f.sub_district_lgd_code
    END,
    village_city_town_name     = COALESCE(EXCLUDED.village_city_town_name, f.village_city_town_name),
    village_city_town_lgd_code = COALESCE(EXCLUDED.village_city_town_lgd_code,
                                          f.village_city_town_lgd_code),
    address                    = COALESCE(EXCLUDED.address, f.address),
    pincode                    = COALESCE(EXCLUDED.pincode, f.pincode),
    latitude                   = COALESCE(EXCLUDED.latitude, f.latitude),
    longitude                  = COALESCE(EXCLUDED.longitude, f.longitude),
    abdm_software              = COALESCE(EXCLUDED.abdm_software, f.abdm_software),
    type_of_service            = COALESCE(EXCLUDED.type_of_service, f.type_of_service),
    phone                      = COALESCE(EXCLUDED.phone, f.phone),
    website                    = COALESCE(EXCLUDED.website, f.website),
    source_response_id         = EXCLUDED.source_response_id,
    first_seen_at              = LEAST(f.first_seen_at, EXCLUDED.first_seen_at),
    last_seen_at               = GREATEST(f.last_seen_at, EXCLUDED.last_seen_at)
RETURNING (xmax = 0) AS inserted
"""

_UPSERT_INFRASTRUCTURE = """
INSERT INTO facility_infrastructure (facility_id, has_icu_beds, total_beds, icu_beds, ventilators)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (facility_id) DO UPDATE SET
    has_icu_beds = EXCLUDED.has_icu_beds,
    total_beds   = EXCLUDED.total_beds,
    icu_beds     = EXCLUDED.icu_beds,
    ventilators  = EXCLUDED.ventilators
"""


class Loader:
    def __init__(self, conn: psycopg.Connection, report: RunReport):
        self.conn = conn
        self.report = report
        self._seen_this_run: set[str] = set()
        self._district_state: dict[int, int] = {}
        self._sub_district_parent: dict[int, int] = {}
        self._ids_by_name: dict[tuple[str, str], int] = {}

    # -- entry points -------------------------------------------------------

    def load(self, responses: Iterable[StoredResponse]) -> None:
        """Load master lists first, then search pages, each oldest first."""
        responses = list(responses)
        for kind in MASTER_KINDS:
            for response in responses:
                if response.kind == kind:
                    self.load_master_list(response)
        for response in responses:
            if response.kind == "search_page":
                self.load_search_page(response)

    def rebuild(self, responses: Iterable[StoredResponse]) -> None:
        """Throw the parsed facilities away and load them again from scratch.

        Merging keeps a known value when a newer copy lacks it, which is right
        between two fetches but would also keep whatever an older parser got
        wrong. One transaction, so readers see the old data until it is done.
        """
        with self.conn.transaction():
            self.conn.execute("DELETE FROM facilities")
            self.conn.execute("DELETE FROM sub_districts")
            self.load(responses)

    def load_master_list(self, response: StoredResponse) -> None:
        try:
            with self.conn.transaction():
                if response.kind == "states":
                    for place in parse_lgd_list(response.body):
                        self.conn.execute(
                            """
                            INSERT INTO states (lgd_code, name) VALUES (%s, %s)
                            ON CONFLICT (lgd_code) DO UPDATE SET name = EXCLUDED.name
                            """,
                            (place.lgd_code, place.name),
                        )
                elif response.kind == "districts":
                    self._load_districts(response)
                else:
                    for entry in parse_named_list(response.body):
                        self._id_for(response.kind, entry.name, entry.code)
        except PageShapeError:
            self.report.warnings["unrecognised_master_list"] += 1
            self._forget_cached_ids()

    def load_search_page(self, response: StoredResponse) -> None:
        try:
            with self.conn.transaction():
                self.conn.execute(
                    "DELETE FROM quarantined_records WHERE response_id = %s", (response.id,)
                )
                try:
                    page = parse_search_page(response.body)
                except PageShapeError:
                    self.report.pages_unrecognised += 1
                    self._store_quarantine(response, -1, None, ["unrecognised_page_shape"],
                                           response.body)
                    return
                for index, raw in enumerate(page.records):
                    self._load_record(response, index, raw)
        except Exception:
            # The whole page rolled back, so cached ids may point at rows that
            # no longer exist.
            self._forget_cached_ids()
            raise

    # -- one record ---------------------------------------------------------

    def _load_record(self, response: StoredResponse, index: int, raw: Any) -> None:
        self.report.records_seen += 1
        result = parse_facility(raw)
        self.report.warnings.update(result.warnings)
        if result.record is None:
            self._quarantine(response, index, result.facility_id, list(result.reasons), raw)
            return

        record = result.record
        try:
            with self.conn.transaction():
                references = self._resolve_references(record)
        except psycopg.errors.IntegrityError as exc:
            self._forget_cached_ids()
            references = f"db_rejected:{exc.diag.constraint_name or type(exc).__name__}"
        if isinstance(references, str):
            self._quarantine(response, index, record.facility_id, [references], raw)
            return

        try:
            # A savepoint per record: one row the database refuses can't sink
            # the rest of the page.
            with self.conn.transaction():
                inserted = self._write_facility(record, references, response)
        except psycopg.errors.IntegrityError as exc:
            constraint = exc.diag.constraint_name or type(exc).__name__
            self._quarantine(response, index, record.facility_id, [f"db_rejected:{constraint}"], raw)
            return

        if record.facility_id in self._seen_this_run:
            self.report.duplicates_merged += 1
        elif inserted:
            self.report.facilities_inserted += 1
        else:
            self.report.facilities_updated += 1
        self._seen_this_run.add(record.facility_id)

    def _resolve_references(self, record: FacilityRecord) -> dict[str, Any] | str:
        """Make sure every master row the record points at exists.

        Returns the ids to use, or a quarantine reason if the record's
        location contradicts what we already know.
        """
        self._ensure_state(record.state)
        if self._ensure_district(record.district, record.state.lgd_code) != record.state.lgd_code:
            return "district_not_in_state"

        sub_district = None
        if record.sub_district:
            parent = self._ensure_sub_district(record.sub_district, record.district.lgd_code)
            if parent == record.district.lgd_code:
                sub_district = record.sub_district.lgd_code
            else:
                self.report.warnings["sub_district_not_in_district"] += 1

        return {
            "sub_district": sub_district,
            "facility_type_id": (
                self._id_for("facility_types", record.facility_type, record.facility_type_code)
                if record.facility_type
                else None
            ),
            "system_ids": [self._id_for("systems_of_medicine", n) for n in record.systems_of_medicine],
            "speciality_ids": [self._id_for("specialities", n) for n in record.specialities],
        }

    def _write_facility(self, record: FacilityRecord, refs: dict, response: StoredResponse) -> bool:
        row = self.conn.execute(
            _UPSERT_FACILITY,
            {
                "facility_id": record.facility_id,
                "name": record.name,
                "status": record.status,
                "ownership_code": record.ownership_code,
                "facility_type_id": refs["facility_type_id"],
                "state": record.state.lgd_code,
                "district": record.district.lgd_code,
                "sub_district": refs["sub_district"],
                "village_name": record.village_name,
                "village_code": record.village_lgd_code,
                "address": record.address,
                "pincode": record.pincode,
                "latitude": record.latitude,
                "longitude": record.longitude,
                "abdm_software": record.abdm_software,
                "type_of_service": record.type_of_service,
                "phone": record.phone,
                "website": record.website,
                "response_id": response.id,
                "seen_at": response.fetched_at,
            },
        ).fetchone()

        infra = record.infrastructure
        if not infra.is_empty:
            self.conn.execute(
                _UPSERT_INFRASTRUCTURE,
                (record.facility_id, infra.has_icu_beds, infra.total_beds,
                 infra.icu_beds, infra.ventilators),
            )
        self._replace_links("facility_specialities", "speciality_id",
                            record.facility_id, refs["speciality_ids"])
        self._replace_links("facility_systems_of_medicine", "system_id",
                            record.facility_id, refs["system_ids"])
        self.conn.execute(
            "INSERT INTO facility_sightings (facility_id, response_id) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING",
            (record.facility_id, response.id),
        )
        return row[0]

    def _replace_links(self, table: str, column: str, facility_id: str, ids: list[int]) -> None:
        if not ids:
            return  # nothing published this time: keep what we had
        self.conn.execute(
            f"DELETE FROM {table} WHERE facility_id = %s AND NOT ({column} = ANY(%s))",
            (facility_id, ids),
        )
        self.conn.execute(
            f"INSERT INTO {table} (facility_id, {column}) SELECT %s, unnest(%s::int[]) "
            "ON CONFLICT DO NOTHING",
            (facility_id, ids),
        )

    # -- master rows --------------------------------------------------------

    def _load_districts(self, response: StoredResponse) -> None:
        state_code = int(response.source_key.split("|")[1])
        exists = self.conn.execute("SELECT 1 FROM states WHERE lgd_code = %s", (state_code,))
        if exists.fetchone() is None:
            self.report.warnings["districts_for_unknown_state"] += 1
            return
        for place in parse_lgd_list(response.body):
            self.conn.execute(
                """
                INSERT INTO districts (lgd_code, state_lgd_code, name) VALUES (%s, %s, %s)
                ON CONFLICT (lgd_code) DO UPDATE SET name = EXCLUDED.name
                """,
                (place.lgd_code, state_code, place.name),
            )

    def _ensure_state(self, place: Place) -> None:
        self.conn.execute(
            "INSERT INTO states (lgd_code, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (place.lgd_code, place.name),
        )

    def _ensure_district(self, place: Place, state_code: int) -> int:
        if place.lgd_code not in self._district_state:
            self.conn.execute(
                "INSERT INTO districts (lgd_code, state_lgd_code, name) VALUES (%s, %s, %s) "
                "ON CONFLICT (lgd_code) DO NOTHING",
                (place.lgd_code, state_code, place.name),
            )
            row = self.conn.execute(
                "SELECT state_lgd_code FROM districts WHERE lgd_code = %s", (place.lgd_code,)
            ).fetchone()
            self._district_state[place.lgd_code] = row[0]
        return self._district_state[place.lgd_code]

    def _ensure_sub_district(self, place: Place, district_code: int) -> int:
        if place.lgd_code not in self._sub_district_parent:
            self.conn.execute(
                "INSERT INTO sub_districts (lgd_code, district_lgd_code, name) VALUES (%s, %s, %s) "
                "ON CONFLICT (lgd_code) DO UPDATE SET "
                "name = coalesce(sub_districts.name, EXCLUDED.name)",
                (place.lgd_code, district_code, place.name),
            )
            row = self.conn.execute(
                "SELECT district_lgd_code FROM sub_districts WHERE lgd_code = %s", (place.lgd_code,)
            ).fetchone()
            self._sub_district_parent[place.lgd_code] = row[0]
        return self._sub_district_parent[place.lgd_code]

    def _id_for(self, table: str, name: str, code: str | None = None) -> int:
        """Id of the row in `table` with this name (any case), creating it if needed."""
        key = (table, name.casefold())
        if key not in self._ids_by_name:
            row = self.conn.execute(
                f"SELECT id FROM {table} WHERE lower(name) = lower(%s)", (name,)
            ).fetchone()
            if row is None:
                row = self.conn.execute(
                    f"INSERT INTO {table} (name, code) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING RETURNING id",
                    (name, code),
                ).fetchone()
            if row is None:
                # The code is already taken by another name; keep the name anyway.
                row = self.conn.execute(
                    f"INSERT INTO {table} (name) VALUES (%s) RETURNING id", (name,)
                ).fetchone()
            self._ids_by_name[key] = row[0]
        return self._ids_by_name[key]

    def _forget_cached_ids(self) -> None:
        self._district_state.clear()
        self._sub_district_parent.clear()
        self._ids_by_name.clear()

    # -- quarantine ---------------------------------------------------------

    def _quarantine(
        self, response: StoredResponse, index: int, facility_id: str | None,
        reasons: list[str], record: Any,
    ) -> None:
        self.report.records_quarantined += 1
        self.report.records_unreadable += bool(STRUCTURAL_REASONS.intersection(reasons))
        self.report.rejected.update(reasons)
        self._store_quarantine(response, index, facility_id, reasons, record)

    def _store_quarantine(
        self, response: StoredResponse, index: int, facility_id: str | None,
        reasons: list[str], record: Any,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO quarantined_records (response_id, record_index, facility_id, reasons, record)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (response_id, record_index) DO UPDATE SET
                facility_id = EXCLUDED.facility_id,
                reasons = EXCLUDED.reasons,
                record = EXCLUDED.record
            """,
            (response.id, index, facility_id, reasons, Jsonb(record)),
        )
