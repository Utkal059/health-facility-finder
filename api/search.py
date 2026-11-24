"""Build the SQL for GET /api/facilities.

Kept free of FastAPI and of the database so the rules can be unit-tested on
their own: which filters apply, how they combine, how results are ordered and
paged. Values always travel as bound parameters, never inside the SQL text.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Literal

SortOption = Literal["name", "district", "beds"]


class EmptySearchError(ValueError):
    """No filter was given. NHPR refuses empty searches, and so do we."""


@dataclass(frozen=True)
class SearchFilters:
    state: str | None = None
    district: str | None = None
    sub_district: str | None = None
    pincode: str | None = None
    name: str | None = None
    facility_id: str | None = None
    ownership: str | None = None
    facility_type: str | None = None
    system_of_medicine: str | None = None
    speciality: str | None = None
    icu: bool | None = None
    status: str | None = None
    sort: SortOption | None = None
    page: int = 1
    page_size: int = 10

    def __post_init__(self) -> None:
        # Treat whitespace-only values as "not given".
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, str):
                object.__setattr__(self, f.name, value.strip() or None)


@dataclass(frozen=True)
class SearchQuery:
    count_sql: str
    page_sql: str
    params: dict[str, object]


_FROM = """
FROM facilities f
LEFT JOIN facility_infrastructure fi ON fi.facility_id = f.facility_id"""

_SELECT = """
SELECT f.facility_id, f.name, f.status, f.ownership_code, o.name AS ownership,
       ft.name AS facility_type, ft.code AS facility_type_code,
       f.state_lgd_code, s.name AS state_name,
       f.district_lgd_code, d.name AS district_name,
       f.sub_district_lgd_code, sd.name AS sub_district_name,
       f.address, f.pincode, f.latitude, f.longitude, f.abdm_software,
       fi.has_icu_beds, fi.total_beds, fi.icu_beds,
       (SELECT string_agg(sm.name, ', ' ORDER BY sm.name)
          FROM facility_systems_of_medicine fsm
          JOIN systems_of_medicine sm ON sm.id = fsm.system_id
         WHERE fsm.facility_id = f.facility_id) AS systems_of_medicine,
       (SELECT min(sm.code)
          FROM facility_systems_of_medicine fsm
          JOIN systems_of_medicine sm ON sm.id = fsm.system_id
         WHERE fsm.facility_id = f.facility_id) AS system_of_medicine_code"""

_JOINS = """
JOIN states s ON s.lgd_code = f.state_lgd_code
JOIN districts d ON d.lgd_code = f.district_lgd_code
LEFT JOIN sub_districts sd ON sd.lgd_code = f.sub_district_lgd_code
LEFT JOIN ownership_types o ON o.code = f.ownership_code
LEFT JOIN facility_types ft ON ft.id = f.facility_type_id"""

# Each ORDER BY ends with facility_id so pages never overlap or skip rows.
_ORDER_BY = {
    "name": "f.name, f.facility_id",
    "district": "d.name, f.name, f.facility_id",
    "beds": "fi.total_beds DESC NULLS LAST, f.name, f.facility_id",
}
_BY_RELEVANCE = "word_similarity(%(name)s, f.name) DESC, f.name, f.facility_id"


def build_search_query(filters: SearchFilters) -> SearchQuery:
    conditions, params = _conditions(filters)
    if not conditions:
        raise EmptySearchError(
            "Add at least one filter, such as state, district, name or facilityId."
        )

    where = "\nWHERE " + "\n  AND ".join(conditions)
    if filters.sort:
        order_by = _ORDER_BY[filters.sort]
    elif "name" in params and not filters.facility_id:
        order_by = _BY_RELEVANCE  # best match first when searching by name
    else:
        order_by = _ORDER_BY["name"]

    params["limit"] = filters.page_size
    params["offset"] = (filters.page - 1) * filters.page_size
    return SearchQuery(
        count_sql=f"SELECT count(*) AS total{_FROM}{where}",
        page_sql=(
            f"{_SELECT}{_FROM}{_JOINS}{where}\nORDER BY {order_by}"
            "\nLIMIT %(limit)s OFFSET %(offset)s"
        ),
        params=params,
    )


def _conditions(f: SearchFilters) -> tuple[list[str], dict[str, object]]:
    # The brief: when facilityId is given, every other filter is ignored.
    if f.facility_id:
        return ["f.facility_id = %(facility_id)s"], {"facility_id": f.facility_id.upper()}

    conditions: list[str] = []
    params: dict[str, object] = {}

    def add(sql: str, **values: object) -> None:
        conditions.append(sql)
        params.update(values)

    # State, district and sub-district take an LGD code or a name.
    if f.state:
        if f.state.isdigit():
            add("f.state_lgd_code = %(state)s", state=int(f.state))
        else:
            add("f.state_lgd_code IN (SELECT lgd_code FROM states WHERE lower(name) = lower(%(state)s))",
                state=f.state)
    if f.district:
        if f.district.isdigit():
            add("f.district_lgd_code = %(district)s", district=int(f.district))
        else:
            add("f.district_lgd_code IN "
                "(SELECT lgd_code FROM districts WHERE lower(name) = lower(%(district)s))",
                district=f.district)
    if f.sub_district:
        if f.sub_district.isdigit():
            add("f.sub_district_lgd_code = %(sub_district)s", sub_district=int(f.sub_district))
        else:
            add("f.sub_district_lgd_code IN "
                "(SELECT lgd_code FROM sub_districts WHERE lower(name) = lower(%(sub_district)s))",
                sub_district=f.sub_district)

    if f.pincode:
        add("f.pincode = %(pincode)s", pincode=f.pincode)

    if f.name:
        # ILIKE catches partial names ("civil hosp"); the word-similarity
        # operator <% catches small typos ("apolo"). Both use the trigram index.
        add("(f.name ILIKE %(name_like)s OR %(name)s <%% f.name)",
            name=f.name, name_like=f"%{_escape_like(f.name)}%")

    # Master filters accept either the code or the display name.
    if f.ownership:
        add("f.ownership_code IN (SELECT code FROM ownership_types "
            "WHERE upper(code) = upper(%(ownership)s) OR lower(name) = lower(%(ownership)s))",
            ownership=f.ownership)
    if f.facility_type:
        add("f.facility_type_id IN (SELECT id FROM facility_types "
            "WHERE code = %(facility_type)s OR lower(name) = lower(%(facility_type)s))",
            facility_type=f.facility_type)
    if f.system_of_medicine:
        add("EXISTS (SELECT 1 FROM facility_systems_of_medicine fsm "
            "JOIN systems_of_medicine sm ON sm.id = fsm.system_id "
            "WHERE fsm.facility_id = f.facility_id AND (sm.code = %(system)s "
            "OR lower(sm.name) = lower(%(system)s)))",
            system=f.system_of_medicine)
    if f.speciality:
        add("EXISTS (SELECT 1 FROM facility_specialities fs "
            "JOIN specialities sp ON sp.id = fs.speciality_id "
            "WHERE fs.facility_id = f.facility_id AND (sp.code = %(speciality)s "
            "OR lower(sp.name) = lower(%(speciality)s)))",
            speciality=f.speciality)

    if f.icu is True:
        add("fi.has_icu_beds IS TRUE")
    elif f.icu is False:
        # NHPR shows "ICU Services: No" when nothing was published, so do we.
        add("fi.has_icu_beds IS NOT TRUE")

    if f.status:
        add("lower(f.status) = lower(%(status)s)", status=f.status)

    return conditions, params


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
