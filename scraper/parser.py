"""Turn raw NHPR JSON into clean records. Pure functions, no I/O.

Field names follow what NHPR's own results and details pages read from the
search response: facName, alternateId, facOwnership, geolocation,
medicalInfraRequestDTO, specialityDtls and so on. The details page renders
that same record without fetching anything else, so a single search record
already holds everything the details page shows.

The challenge's Appendix A names (facilityName, facilityId, ...) are accepted
as fallbacks, which keeps the parser working if NHPR renames things towards
the documented HFR API.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from scraper.normalize import (
    InvalidValue,
    clean_address,
    clean_name,
    clean_text,
    normalize_coordinates,
    normalize_facility_id,
    normalize_phone,
    normalize_pincode,
    parse_count,
    parse_lgd_code,
    parse_yes_no,
    split_geolocation,
)
from scraper.sources import OWNERSHIP_LABELS

_OWNERSHIP_CODES_BY_LABEL = {label.casefold(): code for code, label in OWNERSHIP_LABELS.items()}


class PageShapeError(ValueError):
    """The response is not shaped like a page of search results at all."""


@dataclass(frozen=True)
class Place:
    lgd_code: int
    name: str | None  # only a sub-district may lack one: NHPR sends those as a bare code


@dataclass(frozen=True)
class Infrastructure:
    has_icu_beds: bool | None = None
    total_beds: int | None = None
    icu_beds: int | None = None
    ventilators: int | None = None

    @property
    def is_empty(self) -> bool:
        return all(
            value is None
            for value in (self.has_icu_beds, self.total_beds, self.icu_beds, self.ventilators)
        )


@dataclass(frozen=True)
class FacilityRecord:
    facility_id: str
    name: str
    status: str
    state: Place
    district: Place
    sub_district: Place | None = None
    village_name: str | None = None
    village_lgd_code: int | None = None
    ownership_code: str | None = None
    facility_type: str | None = None
    facility_type_code: str | None = None
    systems_of_medicine: tuple[str, ...] = ()
    specialities: tuple[str, ...] = ()
    address: str | None = None
    pincode: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    abdm_software: bool | None = None
    type_of_service: str | None = None
    phone: str | None = None
    website: str | None = None
    infrastructure: Infrastructure = field(default_factory=Infrastructure)


@dataclass(frozen=True)
class ParseResult:
    """Either a clean record, or the reasons there isn't one. Never both."""

    record: FacilityRecord | None
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    facility_id: str | None = None  # best guess, so quarantined rows stay findable


@dataclass(frozen=True)
class SearchPage:
    records: list[Any]
    total_results: int | None = None
    total_pages: int | None = None
    page_number: int | None = None


@dataclass(frozen=True)
class MasterEntry:
    name: str
    code: str | None = None


# --------------------------------------------------------------------------
# Search pages


def parse_search_page(body: object) -> SearchPage:
    """Find the list of facility records in a search response.

    NHPR returns a Spring-style page ({"content": [...], "totalElements": n});
    the challenge's own API shape ({"facilities": [...]}) is accepted too.
    """
    if isinstance(body, list):
        return SearchPage(records=body)
    if not isinstance(body, Mapping):
        raise PageShapeError(f"expected a JSON object or list, got {type(body).__name__}")

    for key in ("content", "facilities", "data", "results"):
        if isinstance(body.get(key), list):
            records = body[key]
            break
    else:
        # A search with no results may leave the list out altogether.
        if _whole_number(body.get("totalElements", body.get("totalFacilities"))) == 0:
            return SearchPage(records=[], total_results=0)
        raise PageShapeError(f"no list of facilities in response (keys: {sorted(body)[:12]})")

    pageable = body.get("pageable") if isinstance(body.get("pageable"), Mapping) else {}
    return SearchPage(
        records=records,
        total_results=_whole_number(body.get("totalElements", body.get("totalFacilities"))),
        total_pages=_whole_number(body.get("totalPages", body.get("numberOfPages"))),
        page_number=_whole_number(pageable.get("pageNumber", body.get("number"))),
    )


