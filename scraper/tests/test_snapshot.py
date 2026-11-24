from scraper.snapshot import is_contact_key, redact_contacts


def test_contact_fields_are_recognised_by_name():
    for key in ("mobileNo", "landlineNo", "facContactPerMobNo", "facContactPerName",
                "cmoMoIcuControlMobile", "facEmail", "email", "phone"):
        assert is_contact_key(key), key
    for key in ("facName", "pincode", "address1", "totalBeds", "abdmSoftware"):
        assert not is_contact_key(key), key


def test_redaction_reaches_nested_records_and_leaves_the_rest_alone():
    body = {
        "content": [{
            "facName": "Sample Clinic",
            "mobileNo": "9876543210",
            "facEmail": "someone@example.org",
            "landlineNo": "",
            "medicalInfraRequestDTO": [{"totalBeds": "10", "cmoMoIcuControlMobile": "9123456789"}],
        }],
        "totalElements": 1,
    }
    redacted = redact_contacts(body)
    record = redacted["content"][0]
    assert record["facName"] == "Sample Clinic"
    assert record["mobileNo"] is None and record["facEmail"] is None
    assert record["landlineNo"] == ""  # nothing there to hide
    assert record["medicalInfraRequestDTO"][0] == {"totalBeds": "10", "cmoMoIcuControlMobile": None}
    assert body["content"][0]["mobileNo"] == "9876543210"  # the input is not modified
