"""Turn database rows into the HFR-shaped JSON the API returns."""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def coordinate(value: Decimal | None) -> str | None:
    # HFR sends coordinates as strings; trailing zeros add nothing.
    if value is None:
        return None
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def yes_no(value: bool | None) -> str:
    return "Yes" if value else "No"


def code(value: Any) -> str | None:
    return None if value is None else str(value)


def facility_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "facilityId": row["facility_id"],
        "facilityName": row["name"],
        "facilityStatus": row["status"],
        "ownership": row["ownership"],
        "ownershipCode": row["ownership_code"],
        "facilityType": row["facility_type"],
        "facilityTypeCode": row["facility_type_code"],
        "systemOfMedicine": row["systems_of_medicine"],
        "systemOfMedicineCode": row["system_of_medicine_code"],
        "stateName": row["state_name"],
        "stateLGDCode": str(row["state_lgd_code"]),
        "districtName": row["district_name"],
        "districtLGDCode": str(row["district_lgd_code"]),
        "subDistrictName": row["sub_district_name"],
        "subDistrictLGDCode": code(row["sub_district_lgd_code"]),
        "address": row["address"],
        "pincode": row["pincode"],
        "latitude": coordinate(row["latitude"]),
        "longitude": coordinate(row["longitude"]),
        "hasIcuBeds": yes_no(row["has_icu_beds"]),
        "abdmSoftware": yes_no(row["abdm_software"]),
        "totalBeds": row["total_beds"],
    }


def facility_detail(row: dict[str, Any], systems: list[str], specialities: list[str]) -> dict:
    return {
        **facility_summary(row),
        "villageCityTownName": row["village_city_town_name"],
        "villageCityTownLGDCode": code(row["village_city_town_lgd_code"]),
        "typeOfService": row["type_of_service"],
        "phone": row["phone"],
        "website": row["website"],
        "photoUrl": row["photo_url"],
        "icuBeds": row["icu_beds"],
        "ventilators": row["ventilators"],
        "systemsOfMedicine": systems,
        "specialities": specialities,
        "firstSeenAt": row["first_seen_at"].isoformat(),
        "lastSeenAt": row["last_seen_at"].isoformat(),
    }
