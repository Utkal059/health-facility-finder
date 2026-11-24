from __future__ import annotations

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, Request, Response

from api.db import get_conn
from api.errors import ApiError
from api.schemas import ErrorResponse, HealthResponse, StatsResponse

router = APIRouter()

_COUNTS = {
    "byState": """
        SELECT s.lgd_code::text AS code, s.name, count(*) AS facilities
        FROM facilities f JOIN states s ON s.lgd_code = f.state_lgd_code
        GROUP BY s.lgd_code ORDER BY facilities DESC, s.name""",
    "byFacilityType": """
        SELECT t.code, coalesce(t.name, 'Not published') AS name, count(*) AS facilities
        FROM facilities f LEFT JOIN facility_types t ON t.id = f.facility_type_id
        GROUP BY t.id ORDER BY facilities DESC, name""",
    "byOwnership": """
        SELECT o.code, coalesce(o.name, 'Not published') AS name, count(*) AS facilities
        FROM facilities f LEFT JOIN ownership_types o ON o.code = f.ownership_code
        GROUP BY o.code, o.name ORDER BY facilities DESC, name""",
    "byStatus": """
        SELECT NULL AS code, status AS name, count(*) AS facilities
        FROM facilities GROUP BY status ORDER BY facilities DESC, status""",
}


@router.get("/api/stats", response_model=StatsResponse, tags=["Stats"],
            summary="Counts by state, type and ownership; bed totals")
def stats(
    request: Request, response: Response,
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
):
    def load():
        totals = conn.execute(
            """
            SELECT count(*) AS facilities,
                   coalesce(sum(fi.total_beds), 0) AS total_beds,
                   coalesce(sum(fi.icu_beds), 0) AS icu_beds,
                   count(*) FILTER (WHERE fi.has_icu_beds) AS with_icu
            FROM facilities f
            LEFT JOIN facility_infrastructure fi ON fi.facility_id = f.facility_id
            """
        ).fetchone()
        result = {
            "totalFacilities": totals["facilities"],
            "totalBeds": totals["total_beds"],
            "icuBeds": totals["icu_beds"],
            "facilitiesWithIcu": totals["with_icu"],
        }
        for key, sql in _COUNTS.items():
            result[key] = conn.execute(sql).fetchall()
        result["bedsByDistrict"] = [
            {
                "code": str(row["lgd_code"]), "name": row["name"],
                "stateCode": str(row["state_lgd_code"]), "stateName": row["state_name"],
                "facilities": row["facilities"], "totalBeds": row["total_beds"],
                "icuBeds": row["icu_beds"],
            }
            for row in conn.execute(
                """
                SELECT d.lgd_code, d.name, s.lgd_code AS state_lgd_code, s.name AS state_name,
                       count(*) AS facilities,
                       coalesce(sum(fi.total_beds), 0) AS total_beds,
                       coalesce(sum(fi.icu_beds), 0) AS icu_beds
                FROM facilities f
                JOIN districts d ON d.lgd_code = f.district_lgd_code
                JOIN states s ON s.lgd_code = f.state_lgd_code
                LEFT JOIN facility_infrastructure fi ON fi.facility_id = f.facility_id
                GROUP BY d.lgd_code, s.lgd_code
                ORDER BY total_beds DESC, d.name
                """
            ).fetchall()
        ]
        return result

    response.headers["Cache-Control"] = "public, max-age=300"
    return request.app.state.cache.get_or_compute("stats", load)


@router.get("/health", response_model=HealthResponse, tags=["Health"],
            summary="Liveness, including a database round trip",
            responses={503: {"model": ErrorResponse}})
def health(request: Request):
    try:
        with request.app.state.pool.connection(timeout=3) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:
        raise ApiError(503, "database_unavailable", "The database is not reachable.") from exc
    return {"status": "ok", "database": "ok"}