def _whole_number(value: object) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Master lists


def parse_lgd_list(body: object) -> list[Place]:
    """States or districts, as NHPR's LGD master endpoints return them."""
    if not isinstance(body, list):
        raise PageShapeError("expected a list of LGD locations")
    places = []
    for item in body:
        if not isinstance(item, Mapping):
            continue
        try:
            code = parse_lgd_code(item.get("locId"))
        except InvalidValue:
            continue
        name = clean_name(item.get("locName"))
        if code is not None and name and str(item.get("activeYn", "Y")).upper() != "N":
            places.append(Place(code, name))
    return places


def parse_named_list(body: object) -> list[MasterEntry]:
    """Facility types or systems of medicine from NHPR's dropdown endpoints.

    These lists come in a few shapes ({"id", "value"}, {"code", "name"}, or
    plain strings), so this takes whichever name and id fields are present.
    """
    items = body.get("data") if isinstance(body, Mapping) else body
    if not isinstance(items, list):
        raise PageShapeError("expected a list of master entries")
    entries: dict[str, MasterEntry] = {}
    for item in items:
        if isinstance(item, str):
            name, code = clean_name(item), None
        elif isinstance(item, Mapping):
            name = clean_name(_first(item, "value", "name", "facilityType", "label", "desc"))
            code = clean_text(_first(item, "id", "code", "key"))
        else:
            continue
        if name and name.casefold() != "all":
            entries.setdefault(name.casefold(), MasterEntry(name=name, code=code))
    return list(entries.values())


# --------------------------------------------------------------------------
# Facility records


