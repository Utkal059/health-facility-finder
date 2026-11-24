"""Drive NHPR's public facility search in a real browser.

NHPR asks for an image CAPTCHA before every new search. The crawler never
reads or solves it. It picks the state and district, then waits while the
person running the crawl types the CAPTCHA and presses Search. After that it
behaves like a patient visitor: it presses "Load more" with pauses in
between, stops where the site stops offering more, and keeps a copy of every
JSON response the page receives. It never calls NHPR's API itself.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Response, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from scraper.config import CrawlSettings
from scraper.parser import PageShapeError, SearchPage, parse_search_page
from scraper.politeness import Pacer, backoff_seconds, retry_after_seconds
from scraper.report import RunReport
from scraper.sources import (
    OWNERSHIP_LABELS,
    RESULTS_DISPLAY_CAP,
    SEARCH_PAGE_URL,
    classify_master,
    is_search_response,
    page_number_from_url,
)
from scraper.storage import CrawlTask, Store


class Blocked(Exception):
    """NHPR refused us outright. Stop the whole crawl and write it up."""


class LayoutChanged(Exception):
    """The search form isn't shaped the way the crawler expects any more."""


class TaskFailed(Exception):
    """This one search couldn't be completed. Record it and move on."""


class RetryTask(Exception):
    """A "Load more" failed. NHPR's page moves on to the next page number
    even when a request fails, so the only clean retry is a fresh search."""


@dataclass
class TaskOutcome:
    response_ids: list[int] = field(default_factory=list)
    records: int = 0
    total_results: int | None = None

    @property
    def pages(self) -> int:
        return len(self.response_ids)

    @property
    def hit_display_cap(self) -> bool:
        return self.total_results is not None and self.total_results > RESULTS_DISPLAY_CAP


def _is_search(response: Response) -> bool:
    return is_search_response(response.url, response.request.method)


