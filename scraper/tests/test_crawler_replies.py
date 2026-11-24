import json

import pytest

from scraper.crawler import classify_search_reply

RESULTS = json.dumps({"content": [{"facName": "Sample Clinic"}], "totalElements": 1})
NO_RESULTS = json.dumps({"content": [], "totalElements": 0})


@pytest.mark.parametrize(
    ("status", "text", "verdict"),
    [
        (200, RESULTS, "results"),
        (200, NO_RESULTS, "results"),
        # A mistyped or expired CAPTCHA, in the shapes NHPR might plausibly use.
        (400, '{"message": "Invalid captcha"}', "captcha"),
        (401, '{"error": "Unauthorized"}', "captcha"),
        (400, "", "captcha"),
        (200, '{"message": "Captcha does not match"}', "captcha"),
        (403, '{"message": "Invalid Captcha"}', "captcha"),
        # A real refusal stops the crawl; overload means wait and retry.
        (403, "<html>Access denied</html>", "blocked"),
        (429, "", "slow_down"),
        (503, "Service Unavailable", "slow_down"),
        # Anything else is this search's problem, not the operator's.
        (200, "<html>maintenance</html>", "failed"),
        (404, "Not Found", "failed"),
    ],
)
def test_classify_search_reply(status, text, verdict):
    assert classify_search_reply(status, text) == verdict
