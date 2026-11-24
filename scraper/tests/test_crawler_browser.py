"""The crawler in a real (headless) browser, against a stand-in for NHPR's page.

Nothing here touches the network: every request is answered by the test. The
page presses Search by itself where an operator would type the CAPTCHA.
Skipped when Playwright's Chromium isn't installed.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import Error as PlaywrightError

from scraper import crawler
from scraper.config import CrawlSettings
from scraper.crawler import NhprBrowser, OperatorAway, RetryTask, TaskFailed
from scraper.report import RunReport
from scraper.storage import CrawlTask

TASK = CrawlTask("Punjab", "Amritsar")
TOTAL_ON_SITE = 1086

PAGE = """
<button role="tab">Health Facility</button>
<input role="combobox"><input role="combobox"><div id="options"></div>
<input id="captcha"><div id="results"></div>
<script>
  const options = __OPTIONS__;
  for (const box of document.querySelectorAll("[role=combobox]")) {
    box.oninput = () => {
      const option = document.createElement("div");
      option.setAttribute("role", "option");
      option.textContent = box.value;
      option.onclick = () => { option.remove(); };
      document.querySelector("#options").replaceChildren(option);
    };
  }
  let pageNo = 0;
  async function load() {
    const url = "https://apinhpr.abdm.gov.in/v4/hfr/facility/search/searchFacility";
    const reply = await fetch(`${url}?pageNo=${pageNo++}&pageSize=10`, {method: "POST", body: "{}"});
    await reply.json();
    if (!options.offersMore) return;
    // The real page draws its button a moment after the response arrives.
    setTimeout(() => {
      const button = document.createElement("button");
      button.textContent = "Load More";
      button.onclick = load;
      document.querySelector("#results").replaceChildren(button);
      if (options.operatorPressesPage === pageNo) button.click();
    }, options.buttonDelay);
  }
  if (options.operatorPresent) {
    document.querySelector("#captcha").addEventListener("focus", () => setTimeout(load, 200), {once: true});
  }
</script>
"""


class RecordingStore:
    def __init__(self):
        self.pages: list[str] = []

    def save_response(self, *, kind, source_key, **_):
        if kind == "search_page":
            self.pages.append(source_key.rsplit("=", 1)[1])
        return len(self.pages)


@pytest.fixture
def crawl(monkeypatch):
    """Run one search against the fake page; returns (outcome, page numbers saved)."""
    monkeypatch.setattr(crawler, "LOAD_MORE_TIMEOUT_SECONDS", 4.0)
    monkeypatch.setattr(crawler, "RESPONSE_TIMEOUT_SECONDS", 2.0)

    def run(store: RecordingStore, *, fail_page=None, empty_page=None, captcha_timeout=20.0, **options):
        options = {"offersMore": True, "buttonDelay": 300, "operatorPresent": True, **options}

        def answer(route):
            request = route.request
            if "searchFacility" not in request.url:
                route.fulfill(content_type="text/html",
                              body=PAGE.replace("__OPTIONS__", json.dumps(options)))
                return
            number = int(parse_qs(urlsplit(request.url).query)["pageNo"][0])
            if number == fail_page:
                route.abort()
                return
            records = [] if number == empty_page else [{"facName": f"Sample {number}"}] * 10
            route.fulfill(json={"content": records, "totalElements": TOTAL_ON_SITE},
                          headers={"Access-Control-Allow-Origin": "*"})

        settings = CrawlSettings(contact="test@example.org", captcha_timeout=captcha_timeout)
        browser = NhprBrowser(settings, store, RunReport(command="test"), run_id=1, min_delay=0.1,
                              headless=True)
        try:
            browser.__enter__()
        except PlaywrightError as exc:
            pytest.skip(f"Playwright's Chromium isn't available: {exc.message.splitlines()[0]}")
        try:
            browser.page.route("**/*", answer)
            return browser.crawl(TASK)
        finally:
            browser.__exit__(None, None, None)

    return run


def test_collects_every_page_the_site_shows(crawl):
    store = RecordingStore()
    outcome = crawl(store)
    assert store.pages == ["0", "1", "2", "3", "4"]
    assert (outcome.records, outcome.total_results, outcome.hit_display_cap) == (50, TOTAL_ON_SITE, True)


def test_waits_for_a_load_more_button_that_is_drawn_late(crawl):
    store = RecordingStore()
    assert crawl(store, buttonDelay=2500).records == 50


def test_a_load_more_the_operator_presses_is_kept_too(crawl):
    store = RecordingStore()
    assert crawl(store, operatorPressesPage=2).records == 50
    assert store.pages == ["0", "1", "2", "3", "4"]


def test_a_missing_load_more_button_is_a_retry_not_a_short_result(crawl):
    with pytest.raises(RetryTask, match="after 10 of 50"):
        crawl(RecordingStore(), offersMore=False)


def test_a_failed_load_more_is_a_retry(crawl):
    with pytest.raises(RetryTask, match="no response"):
        crawl(RecordingStore(), fail_page=2)


def test_an_empty_page_before_the_end_is_a_failure(crawl):
    with pytest.raises(TaskFailed, match="after 20 of 50"):
        crawl(RecordingStore(), empty_page=2)


def test_the_crawl_stops_when_nobody_types_the_captcha(crawl):
    with pytest.raises(OperatorAway, match="Amritsar, Punjab"):
        crawl(RecordingStore(), operatorPresent=False, captcha_timeout=1.0)