def parse_facility(raw: object) -> ParseResult:
    """Clean and validate one facility record from a search response.

    Every problem is collected rather than stopping at the first, so the
    quarantine table says everything that was wrong with a record.
    """
    if not isinstance(raw, Mapping):
        return ParseResult(record=None, reasons=("record_not_an_object",))

    reasons: list[str] = []
    warnings: list[str] = []

    def attempt(fn, *args):
        try:
            return fn(*args)
        except InvalidValue as exc:
            reasons.append(exc.reason)
            return None

    facility_id = attempt(normalize_facility_id, _first(raw, "alternateId", "facilityId", "hfrId"))
    name = clean_name(_first(raw, "facName", "facilityName"))
    if name is None:
        reasons.append("missing_name")
    status = _clean_status(_first(raw, "status", "facilityStatus"))
    if status is None:
        reasons.append("missing_status")

    state = attempt(_place, raw, "state", "stateLGDCode", "stateName")
    if state is None and "invalid_state" not in reasons:
        reasons.append("missing_state")
    district = attempt(_place, raw, "district", "districtLGDCode", "districtName")
    if district is None and "invalid_district" not in reasons:
        reasons.append("missing_district")
    # Sub-district and village are optional extras; a broken one is dropped
    # with a warning instead of costing us the whole facility.
    try:
        sub_district = _place(raw, "subDistrict", "subDistrictLGDCode", "subDistrictName")
    except InvalidValue:
        sub_district = None
        warnings.append("sub_district_dropped")
    village = _location_object(raw, "vilCityTown", "villageCityTown") or {
        "locId": raw.get("villageCityTownLGDCode"),
        "locName": raw.get("villageCityTownName"),
    }
    village_name = clean_name(village.get("locName"))
    village_code = _quiet(parse_lgd_code, village.get("locId"))
    # NHPR sometimes joins the wrong village: facilities in Ludhiana came back
    # with villages in Kashmir. A village names its parent sub-district, so one
    # whose parent isn't the facility's own sub-district is not believed.
    village_parent = _quiet(parse_lgd_code, village.get("locParntId"))
    if sub_district and village_parent and village_parent != sub_district.lgd_code:
        village_name = village_code = None
        warnings.append("village_not_in_sub_district")

    pincode = attempt(normalize_pincode, raw.get("pincode"))
    latitude, longitude = _coordinates(raw, reasons, warnings)
    infrastructure = _infrastructure(raw, reasons)

    phone = None
    try:
        phone = normalize_phone(_first(raw, "mobileNo", "landlineNo", "phone"))
    except InvalidValue:
        warnings.append("phone_dropped")  # not a constraint, so not worth a quarantine

    ownership_code = _ownership_code(_first(raw, "facOwnership", "ownershipCode", "ownership"))
    if ownership_code is None and clean_text(_first(raw, "facOwnership", "ownershipCode")):
        warnings.append("unknown_ownership")

    facility_type_raw = raw.get("facilityType")
    if isinstance(facility_type_raw, Mapping):
        facility_type = clean_name(_first(facility_type_raw, "value", "name"))
        facility_type_code = clean_text(_first(facility_type_raw, "id", "code"))
    else:
        facility_type = clean_name(facility_type_raw)
        facility_type_code = clean_text(_first(raw, "facilityTypeCode", "facilityTypeId"))

    if facility_id and state and int(facility_id[2:4]) != state.lgd_code:
        warnings.append("facility_id_state_mismatch")

    if reasons:
        return ParseResult(
            record=None,
            reasons=tuple(dict.fromkeys(reasons)),
            warnings=tuple(warnings),
            facility_id=facility_id or clean_text(_first(raw, "alternateId", "facilityId")),
        )

    record = FacilityRecord(
        facility_id=facility_id,
        name=name,
        status=status,
        state=state,
        district=district,
        sub_district=sub_district,
        village_name=village_name,
        village_lgd_code=village_code,
        ownership_code=ownership_code,
        facility_type=facility_type,
        facility_type_code=facility_type_code,
        systems_of_medicine=_name_list(_first(raw, "systemOfMedicine", "systemsOfMedicine")),
        specialities=_specialities(raw),
        address=clean_address(
            *(raw.get(key) for key in ("address1", "address2", "address3", "address"))
        ),
        pincode=pincode,
        latitude=latitude,
        longitude=longitude,
        abdm_software=parse_yes_no(raw.get("abdmSoftware")),
        type_of_service=clean_name(raw.get("typeOfService")),
        phone=phone,
        website=_website(raw.get("facWebsite") or raw.get("website")),
        infrastructure=infrastructure,
    )
    return ParseResult(record=record, warnings=tuple(warnings), facility_id=facility_id)


