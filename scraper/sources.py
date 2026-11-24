"""What the scraper knows about NHPR's public facility search.

All of it was read off the live site: the search page below and the
JavaScript bundle it loads. If NHPR changes its site, this module and
parser.py are the two places that need attention.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

SITE_ORIGIN = "https://nhpr.abdm.gov.in"
SEARCH_PAGE_URL = f"{SITE_ORIGIN}/nhpr/v4/search/facility"
ROBOTS_URL = f"{SITE_ORIGIN}/robots.txt"

# The search page talks to this API. We never call it directly: the page does,
# and we keep copies of the JSON it receives.
API_HOST = "apinhpr.abdm.gov.in"

# The results list shows 10 facilities at a time and stops offering
# "Load more" once 50 are on screen. The crawler stays inside that limit.
RESULTS_PAGE_SIZE = 10
RESULTS_DISPLAY_CAP = 50

OWNERSHIP_LABELS = {
    "G": "Government",
    "P": "Private",
    "PP": "Public Private Partnership",
}

_SEARCH = re.compile(r"/v4/hfr/facility/search/searchFacility\b")

# Master lists the search page loads by itself. Keeping them gives us real LGD
# names and codes for the reference tables without any extra requests.
_MASTER_LISTS = (
    ("districts", re.compile(r"/v4/hfr/master/lgdMasters/districtsOfState/(?P<key>\d+)")),
    ("states", re.compile(r"/v4/hfr/master/lgdMasters/states\b")),
    ("facility_types", re.compile(r"/v4/hfr/master/facilityTypeDetails/getAllActiveFacilityTypes\b")),
    ("systems_of_medicine", re.compile(r"/v4/hfr/master/mdropdown/type\?type=SystemMedicine\b")),
)


def is_search_response(url: str, method: str) -> bool:
    return method.upper() == "POST" and API_HOST in url and bool(_SEARCH.search(url))


def classify_master(url: str) -> tuple[str, str] | None:
    """Return (kind, source_key) for a master-list response, else None."""
    if API_HOST not in url:
        return None
    for kind, pattern in _MASTER_LISTS:
        match = pattern.search(url)
        if match:
            key = match.groupdict().get("key") or "all"
            return kind, f"{kind}|{key}"
    return None


def page_number_from_url(url: str) -> int | None:
    """The page index the site asked for (`pageNo`, zero-based), if present."""
    values = parse_qs(urlsplit(url).query).get("pageNo")
    if values and values[0].isdigit():
        return int(values[0])
    return None
