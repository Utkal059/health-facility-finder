"""Small, pure clean-up helpers used by the parser. No I/O in here.

Each helper either returns a cleaned value, returns None when the value is
simply missing, or raises InvalidValue when something is present but wrong.
That last case is what sends a record to quarantine.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# How blank form fields tend to come back from registries.
_PLACEHOLDERS = {"", "-", "--", "na", "n/a", "nil", "null", "none", "undefined", "not available"}

INDIA_LATITUDE = (Decimal("6"), Decimal("37.5"))
INDIA_LONGITUDE = (Decimal("68"), Decimal("97.5"))
_SIX_PLACES = Decimal("0.000001")


class InvalidValue(ValueError):
    """A value was present but could not be cleaned into something valid.

    `reason` is a short code (for example "invalid_pincode") that ends up in
    the quarantine table and the run report.
    """

    def __init__(self, reason: str, value: object = None):
        super().__init__(f"{reason}: {value!r}")
        self.reason = reason
        self.value = value


def clean_text(value: object) -> str | None:
    """Unicode-normalise, collapse whitespace, and turn placeholders into None."""
    if value is None:
        return None
    text = " ".join(unicodedata.normalize("NFKC", str(value)).split())
    return None if text.casefold() in _PLACEHOLDERS else text


def clean_name(value: object) -> str | None:
    """Tidy a facility or place name without changing its spelling or case.

    Registry names are often typed in capitals, and acronyms like PHC, CHC and
    AIIMS make automatic title-casing wrong more often than right. Search is
    case-insensitive anyway, so the case is left as NHPR has it.
    """
    text = clean_text(value)
    if text is None:
        return None
    text = re.sub(r"([,;:])\1+", r"\1", text)  # ",," -> ","
    text = re.sub(r"\s+([,;:.])", r"\1", text)  # "Clinic ," -> "Clinic,"
    text = text.strip(" ,;:-'\"")
    return text or None


def clean_address(*parts: object) -> str | None:
    """Join address lines, dropping blanks and lines repeated verbatim."""
    lines: list[str] = []
    for part in parts:
        line = clean_name(part)
        if not line:
            continue
        line = re.sub(r",(?=\S)", ", ", line)  # "Lane,Ward 4" -> "Lane, Ward 4"
        if line.casefold() not in {existing.casefold() for existing in lines}:
            lines.append(line)
    return ", ".join(lines) or None


def normalize_facility_id(value: object) -> str:
    text = clean_text(value)
    if text is None:
        raise InvalidValue("missing_facility_id")
    facility_id = re.sub(r"\s", "", text).upper()
    if not re.fullmatch(r"IN\d{10}", facility_id):
        raise InvalidValue("invalid_facility_id", value)
    return facility_id


def normalize_pincode(value: object) -> str | None:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = clean_text(value)
    if text is None:
        return None
    digits = re.sub(r"[\s-]", "", text)
    if set(digits) == {"0"}:
        return None  # "000000" is what an untouched form field looks like
    if not re.fullmatch(r"[1-9]\d{5}", digits):
        raise InvalidValue("invalid_pincode", value)
    return digits


def normalize_phone(value: object) -> str | None:
    """Return the first Indian phone number in `value` as +91XXXXXXXXXX.

    Handles "+91-98765 43210", "098765 43210" and landlines like "0161-2345678".
    Raises InvalidValue if something is there but none of it is a valid number.
    """
    text = clean_text(value)
    if text is None:
        return None
    for chunk in re.split(r"[,/;|]| or ", text):
        digits = re.sub(r"\D", "", chunk)
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        elif len(digits) == 13 and digits.startswith("091"):
            digits = digits[3:]
        elif len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) == 10 and digits[0] != "0" and len(set(digits)) > 1:
            return "+91" + digits
    raise InvalidValue("invalid_phone", value)


def _coordinate(value: object) -> Decimal | None:
    text = clean_text(value)
    if text is None:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise InvalidValue("invalid_coordinates", value) from None
    if not number.is_finite():
        raise InvalidValue("invalid_coordinates", value)
    return number


def normalize_coordinates(
    latitude: object, longitude: object
) -> tuple[Decimal | None, Decimal | None, bool]:
    """Validate a latitude/longitude pair against India's bounding box.

    Returns (latitude, longitude, swapped). A pair of zeros means "not filled
    in" and becomes (None, None). A pair that only fits India with the two
    values swapped is swapped back and flagged, since that mistake is common
    and unambiguous. Anything else outside India raises InvalidValue.
    """
    lat, lon = _coordinate(latitude), _coordinate(longitude)
    if lat is None and lon is None:
        return None, None, False
    if lat is None or lon is None:
        raise InvalidValue("incomplete_coordinates", (latitude, longitude))
    if lat == 0 and lon == 0:
        return None, None, False

    def inside(la: Decimal, lo: Decimal) -> bool:
        return (
            INDIA_LATITUDE[0] <= la <= INDIA_LATITUDE[1]
            and INDIA_LONGITUDE[0] <= lo <= INDIA_LONGITUDE[1]
        )

    swapped = False
    if not inside(lat, lon):
        if not inside(lon, lat):
            raise InvalidValue("coordinates_outside_india", (latitude, longitude))
        lat, lon, swapped = lon, lat, True
    return (
        lat.quantize(_SIX_PLACES, rounding=ROUND_HALF_UP),
        lon.quantize(_SIX_PLACES, rounding=ROUND_HALF_UP),
        swapped,
    )


def split_geolocation(value: object) -> tuple[str | None, str | None]:
    """NHPR sends coordinates as one "lat,long" string."""
    text = clean_text(value)
    if text is None:
        return None, None
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 2:
        raise InvalidValue("invalid_coordinates", value)
    return parts[0], parts[1]


def parse_yes_no(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    text = clean_text(value)
    if text is None:
        return None
    folded = text.casefold()
    if folded in {"yes", "y", "true", "1"}:
        return True
    if folded in {"no", "n", "false", "0"}:
        return False
    return None


def parse_count(value: object, field: str) -> int | None:
    """Parse a non-negative whole number such as a bed count."""
    if value is None or isinstance(value, bool):
        return None
    text = clean_text(value)
    if text is None:
        return None
    try:
        number = Decimal(text.replace(",", ""))
    except InvalidOperation:
        raise InvalidValue(f"invalid_{field}", value) from None
    if not number.is_finite() or number != number.to_integral_value():
        raise InvalidValue(f"invalid_{field}", value)
    if number < 0:
        raise InvalidValue(f"negative_{field}", value)
    return int(number)


def parse_lgd_code(value: object) -> int | None:
    text = clean_text(value)
    if text is None:
        return None
    if not text.isdigit() or int(text) == 0:
        raise InvalidValue("invalid_lgd_code", value)
    return int(text)
