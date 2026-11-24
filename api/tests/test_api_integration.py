"""The API against a real Postgres, seeded through the scraper's own loader."""

import pytest
from fastapi.testclient import TestClient

from api.config import Settings
from api.main import create_app

pytestmark = pytest.mark.integration

APPENDIX_B_FIELDS = {
    "facilityId", "facilityName", "facilityStatus", "ownership", "ownershipCode", "facilityType",
    "systemOfMedicine", "stateName", "stateLGDCode", "districtName", "districtLGDCode", "address",
    "pincode", "latitude", "longitude", "hasIcuBeds", "abdmSoftware",
}


@pytest.fixture
def client(seeded_db):
    settings = Settings(database_url=seeded_db, allowed_origins="http://localhost:5173",
                        rate_limit_per_minute=1000)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]


class TestSearch:
    def test_empty_search_is_a_400_with_a_clear_message(self, client):
        assert_error(client.get("/api/facilities"), 400, "empty_search")

    def test_results_follow_the_hfr_search_shape(self, client):
        body = client.get("/api/facilities", params={"state": "3"}).json()
        assert set(body) == {"facilities", "totalFacilities", "numberOfPages", "message"}
        assert body["totalFacilities"] == 3
        assert body["message"] == "Request processed successfully"
        first = body["facilities"][0]
        assert set(first) >= APPENDIX_B_FIELDS
        assert first == client.get("/api/facilities", params={"state": "Punjab"}).json()[
            "facilities"][0]

    def test_coordinates_and_flags_are_formatted_like_hfr(self, client):
        body = client.get("/api/facilities", params={"facilityId": "IN0399000001"}).json()
        facility = body["facilities"][0]
        assert (facility["latitude"], facility["longitude"]) == ("31.634", "74.8723")
        assert (facility["hasIcuBeds"], facility["abdmSoftware"]) == ("Yes", "Yes")
        assert facility["stateLGDCode"] == "3"

    def test_name_search_tolerates_typos(self, client):
        body = client.get("/api/facilities", params={"name": "civl hospitl"}).json()
        assert [f["facilityId"] for f in body["facilities"]] == ["IN0399000001"]

    def test_facility_id_ignores_other_filters(self, client):
        body = client.get("/api/facilities",
                          params={"facilityId": "in0399000007", "state": "3"}).json()
        assert [f["facilityId"] for f in body["facilities"]] == ["IN0399000007"]

    def test_filters_sorting_and_paging(self, client):
        body = client.get("/api/facilities",
                          params={"state": "3", "sort": "beds", "pageSize": 2}).json()
        assert body["numberOfPages"] == 2
        assert [f["totalBeds"] for f in body["facilities"]] == [120, 10]

        page_two = client.get("/api/facilities",
                              params={"state": "3", "sort": "beds", "pageSize": 2, "page": 2})
        assert [f["facilityId"] for f in page_two.json()["facilities"]] == ["IN0399000006"]

        icu = client.get("/api/facilities", params={"state": "3", "icu": "yes"}).json()
        assert [f["facilityId"] for f in icu["facilities"]] == ["IN0399000001"]

        cardiology = client.get("/api/facilities", params={"speciality": "cardiology"}).json()
        assert cardiology["totalFacilities"] == 1

    @pytest.mark.parametrize(
        "params",
        [{"state": "3", "pageSize": 51}, {"pincode": "12345"}, {"facilityId": "IN12"},
         {"state": "3", "sort": "price"}, {"icu": "maybe"}, {"name": "a"}],
    )
    def test_invalid_input_is_a_400_with_details(self, client, params):
        response = client.get("/api/facilities", params=params)
        assert_error(response, 400, "invalid_parameters")
        assert response.json()["error"]["details"]

    def test_search_is_rate_limited(self, seeded_db):
        settings = Settings(database_url=seeded_db, rate_limit_per_minute=2)
        with TestClient(create_app(settings)) as limited:
            statuses = [limited.get("/api/facilities", params={"state": "3"}).status_code
                        for _ in range(3)]
            assert statuses == [200, 200, 429]
            blocked = limited.get("/api/facilities", params={"state": "3"})
            assert_error(blocked, 429, "rate_limited")
            assert int(blocked.headers["Retry-After"]) > 0
            assert limited.get("/health").status_code == 200  # only search is limited


class TestDetails:
    def test_includes_beds_and_specialities(self, client):
        body = client.get("/api/facilities/in0399000001").json()
        assert body["facilityId"] == "IN0399000001"
        assert (body["totalBeds"], body["icuBeds"], body["ventilators"]) == (120, 10, 8)
        assert body["specialities"] == ["Cardiology", "General Medicine"]
        assert body["subDistrictName"] == "Sample Tehsil"
        assert body["phone"] == "+919876543210"

    def test_unknown_id_is_404(self, client):
        assert_error(client.get("/api/facilities/IN0399999999"), 404, "facility_not_found")

    def test_malformed_id_is_400(self, client):
        assert_error(client.get("/api/facilities/not-an-id"), 400, "invalid_parameters")


class TestMastersStatsHealth:
    def test_states_and_their_districts(self, client):
        states = client.get("/api/masters/states").json()["states"]
        assert {"code": "3", "name": "Punjab", "facilityCount": 3} in states

        districts = client.get("/api/masters/states/3/districts").json()
        names = {d["name"]: d["facilityCount"] for d in districts["districts"]}
        assert names["Amritsar"] == 2 and names["Barnala"] == 0

        assert_error(client.get("/api/masters/states/99/districts"), 404, "state_not_found")

    def test_other_master_lists(self, client):
        ownership = client.get("/api/masters/ownership").json()["items"]
        assert {"code": "P", "name": "Private", "facilityCount": 2} in ownership
        assert_error(client.get("/api/masters/colours"), 404, "unknown_master_type")

    def test_stats(self, client):
        body = client.get("/api/stats").json()
        assert body["totalFacilities"] == 4
        assert (body["totalBeds"], body["icuBeds"], body["facilitiesWithIcu"]) == (130, 10, 1)
        assert body["byState"][0] == {"code": "3", "name": "Punjab", "facilities": 3}
        assert body["bedsByDistrict"][0] == {
            "code": "27", "name": "Amritsar", "stateCode": "3", "stateName": "Punjab",
            "facilities": 2, "totalBeds": 130, "icuBeds": 10,
        }

    def test_health_checks_the_database(self, client):
        assert client.get("/health").json() == {"status": "ok", "database": "ok"}

    def test_openapi_is_served(self, client):
        spec = client.get("/openapi.json").json()
        assert "/api/facilities/{facilityId}" in spec["paths"]
        assert client.get("/docs").status_code == 200

    def test_cors_only_allows_the_configured_origin(self, client):
        allowed = client.get("/health", headers={"Origin": "http://localhost:5173"})
        assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
        other = client.get("/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in other.headers
