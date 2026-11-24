from __future__ import annotations

import math
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Query, Request, Response

from api.db import get_conn
from api.errors import ApiError
from api.rate_limit import search_rate_limit
from api.schemas import ErrorResponse, FacilityDetail, SearchResponse
from api.search import EmptySearchError, SearchFilters, build_search_query
from api.serializers import facility_detail, facility_summary

router = APIRouter(prefix="/api/facilities", tags=["Facilities"])

FACILITY_ID = r"^[Ii][Nn][0-9]{10}$"
ERRORS = {400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}}

Text = Annotated[str | None, Query(max_length=100)]


@router.get(
    "",
    response_model=SearchResponse,
    summary="Search facilities",
    description=(
        "At least one filter is required. If `facilityId` is given, every other filter is "
        "ignored. `name` matches partial names and tolerates small typos. Rate limited per IP."
    ),
    responses={400: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
    dependencies=[Depends(search_rate_limit)],
)
def search_facilities(
    request: Request,
    response: Response,
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
    state: Annotated[str | None, Query(max_length=60, description="LGD code (3) or name (Punjab)")] = None,
    district: Annotated[str | None, Query(max_length=60, description="LGD code or name")] = None,
    subDistrict: Annotated[str | None, Query(max_length=60, description="LGD code or name")] = None,
    pincode: Annotated[str | None, Query(pattern=r"^[0-9]{6}$")] = None,
    name: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
    facilityId: Annotated[str | None, Query(pattern=FACILITY_ID)] = None,
    ownership: Annotated[str | None, Query(max_length=40, description="Code (G, P, PP) or name")] = None,
    facilityType: Text = None,
    systemOfMedicine: Text = None,
    speciality: Text = None,
    icu: Annotated[Literal["yes", "no"] | None, Query(description="ICU services")] = None,
    status: Annotated[str | None, Query(max_length=40, description="e.g. Approved")] = None,
    sort: Literal["name", "district", "beds"] | None = None,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=50)] = 10,
):
    filters = SearchFilters(
        state=state, district=district, sub_district=subDistrict, pincode=pincode, name=name,
        facility_id=facilityId, ownership=ownership, facility_type=facilityType,
        system_of_medicine=systemOfMedicine, speciality=speciality,
        icu=None if icu is None else icu == "yes", status=status, sort=sort,
        page=page, page_size=pageSize,
    )
    try:
        query = build_search_query(filters)
    except EmptySearchError as exc:
        raise ApiError(400, "empty_search", str(exc)) from exc

    total = conn.execute(query.count_sql, query.params).fetchone()["total"]
    rows = conn.execute(query.page_sql, query.params).fetchall() if total else []

    response.headers["X-RateLimit-Limit"] = str(request.app.state.search_limiter.limit)
    response.headers["X-RateLimit-Remaining"] = str(request.state.rate_limit_remaining)
    return {
        "facilities": [facility_summary(row) for row in rows],
        "totalFacilities": total,
        "numberOfPages": math.ceil(total / pageSize),
        "message": "Request processed successfully",
    }


_DETAIL_SQL = """
SELECT f.*, o.name AS ownership, ft.name AS facility_type, ft.code AS facility_type_code,
       s.name AS state_name, d.name AS district_name, sd.name AS sub_district_name,
       fi.has_icu_beds, fi.total_beds, fi.icu_beds, fi.ventilators,
       ARRAY(SELECT sm.name FROM facility_systems_of_medicine fsm
               JOIN systems_of_medicine sm ON sm.id = fsm.system_id
              WHERE fsm.facility_id = f.facility_id ORDER BY sm.name) AS systems,
       (SELECT min(sm.code) FROM facility_systems_of_medicine fsm
          JOIN systems_of_medicine sm ON sm.id = fsm.system_id
         WHERE fsm.facility_id = f.facility_id) AS system_of_medicine_code,
       ARRAY(SELECT sp.name FROM facility_specialities fs
               JOIN specialities sp ON sp.id = fs.speciality_id
              WHERE fs.facility_id = f.facility_id ORDER BY sp.name) AS specialities
FROM facilities f
JOIN states s ON s.lgd_code = f.state_lgd_code
JOIN districts d ON d.lgd_code = f.district_lgd_code
LEFT JOIN sub_districts sd ON sd.lgd_code = f.sub_district_lgd_code
LEFT JOIN ownership_types o ON o.code = f.ownership_code
LEFT JOIN facility_types ft ON ft.id = f.facility_type_id
LEFT JOIN facility_infrastructure fi ON fi.facility_id = f.facility_id
WHERE f.facility_id = %(facility_id)s
"""


@router.get(
    "/{facilityId}",
    response_model=FacilityDetail,
    summary="One facility, with beds and specialities",
    responses=ERRORS,
)
def get_facility(
    facilityId: Annotated[str, Path(pattern=FACILITY_ID, examples=["IN0310000334"])],
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
):
    facility_id = facilityId.upper()
    row = conn.execute(_DETAIL_SQL, {"facility_id": facility_id}).fetchone()
    if row is None:
        raise ApiError(404, "facility_not_found", f"No facility with ID {facility_id}.")
    row["systems_of_medicine"] = ", ".join(row["systems"]) or None
    return facility_detail(row, row["systems"], row["specialities"])
