from __future__ import annotations

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, Path, Request, Response

from api.db import get_conn
from api.errors import ApiError
from api.schemas import DistrictsResponse, ErrorResponse, MasterListResponse, StatesResponse

router = APIRouter(prefix="/api/masters", tags=["Master lists"])

CACHE_HEADER = "public, max-age=300"

# Each list comes with how many loaded facilities use it, so a client can
# hide entries that would only ever return nothing.
_MASTER_QUERIES = {
    "ownership": """
        SELECT o.code, o.name, count(f.facility_id) AS facilities
        FROM ownership_types o LEFT JOIN facilities f ON f.ownership_code = o.code
        GROUP BY o.code, o.name ORDER BY o.name""",
    "facility-types": """
        SELECT t.code, t.name, count(f.facility_id) AS facilities
        FROM facility_types t LEFT JOIN facilities f ON f.facility_type_id = t.id
        GROUP BY t.id ORDER BY t.name""",
    "systems-of-medicine": """
        SELECT sm.code, sm.name, count(l.facility_id) AS facilities
        FROM systems_of_medicine sm
        LEFT JOIN facility_systems_of_medicine l ON l.system_id = sm.id
        GROUP BY sm.id ORDER BY sm.name""",
    "specialities": """
        SELECT sp.code, sp.name, count(l.facility_id) AS facilities
        FROM specialities sp LEFT JOIN facility_specialities l ON l.speciality_id = sp.id
        GROUP BY sp.id ORDER BY sp.name""",
}


def _place(row: dict) -> dict:
    return {"code": str(row["lgd_code"]), "name": row["name"], "facilityCount": row["facilities"]}


@router.get("/states", response_model=StatesResponse, summary="States")
def list_states(
    request: Request, response: Response,
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
):
    def load():
        rows = conn.execute(
            """
            SELECT s.lgd_code, s.name, count(f.facility_id) AS facilities
            FROM states s LEFT JOIN facilities f ON f.state_lgd_code = s.lgd_code
            GROUP BY s.lgd_code ORDER BY s.name
            """
        ).fetchall()
        return {"states": [_place(row) for row in rows]}

    response.headers["Cache-Control"] = CACHE_HEADER
    return request.app.state.cache.get_or_compute("states", load)


@router.get(
    "/states/{stateCode}/districts",
    response_model=DistrictsResponse,
    summary="Districts in one state",
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def list_districts(
    request: Request, response: Response,
    stateCode: Annotated[str, Path(pattern=r"^[0-9]{1,2}$", description="State LGD code")],
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
):
    code = int(stateCode)

    def load():
        state = conn.execute(
            """
            SELECT s.lgd_code, s.name, count(f.facility_id) AS facilities
            FROM states s LEFT JOIN facilities f ON f.state_lgd_code = s.lgd_code
            WHERE s.lgd_code = %s GROUP BY s.lgd_code
            """,
            (code,),
        ).fetchone()
        if state is None:
            return None
        rows = conn.execute(
            """
            SELECT d.lgd_code, d.name, count(f.facility_id) AS facilities
            FROM districts d LEFT JOIN facilities f ON f.district_lgd_code = d.lgd_code
            WHERE d.state_lgd_code = %s GROUP BY d.lgd_code ORDER BY d.name
            """,
            (code,),
        ).fetchall()
        return {"state": _place(state), "districts": [_place(row) for row in rows]}

    result = request.app.state.cache.get_or_compute(f"districts:{code}", load)
    if result is None:
        raise ApiError(404, "state_not_found", f"No state with LGD code {code}.")
    response.headers["Cache-Control"] = CACHE_HEADER
    return result


@router.get(
    "/{type}",
    response_model=MasterListResponse,
    summary="Other master lists",
    description="`type` is one of: " + ", ".join(_MASTER_QUERIES),
    responses={404: {"model": ErrorResponse}},
)
def list_master(
    request: Request, response: Response, type: str,
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
):
    sql = _MASTER_QUERIES.get(type)
    if sql is None:
        raise ApiError(404, "unknown_master_type", f"There is no master list called {type!r}.",
                       details={"validTypes": list(_MASTER_QUERIES)})

    def load():
        rows = conn.execute(sql).fetchall()
        return {
            "type": type,
            "items": [
                {"code": row["code"], "name": row["name"], "facilityCount": row["facilities"]}
                for row in rows
            ],
        }

    response.headers["Cache-Control"] = CACHE_HEADER
    return request.app.state.cache.get_or_compute(f"master:{type}", load)
