from scraper.snapshot import is_personal_key, redact_personal


def test_personal_fields_are_recognised_by_name():
    for key in ("mobileNo", "landlineNo", "facContactPerMobNo", "facContactPerName",
                "cmoMoIcuControlMobile", "facEmail", "email", "phone", "healthId", "crtUsr",
                "lstUpdUsr", "declaredBy", "identificationNo", "facPAN"):
        assert is_personal_key(key), key
    for key in ("facName", "pincode", "address1", "totalBeds", "abdmSoftware", "alternateId",
                "healthFacId", "facOwnership"):
        assert not is_personal_key(key), key


def test_redaction_reaches_nested_records_and_leaves_the_rest_alone():
    body = {
        "content": [{
            "facName": "Sample Clinic",
            "mobileNo": "9876543210",
            "facEmail": "someone@example.org",
            "healthId": "71-0000-0000-0000",
            "landlineNo": "",
            "medicalInfraRequestDTO": [{"totalBeds": "10", "cmoMoIcuControlMobile": "9123456789"}],
        }],
        "totalElements": 1,
    }
    redacted = redact_personal(body)
    record = redacted["content"][0]
    assert record["facName"] == "Sample Clinic"
    assert record["mobileNo"] is None and record["facEmail"] is None and record["healthId"] is None
    assert record["landlineNo"] == ""  # nothing there to hide
    assert record["medicalInfraRequestDTO"][0] == {"totalBeds": "10", "cmoMoIcuControlMobile": None}
    assert body["content"][0]["mobileNo"] == "9876543210"  # the input is not modified


def test_contact_details_inside_free_text_are_removed_too():
    redacted = redact_personal({
        "address1": "12 Sample Road, call +91 9876543210",
        "address2": "write to someone@example.org",
        "note": "added by 71-0000-0000-0000",
    })
    assert redacted == {
        "address1": "12 Sample Road, call", "address2": "write to", "note": "added by",
    }


def test_numbers_that_only_look_a_little_like_phones_survive():
    body = {"alternateId": "IN0310017184", "geolocation": "31.646308,74.878183",
            "pincode": "143001", "crtDt": "2026-10-07T07:22:13.858+00:00"}
    assert redact_personal(body) == body


def test_coordinates_with_ten_decimals_are_not_mistaken_for_mobile_numbers():
    body = {"geolocation": "30.9123456789,75.857276", "latitude": "30.9123456789",
            "longitude": "75.919876543210"}
    assert redact_personal(body) == body