class NhprBrowser:
    def __init__(
        self, settings: CrawlSettings, store: Store, report: RunReport, run_id: int,
        min_delay: float,
    ):
        self.settings = settings
        self.store = store
        self.report = report
        self.run_id = run_id
        self.pacer = Pacer(min_delay)
        self.current_response_ids: list[int] = []
        self._master_responses: list[Response] = []

    def __enter__(self) -> NhprBrowser:
        self._playwright = sync_playwright().start()
        # Headed on purpose: a person has to see and type the CAPTCHA.
        self._browser = self._playwright.chromium.launch(headless=False)
        probe = self._browser.new_page()
        user_agent = f"{probe.evaluate('navigator.userAgent')} {self.settings.bot_token}"
        probe.close()
        self._context = self._browser.new_context(
            user_agent=user_agent, locale="en-IN", viewport={"width": 1280, "height": 900}
        )
        self.page = self._context.new_page()
        self.page.on("response", self._remember_master_list)
        return self

    def __exit__(self, *exc_info: object) -> None:
        for close in (self._context.close, self._browser.close, self._playwright.stop):
            with contextlib.suppress(PlaywrightError):  # the operator may have closed the window
                close()

    # -- one search ---------------------------------------------------------

    def crawl(self, task: CrawlTask) -> TaskOutcome:
        self.current_response_ids = []
        outcome = TaskOutcome()

        self.pacer.wait()
        self.page.goto(SEARCH_PAGE_URL, wait_until="domcontentloaded", timeout=60_000)
        self._fill_search_form(task)
        self._save_master_lists()

        response, body, first = self._wait_for_operator_search(task)
        self._save_page(task, response, body, first, outcome, page_index=0)
        self._save_master_lists()

        target = RESULTS_DISPLAY_CAP
        if outcome.total_results is not None:
            target = min(outcome.total_results, RESULTS_DISPLAY_CAP)

        page_index = 0
        while outcome.records < target:
            self.pacer.wait()
            button = self._load_more_button()
            if button is None:
                break  # the site isn't offering more, so neither do we
            page_index += 1
            response = self._click_for_results(button)
            body = self._json(response)
            try:
                page = parse_search_page(body)
            except PageShapeError as exc:
                raise TaskFailed(f"unexpected 'Load more' response: {exc}") from exc
            self._save_page(task, response, body, page, outcome, page_index)
            if not page.records:
                break
        return outcome

    def _fill_search_form(self, task: CrawlTask) -> None:
        page = self.page
        facility_tab = page.get_by_role("tab", name="Health Facility")
        if facility_tab.count():
            facility_tab.first.click()
        boxes = page.locator("input[role=combobox]")
        try:
            boxes.first.wait_for(timeout=30_000)
        except PlaywrightTimeout as exc:
            raise LayoutChanged("the search form never appeared") from exc
        if boxes.count() < 2 or page.locator("#captcha").count() == 0:
            raise LayoutChanged("couldn't find the State/District dropdowns and CAPTCHA box")

        self._choose(boxes.nth(0), task.state_name)
        self._choose(boxes.nth(1), task.district_name)
        if task.ownership:
            page.get_by_text("All Filter", exact=True).click()
            page.get_by_label(OWNERSHIP_LABELS[task.ownership], exact=True).check()

    def _choose(self, box: Locator, label: str) -> None:
        """Pick `label` in one of the site's type-ahead dropdowns."""
        box.click()
        box.fill(label)
        try:
            self.page.get_by_role("option", name=label, exact=True).first.click(timeout=20_000)
        except PlaywrightTimeout as exc:
            raise TaskFailed(f"{label!r} isn't in NHPR's dropdown; check crawl_plan.toml") from exc
        if box.input_value().strip().casefold() != label.casefold():
            raise TaskFailed(f"the dropdown didn't keep {label!r}")

    def _wait_for_operator_search(self, task: CrawlTask) -> tuple[Response, Any, SearchPage]:
        captcha = self.page.locator("#captcha")
        for attempt in range(self.settings.max_captcha_attempts):
            self.page.bring_to_front()
            captcha.focus()
            print(f"\n>>> {task.label}: type the CAPTCHA in the browser window, then press Search.")
            try:
                response = self.page.wait_for_event(
                    "response", predicate=_is_search,
                    timeout=self.settings.captcha_timeout * 1000,
                )
            except PlaywrightTimeout as exc:
                raise TaskFailed("nobody entered the CAPTCHA in time") from exc

            text = self._text(response)
            status = response.status
            verdict = classify_search_reply(status, text)
            if verdict == "results":
                body = json.loads(text)
                return response, body, parse_search_page(body)
            if verdict == "captcha":
                print(f"    NHPR didn't accept that search (HTTP {status}), usually a mistyped or "
                      "expired CAPTCHA. Refresh it if needed and try again.")
                continue
            if verdict == "blocked":
                raise Blocked(f"NHPR answered the search with HTTP 403: {text[:200]}")
            if verdict == "slow_down":
                self._back_off(response, attempt)
                print("    NHPR asked us to slow down; please search again once it lets you.")
                continue
            raise TaskFailed(f"search returned HTTP {status} without a list of facilities: {text[:200]}")
        raise TaskFailed("too many attempts at the CAPTCHA")

    def _click_for_results(self, button: Locator) -> Response:
        try:
            with self.page.expect_response(_is_search, timeout=60_000) as info:
                button.click()
        except PlaywrightTimeout as exc:
            raise RetryTask("'Load more' got no response within a minute") from exc
        response = info.value
        if response.status == 200:
            return response
        if response.status == 403:
            raise Blocked(f"NHPR answered 'Load more' with HTTP 403: {self._text(response)[:200]}")
        if response.status == 429 or response.status >= 500:
            self._back_off(response, attempt=0)
            raise RetryTask(f"HTTP {response.status} on 'Load more'")
        raise TaskFailed(f"'Load more' failed with HTTP {response.status}")

    def _load_more_button(self) -> Locator | None:
        # NHPR labels it "Load More". Prefer a real button; fall back to any
        # clickable element with that text in case it's rendered as a link or span.
        label = re.compile(r"load\s*more", re.I)
        for candidates in (self.page.get_by_role("button", name=label), self.page.get_by_text(label)):
            if candidates.count() and candidates.first.is_visible() and candidates.first.is_enabled():
                return candidates.first
        return None

    # -- saving what the page received ---------------------------------------

    def _save_page(
        self, task: CrawlTask, response: Response, body: Any, page: SearchPage,
        outcome: TaskOutcome, page_index: int,
    ) -> None:
        page_no = page_number_from_url(response.url)
        response_id = self.store.save_response(
            kind="search_page",
            source_key=f"{task.key}|page={page_no if page_no is not None else page_index}",
            url=response.url,
            method=response.request.method,
            request_body=_request_body(response),
            http_status=response.status,
            body=body,
            fetched_at=datetime.now(UTC),
            run_id=self.run_id,
        )
        self.current_response_ids.append(response_id)
        outcome.response_ids.append(response_id)
        outcome.records += len(page.records)
        if page.total_results is not None:
            outcome.total_results = page.total_results
        self.report.search_pages_fetched += 1

    def _remember_master_list(self, response: Response) -> None:
        # Runs inside Playwright's event dispatch, so only note it here; the
        # body is read later in _save_master_lists.
        if classify_master(response.url):
            self._master_responses.append(response)

    def _save_master_lists(self) -> None:
        pending, self._master_responses = self._master_responses, []
        for response in pending:
            kind, key = classify_master(response.url)
            if response.status != 200:
                self.report.http_errors[response.status] += 1
                continue
            try:
                body = response.json()
            except (PlaywrightError, json.JSONDecodeError):
                continue
            self.store.save_response(
                kind=kind, source_key=key, url=response.url, method=response.request.method,
                request_body=None, http_status=200, body=body,
                fetched_at=datetime.now(UTC), run_id=self.run_id,
            )
            self.report.master_lists_fetched += 1

    # -- helpers ------------------------------------------------------------

    def _back_off(self, response: Response, attempt: int) -> None:
        self.report.http_errors[response.status] += 1
        self.report.retries += 1
        delay = retry_after_seconds(response.headers.get("retry-after")) or backoff_seconds(attempt)
        self.pacer.slow_down()
        print(f"    HTTP {response.status}: waiting {delay:.0f}s before trying again.")
        time.sleep(delay)

    def _text(self, response: Response) -> str:
        try:
            return response.text()
        except PlaywrightError:
            return ""

    def _json(self, response: Response) -> Any:
        try:
            return json.loads(self._text(response))
        except json.JSONDecodeError as exc:
            raise TaskFailed("'Load more' returned something that isn't JSON") from exc


SearchVerdict = Literal["results", "captcha", "blocked", "slow_down", "failed"]


def classify_search_reply(status: int, text: str) -> SearchVerdict:
    """Decide what to do with NHPR's answer to a search the operator submitted.

    NHPR doesn't document its error replies. A 400 or 401 on a search is read
    as a rejected CAPTCHA, by far the likeliest cause, so one typo gives the
    operator another go instead of failing the whole district. A 403 that
    talks about the CAPTCHA is a typo too, not a block.
    """
    if status == 200 and _looks_like_results(text):
        return "results"
    if status in (400, 401) or "captcha" in text.lower():
        return "captcha"
    if status == 403:
        return "blocked"
    if status == 429 or status >= 500:
        return "slow_down"
    return "failed"


def _looks_like_results(text: str) -> bool:
    try:
        parse_search_page(json.loads(text))
        return True
    except (json.JSONDecodeError, PageShapeError):
        return False


def _request_body(response: Response) -> Any:
    """What the page asked for, minus the CAPTCHA answer (useless once spent)."""
    try:
        body = response.request.post_data_json
    except (PlaywrightError, ValueError):
        return None
    if isinstance(body, dict):
        body = {key: value for key, value in body.items() if key != "captchaValue"}
    return body
