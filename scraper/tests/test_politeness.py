import random
from datetime import UTC, datetime

import pytest

from scraper.politeness import (
    MAX_BACKOFF_SECONDS,
    HttpResult,
    Pacer,
    backoff_seconds,
    check_robots,
    retry_after_seconds,
)

UA = "HealthFacilityFinderBot/0.1"
ROBOTS = "https://example.gov.in/robots.txt"
PATH = "https://example.gov.in/nhpr/v4/search/facility"


def fake_fetch(responses: dict[str, HttpResult], default: HttpResult):
    return lambda url: responses.get(url, default)


class TestRobots:
    def test_disallow_is_obeyed(self):
        fetch = fake_fetch({ROBOTS: HttpResult(200, "User-agent: *\nDisallow: /nhpr/")}, None)
        decision = check_robots(ROBOTS, UA, [PATH], fetch)
        assert not decision.allowed

    def test_crawl_delay_is_picked_up(self):
        fetch = fake_fetch({ROBOTS: HttpResult(200, "User-agent: *\nCrawl-delay: 7\nAllow: /")}, None)
        decision = check_robots(ROBOTS, UA, [PATH], fetch)
        assert decision.allowed and decision.crawl_delay == 7.0

    def test_missing_robots_allows_everything(self):
        decision = check_robots(ROBOTS, UA, [PATH], fake_fetch({}, HttpResult(404, "")))
        assert decision.allowed and decision.crawl_delay is None

    def test_catch_all_error_page_counts_as_no_robots(self):
        # NHPR answers every unknown path, robots.txt included, with this page.
        waf_page = HttpResult(503, "Please make a valid request.")
        decision = check_robots(ROBOTS, UA, [PATH], fake_fetch({}, waf_page))
        assert decision.allowed
        assert "every unknown path" in decision.note

    def test_genuinely_unreachable_robots_means_stop(self):
        fetch = fake_fetch({ROBOTS: HttpResult(503, "Service Unavailable")}, HttpResult(404, ""))
        assert not check_robots(ROBOTS, UA, [PATH], fetch).allowed


class TestRetryAfter:
    def test_seconds(self):
        assert retry_after_seconds("30") == 30.0

    def test_http_date(self):
        now = datetime(2026, 11, 24, 12, 0, 0, tzinfo=UTC)
        assert retry_after_seconds("Tue, 24 Nov 2026 12:01:00 GMT", now=now) == 60.0

    def test_is_capped(self):
        assert retry_after_seconds("86400") == MAX_BACKOFF_SECONDS

    @pytest.mark.parametrize("header", [None, "", "soon"])
    def test_unusable_values_are_ignored(self, header):
        assert retry_after_seconds(header) is None


def test_backoff_grows_then_caps():
    rng = random.Random(1)
    delays = [backoff_seconds(attempt, rng=rng) for attempt in range(8)]
    assert delays[0] < delays[1] < delays[2]
    assert max(delays) == MAX_BACKOFF_SECONDS


class TestPacer:
    def make(self):
        now = [100.0]
        slept: list[float] = []

        def sleep(seconds):
            slept.append(seconds)
            now[0] += seconds

        pacer = Pacer(min_delay=4, jitter=0, clock=lambda: now[0], sleep=sleep)
        return pacer, now, slept

    def test_first_request_goes_straight_away(self):
        pacer, _, slept = self.make()
        assert pacer.wait() == 0 and slept == []

    def test_waits_out_the_rest_of_the_gap(self):
        pacer, now, slept = self.make()
        pacer.wait()
        now[0] += 1.5  # the page took 1.5s to render
        pacer.wait()
        assert slept == [2.5]

    def test_a_request_made_outside_wait_restarts_the_gap(self):
        pacer, now, slept = self.make()
        pacer.wait()
        now[0] += 60  # the operator took a minute over the CAPTCHA
        pacer.mark()  # and their search went out just now
        pacer.wait()
        assert slept == [4]

    def test_slow_down_sticks(self):
        pacer, _, _ = self.make()
        pacer.slow_down()
        assert pacer.min_delay == 6
