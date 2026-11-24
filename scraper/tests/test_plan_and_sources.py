import pytest

from scraper.plan import PlanError, load_plan, tasks_from_plan
from scraper.sources import classify_master, is_search_response, page_number_from_url
from scraper.storage import CrawlTask, body_hash, strip_blobs

API = "https://apinhpr.abdm.gov.in/v4"


class TestPlan:
    def test_the_committed_plan_covers_the_brief(self):
        tasks = load_plan("scraper/crawl_plan.toml")
        assert len({t.state_name for t in tasks}) >= 5
        assert len({(t.state_name, t.district_name) for t in tasks}) >= 25

    def test_ownership_filters_multiply_searches(self):
        tasks = tasks_from_plan({
            "ownership_filters": ["G", "P"],
            "states": [{"name": "Punjab", "districts": ["Amritsar"]}],
        })
        assert tasks == [CrawlTask("Punjab", "Amritsar", "G"), CrawlTask("Punjab", "Amritsar", "P")]

    def test_duplicate_searches_are_refused(self):
        with pytest.raises(PlanError, match="twice"):
            tasks_from_plan({"states": [{"name": "Punjab", "districts": ["Amritsar", "Amritsar"]}]})

    def test_unknown_ownership_is_refused(self):
        with pytest.raises(PlanError, match="ownership"):
            tasks_from_plan({"ownership_filters": ["X"],
                             "states": [{"name": "Punjab", "districts": ["Amritsar"]}]})


class TestSources:
    def test_search_requests(self):
        assert is_search_response(f"{API}/hfr/facility/search/searchFacility?pageNo=1", "POST")
        assert not is_search_response(f"{API}/hfr/facility/search/searchFacility", "OPTIONS")

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            (f"{API}/hfr/master/lgdMasters/districtsOfState/3", ("districts", "districts|3")),
            (f"{API}/hfr/master/lgdMasters/states", ("states", "states|all")),
            (f"{API}/hfr/master/facilityTypeDetails/getAllActiveFacilityTypes",
             ("facility_types", "facility_types|all")),
            (f"{API}/hfr/master/mdropdown/type?type=SystemMedicine",
             ("systems_of_medicine", "systems_of_medicine|all")),
            (f"{API}/hfr/master/mdropdown/type?type=ServiceType", None),
            ("https://elsewhere.example/lgdMasters/states", None),
        ],
    )
    def test_master_lists_are_recognised(self, url, expected):
        assert classify_master(url) == expected

    def test_page_number_comes_from_the_query_string(self):
        assert page_number_from_url(f"{API}/x?pageNo=3&pageSize=10") == 3
        assert page_number_from_url(f"{API}/x") is None


class TestRawStorage:
    def test_base64_images_are_cut_out_and_recorded(self):
        photo = "iVBORw0KGgo" * 100
        body, stripped = strip_blobs({"content": [{"facName": "A", "buildImage": photo}]})
        assert body == {"content": [{"facName": "A", "buildImage": None}]}
        assert stripped[0]["path"] == "content[0].buildImage"
        assert stripped[0]["length"] == len(photo)

    def test_ordinary_text_is_left_alone(self):
        body = {"aboutUs": "A long description. " * 50}
        assert strip_blobs(body) == (body, [])

    def test_hash_ignores_key_order(self):
        assert body_hash({"a": 1, "b": [1, 2]}) == body_hash({"b": [1, 2], "a": 1})