def _first(mapping: Mapping, *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return None


def _quiet(fn, *args):
    try:
        return fn(*args)
    except InvalidValue:
        return None


def _clean_status(value: object) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    # "APPROVED" and "approved" both become "Approved"; mixed case is kept.
    return text.capitalize() if text.isupper() or text.islower() else text


def _location_object(raw: Mapping, *keys: str) -> Mapping | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _place(raw: Mapping, key: str, code_key: str, name_key: str) -> Place | None:
    """Read a {locId, locName} object, or a flat code/name pair."""
    what = "state" if key == "state" else "district" if key == "district" else "sub_district"
    obj = raw.get(key)
    if isinstance(obj, Mapping):
        code_value, name_value = obj.get("locId"), obj.get("locName")
    else:
        code_value, name_value = raw.get(code_key), raw.get(name_key)
        if isinstance(obj, str):
            if obj.strip().isdecimal():
                code_value = obj if code_value is None else code_value
            else:
                name_value = obj if name_value is None else name_value

    name = clean_name(name_value)
    try:
        code = parse_lgd_code(code_value)
    except InvalidValue:
        raise InvalidValue(f"invalid_{what}", code_value) from None
    if code is None and name is None:
        return None
    if code is not None and name is None and what == "sub_district":
        return Place(code, None)
    if code is None or name is None:
        raise InvalidValue(f"invalid_{what}", obj if obj is not None else (code_value, name_value))
    return Place(code, name)


def _coordinates(raw: Mapping, reasons: list[str], warnings: list[str]):
    try:
        if raw.get("geolocation") or raw.get("geoLocation"):
            lat_text, lon_text = split_geolocation(raw.get("geolocation") or raw.get("geoLocation"))
        else:
            lat_text, lon_text = raw.get("latitude"), raw.get("longitude")
        latitude, longitude, swapped = normalize_coordinates(lat_text, lon_text)
    except InvalidValue as exc:
        reasons.append(exc.reason)
        return None, None
    if swapped:
        warnings.append("coordinates_swapped")
    return latitude, longitude


# Field names on NHPR's details page. ICU beds are published either split by
# ventilator or by ICU level, depending on the facility type.
_ICU_BY_VENTILATOR = ("icuBedsWithVent", "icuBedsWithoutVent")
_ICU_BY_LEVEL = (
    "noOfLevel1IcuBedWithVent",
    "noOfLevel1IcuBedWithOutVent",
    "noOfLevel2IcuBeds",
    "noOfLevel3IcuBeds",
)


def _infrastructure(raw: Mapping, reasons: list[str]) -> Infrastructure:
    rows = raw.get("medicalInfraRequestDTO")
    rows = [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []
    sources = [*rows, raw]

    def value(key: str) -> object:
        # Same rule as NHPR's details page: first non-empty value wins.
        for source in sources:
            found = source.get(key)
            if found is not None and found != "":
                return found
        return None

    def count(key: str, label: str) -> int | None:
        try:
            return parse_count(value(key), label)
        except InvalidValue as exc:
            reasons.append(exc.reason)
            return None

    total_beds = count("totalBeds", "total_beds")
    ventilators = count("ventillators", "ventilators")  # NHPR's spelling
    if ventilators is None:
        ventilators = count("ventilators", "ventilators")

    icu_beds = None
    for group in (_ICU_BY_VENTILATOR, _ICU_BY_LEVEL, ("icuBeds",)):
        parts = [count(key, "icu_beds") for key in group]
        present = [part for part in parts if part is not None]
        if present:
            icu_beds = sum(present)
            break

    flags = [parse_yes_no(source.get("hasIcuBeds")) for source in sources]
    if True in flags:
        has_icu = True
    elif False in flags:
        has_icu = False
    else:
        has_icu = True if icu_beds else None

    if total_beds is not None and icu_beds is not None and icu_beds > total_beds:
        reasons.append("icu_beds_exceed_total_beds")

    return Infrastructure(
        has_icu_beds=has_icu, total_beds=total_beds, icu_beds=icu_beds, ventilators=ventilators
    )


def _ownership_code(value: object) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    if text.upper() in OWNERSHIP_LABELS:
        return text.upper()
    return _OWNERSHIP_CODES_BY_LABEL.get(text.casefold())


def _name_list(value: object) -> tuple[str, ...]:
    """Names from a list or a comma-separated string, de-duplicated."""
    if value is None:
        return ()
    items: Iterable[object] = value if isinstance(value, list) else str(value).split(",")
    seen: dict[str, str] = {}
    for item in items:
        if isinstance(item, Mapping):
            item = _first(item, "name", "value", "specName")
        name = clean_name(item)
        if name and name.casefold() != "all":
            seen.setdefault(name.casefold(), name)
    return tuple(sorted(seen.values(), key=str.casefold))


def _specialities(raw: Mapping) -> tuple[str, ...]:
    details = raw.get("specialityDtls")
    if isinstance(details, list):
        # NHPR keeps withdrawn rows and marks them inactive.
        return _name_list([
            d.get("specName") if isinstance(d, Mapping) else d
            for d in details
            if not (isinstance(d, Mapping) and str(d.get("activeYn", "Y")).upper() == "N")
        ])
    return _name_list(raw.get("specialities"))


def _website(value: object) -> str | None:
    text = clean_text(value)
    if text is None or "." not in text or " " in text:
        return None
    return text if text.lower().startswith(("http://", "https://")) else f"https://{text}"
