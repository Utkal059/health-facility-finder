import json

import pytest

from scraper.crawler import TaskOutcome, classify_search_reply, missing_pages

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


@pytest.mark.parametrize(
    ("seen", "missing"),
    [([], []), ([0], []), ([0, 1, 2], []), ([2, 0, 1], []), ([0, 1, 2, 4, 5], [3]), ([1], [0])],
)
def test_a_skipped_results_page_is_noticed(seen, missing):
    assert missing_pages(seen) == missing


@pytest.mark.parametrize(("total", "target"), [(7, 7), (50, 50), (1086, 50), (None, 50)])
def test_a_search_aims_for_everything_the_site_shows(total, target):
    assert TaskOutcome(total_results=total).target == target
