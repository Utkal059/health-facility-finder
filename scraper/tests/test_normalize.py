from decimal import Decimal

import pytest

from scraper.normalize import (
    InvalidValue,
    clean_address,
    clean_name,
    normalize_coordinates,
    normalize_facility_id,
    normalize_phone,
    normalize_pincode,
    parse_count,
    parse_yes_no,
)


class TestNames:
    def test_collapses_whitespace_and_stray_punctuation_but_keeps_case(self):
        assert clean_name("  SAMPLE   PHC  ,, ") == "SAMPLE PHC"
        assert clean_name("Dr. Mehta's  Clinic") == "Dr. Mehta's Clinic"

    @pytest.mark.parametrize("blank", [None, "", "   ", "NA", "n/a", "null", "-"])
    def test_placeholders_mean_missing(self, blank):
        assert clean_name(blank) is None

    def test_address_lines_are_joined_without_repeats(self):
        assert clean_address("12, Sample Lane,Ward 4", "12, Sample Lane, Ward 4", None, "") == (
            "12, Sample Lane, Ward 4"
        )
        assert clean_address("Sample Road", "Near Bus Stand") == "Sample Road, Near Bus Stand"


class TestFacilityId:
    def test_trims_and_uppercases(self):
        assert normalize_facility_id(" in0310000334 ") == "IN0310000334"

    @pytest.mark.parametrize("bad", ["IN03ABC", "IN031000033", "US0310000334", "0310000334"])
    def test_rejects_anything_not_in_plus_ten_digits(self, bad):
        with pytest.raises(InvalidValue, match="invalid_facility_id"):
            normalize_facility_id(bad)

    def test_missing_id_has_its_own_reason(self):
        with pytest.raises(InvalidValue, match="missing_facility_id"):
            normalize_facility_id("  ")


class TestPincode:
    @pytest.mark.parametrize("raw", ["143001", "143 001", "143-001", 143001, 143001.0])
    def test_accepts_common_spellings(self, raw):
        assert normalize_pincode(raw) == "143001"

    @pytest.mark.parametrize("raw", [None, "", "000000", "0"])
    def test_blank_or_all_zero_is_missing(self, raw):
        assert normalize_pincode(raw) is None

    @pytest.mark.parametrize("raw", ["14300", "1430011", "043001", "14300A"])
    def test_rejects_invalid(self, raw):
        with pytest.raises(InvalidValue, match="invalid_pincode"):
            normalize_pincode(raw)


class TestPhone:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("+91-98765 43210", "+919876543210"),
            ("098765 43210", "+919876543210"),
            ("9876543210", "+919876543210"),
            ("0183-2345678", "+911832345678"),
            ("bad / 98765 43210", "+919876543210"),
        ],
    )
    def test_normalises_to_e164(self, raw, expected):
        assert normalize_phone(raw) == expected

    @pytest.mark.parametrize("raw", ["12345", "0000000000", "9999999999"])
    def test_rejects_numbers_that_cannot_be_real(self, raw):
        with pytest.raises(InvalidValue, match="invalid_phone"):
            normalize_phone(raw)


class TestCoordinates:
    def test_valid_pair_is_rounded_to_six_places(self):
        lat, lon, swapped = normalize_coordinates("31.63400049", "74.8723")
        assert (lat, lon, swapped) == (Decimal("31.634000"), Decimal("74.872300"), False)

    def test_swapped_pair_is_put_back_and_flagged(self):
        lat, lon, swapped = normalize_coordinates("74.8723", "31.634")
        assert (lat, lon, swapped) == (Decimal("31.634000"), Decimal("74.872300"), True)

    @pytest.mark.parametrize("pair", [(None, None), ("", ""), ("0", "0"), ("0.0", "0.000")])
    def test_missing_or_zero_means_not_filled_in(self, pair):
        assert normalize_coordinates(*pair) == (None, None, False)

    def test_outside_india_is_rejected(self):
        with pytest.raises(InvalidValue, match="coordinates_outside_india"):
            normalize_coordinates("51.5074", "-0.1278")

    def test_half_a_pair_is_rejected(self):
        with pytest.raises(InvalidValue, match="incomplete_coordinates"):
            normalize_coordinates("31.6", None)

    def test_text_is_rejected(self):
        with pytest.raises(InvalidValue, match="invalid_coordinates"):
            normalize_coordinates("north", "74.8")


class TestCounts:
    @pytest.mark.parametrize(("raw", "expected"), [("12", 12), (0, 0), ("1,200", 1200), (None, None)])
    def test_parses_whole_numbers(self, raw, expected):
        assert parse_count(raw, "total_beds") == expected

    def test_negative_is_rejected_with_its_own_reason(self):
        with pytest.raises(InvalidValue, match="negative_total_beds"):
            parse_count("-3", "total_beds")

    @pytest.mark.parametrize("raw", ["1.5", "ten"])
    def test_fractions_and_text_are_rejected(self, raw):
        with pytest.raises(InvalidValue, match="invalid_total_beds"):
            parse_count(raw, "total_beds")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Yes", True), ("yes", True), (True, True), ("No", False), ("N", False), (False, False),
        # NHPR sends abdmSoftware as "1"/"0" (its results page shows "1" as Yes).
        ("1", True), (1, True), ("0", False), (0, False),
        ("", None), ("maybe", None),
    ],
)
def test_yes_no(raw, expected):
    assert parse_yes_no(raw) is expected
