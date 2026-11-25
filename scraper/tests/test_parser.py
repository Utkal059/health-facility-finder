import json
from decimal import Decimal
from pathlib import Path

import pytest

from scraper.parser import (
    Infrastructure,
    PageShapeError,
    Place,
    parse_facility,
    parse_lgd_list,
    parse_named_list,
    parse_search_page,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def page():
    return parse_search_page(json.loads((FIXTURES / "search_page.json").read_text("utf-8")))


@pytest.fixture(scope="module")
def results(page):
    return {i: parse_facility(raw) for i, raw in enumerate(page.records)}


class TestSearchPage:
    def test_reads_records_and_paging(self, page):
        assert len(page.records) == 7
        assert (page.total_results, page.total_pages, page.page_number) == (7, 1, 0)

    def test_accepts_the_challenge_api_shape_too(self):
        page = parse_search_page({"facilities": [{}], "totalFacilities": 37, "numberOfPages": 4})
        assert (len(page.records), page.total_results, page.total_pages) == (1, 37, 4)

    def test_accepts_a_bare_list(self):
        assert len(parse_search_page([{}, {}]).records) == 2

    def test_a_search_with_no_results_may_leave_the_list_out(self):
        page = parse_search_page({"totalElements": 0, "message": "No data found"})
        assert (page.records, page.total_results) == ([], 0)

    @pytest.mark.parametrize("body", [{"message": "Invalid captcha"}, "oops", None])
    def test_anything_else_is_a_shape_error(self, body):
        with pytest.raises(PageShapeError):
            parse_search_page(body)


class TestCleanRecord:
    def test_every_field_is_read(self, results):
        result = results[0]
        assert result.reasons == () and result.warnings == ()
        record = result.record
        assert record.facility_id == "IN0399000001"
        assert record.name == "Sample Civil Hospital"
        assert record.status == "Approved"
        assert record.ownership_code == "G"
        assert record.facility_type == "Hospital"
        assert record.systems_of_medicine == ("Modern Medicine(Allopathy)",)
        assert record.state == Place(3, "Punjab")
        assert record.district == Place(27, "Amritsar")
        assert record.sub_district == Place(99901, "Sample Tehsil")
        assert (record.village_name, record.village_lgd_code) == ("Sample Town", 800001)
        assert record.address == "Sample Road, Near Bus Stand"
        assert record.pincode == "143001"
        assert (record.latitude, record.longitude) == (Decimal("31.634000"), Decimal("74.872300"))
        assert record.abdm_software is True
        assert record.type_of_service == "In Patient"
        assert record.phone == "+919876543210"
        assert record.website == "https://www.example.org"
        assert record.specialities == ("Cardiology", "General Medicine")

    def test_icu_beds_add_up_ventilated_and_non_ventilated(self, results):
        assert results[0].record.infrastructure == Infrastructure(
            has_icu_beds=True, total_beds=120, icu_beds=10, ventilators=8
        )


class TestMessyButValidRecord:
    def test_is_cleaned_not_rejected(self, results):
        result = results[1]
        assert result.reasons == ()
        record = result.record
        assert record.facility_id == "IN0399000002"
        assert record.name == "SAMPLE PHC"
        assert record.status == "Submitted"
        assert record.ownership_code == "P"  # sent as the label "Private"
        assert record.pincode == "143001"
        assert record.address == "12, Sample Lane, Ward 4"
        assert record.phone == "+911832345678"

    def test_swapped_coordinates_are_fixed_and_flagged(self, results):
        record = results[1].record
        assert (record.latitude, record.longitude) == (Decimal("31.634000"), Decimal("74.872300"))
        assert "coordinates_swapped" in results[1].warnings

    def test_lists_are_deduplicated_case_insensitively(self, results):
        record = results[1].record
        assert record.systems_of_medicine == ("Ayurveda", "Homoeopathy")
        assert record.specialities == ("Dermatology", "ENT")

    def test_specialities_nhpr_marks_inactive_are_left_out(self, page):
        result = parse_facility({**page.records[0], "specialityDtls": [
            {"specName": "Cardiology  ", "activeYn": "Y"},
            {"specName": "ENT", "activeYn": "N"},
            {"specName": "Cardiology", "activeYn": "N"},
        ]})
        assert result.record.specialities == ("Cardiology",)

    def test_explicit_no_icu(self, results):
        assert results[1].record.infrastructure == Infrastructure(has_icu_beds=False, total_beds=10)


class TestRejectedRecords:
    def test_icu_beds_above_total_beds(self, results):
        assert results[2].record is None
        assert results[2].reasons == ("icu_beds_exceed_total_beds",)
        assert results[2].facility_id == "IN0399000003"

    def test_every_reason_is_reported_not_just_the_first(self, results):
        assert results[3].record is None
        assert set(results[3].reasons) == {"invalid_pincode", "coordinates_outside_india"}

    def test_bad_id_and_missing_name(self, results):
        assert set(results[4].reasons) == {"invalid_facility_id", "missing_name"}
        assert results[4].facility_id == "IN03ABC"  # kept so the quarantine row is findable

    def test_non_object_record(self):
        assert parse_facility("not a record").reasons == ("record_not_an_object",)

    def test_location_is_required(self):
        result = parse_facility({"alternateId": "IN0399000009", "facName": "X", "status": "Approved"})
        assert set(result.reasons) == {"missing_state", "missing_district"}


class TestSoftProblems:
    def test_zeros_and_bad_phone_become_missing(self, results):
        result = results[5]
        record = result.record
        assert record.pincode is None
        assert (record.latitude, record.longitude) == (None, None)
        assert record.phone is None
        assert record.infrastructure.is_empty
        assert result.warnings == ("phone_dropped",)

    def test_id_from_another_state_is_kept_but_flagged(self, results):
        assert results[6].record.state == Place(24, "Gujarat")
        assert results[6].warnings == ("facility_id_state_mismatch",)


def test_appendix_a_field_names_are_understood():
    result = parse_facility({
        "facilityId": "IN3200004821",
        "facilityName": "Example Heart and Multispeciality Hospital",
        "facilityStatus": "Approved",
        "ownershipCode": "P",
        "facilityType": "Hospital",
        "facilityTypeCode": "HOSP",
        "systemOfMedicine": "Modern Medicine",
        "stateName": "Kerala",
        "stateLGDCode": "32",
        "districtName": "Kollam",
        "districtLGDCode": "559",
        "address": "12 Example Road, Chinnakada",
        "pincode": "691001",
        "latitude": "8.8850",
        "longitude": "76.5900",
        "hasIcuBeds": "Yes",
        "abdmSoftware": "Yes",
        "totalBeds": 80,
        "icuBeds": 12,
        "specialities": ["Cardiology", "Orthopaedics"],
    })
    assert result.reasons == ()
    record = result.record
    assert (record.facility_id, record.state, record.district) == (
        "IN3200004821", Place(32, "Kerala"), Place(559, "Kollam")
    )
    assert record.facility_type_code == "HOSP"
    assert record.infrastructure == Infrastructure(has_icu_beds=True, total_beds=80, icu_beds=12)
    assert record.specialities == ("Cardiology", "Orthopaedics")


def test_real_lgd_district_list():
    body = json.loads((FIXTURES / "districts_of_state_3.json").read_text("utf-8"))
    assert parse_lgd_list(body) == [
        Place(27, "Amritsar"), Place(605, "Barnala"), Place(28, "Bathinda"), Place(29, "Faridkot")
    ]


@pytest.mark.parametrize(
    "body",
    [
        [{"id": "1", "value": "Ayurveda"}, {"id": "ALL", "value": "ALL"}],
        {"data": [{"code": "1", "name": "Ayurveda"}]},
        ["Ayurveda", "ayurveda"],
    ],
)
def test_named_master_lists_in_any_common_shape(body):
    entries = parse_named_list(body)
    assert [entry.name for entry in entries] == ["Ayurveda"]


class TestSubDistrictAndVillage:
    BASE = {
        "alternateId": "IN0399000010", "facName": "Sample Clinic", "status": "Approved",
        "state": {"locId": "3", "locName": "Punjab"},
        "district": {"locId": "36", "locName": "Ludhiana"},
    }

    def test_a_bare_code_is_kept_without_a_name(self):
        result = parse_facility({**self.BASE, "subDistrict": "227"})
        assert result.record.sub_district == Place(227, None)
        assert result.warnings == ()

    def test_a_name_without_a_code_is_dropped_with_a_warning(self):
        result = parse_facility({**self.BASE, "subDistrict": "Sample Tehsil"})
        assert result.record.sub_district is None
        assert result.warnings == ("sub_district_dropped",)

    def test_a_village_in_the_same_sub_district_is_kept(self):
        village = {"locId": "33546", "locName": "Sample Village", "locParntId": "227"}
        result = parse_facility({**self.BASE, "subDistrict": "227", "vilCityTown": village})
        assert (result.record.village_name, result.record.village_lgd_code) == ("Sample Village", 33546)

    def test_a_village_from_another_sub_district_is_dropped_with_a_warning(self):
        village = {"locId": "297", "locName": "Sample Village", "locParntId": "6789"}
        result = parse_facility({**self.BASE, "subDistrict": "227", "vilCityTown": village})
        assert (result.record.village_name, result.record.village_lgd_code) == (None, None)
        assert result.warnings == ("village_not_in_sub_district",)


class TestRealSearchPage:
    """A page NHPR actually sent, with personal details removed."""

    @pytest.fixture(scope="class")
    def page(self):
        return parse_search_page(
            json.loads((FIXTURES / "search_page_real.json").read_text("utf-8"))
        )

    def test_paging_is_read(self, page):
        assert len(page.records) == 4
        assert page.total_results == 1611
        assert page.page_number == 5

    def test_every_record_parses(self, page):
        results = [parse_facility(raw) for raw in page.records]
        assert [r.reasons for r in results] == [()] * 4
        for result in results:
            record = result.record
            assert record.facility_id.startswith("IN03")
            assert record.state == Place(3, "Punjab")
            assert record.district == Place(36, "Ludhiana")
            assert record.sub_district is not None and record.sub_district.name is None
            assert record.status == "Approved"
            assert record.latitude is not None and record.longitude is not None
            assert record.specialities
            assert record.phone is None  # removed from the fixture

    def test_villages_joined_from_elsewhere_are_not_believed(self, page):
        warnings = [parse_facility(raw).warnings for raw in page.records]
        assert sum("village_not_in_sub_district" in w for w in warnings) == 2
