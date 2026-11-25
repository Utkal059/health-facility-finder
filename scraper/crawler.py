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


class OperatorAway(Exception):
    """Nobody is there to type CAPTCHAs, so there is no point opening the
    remaining searches one after another. The next run picks up from here."""


# How long NHPR gets to draw its search form.
FORM_TIMEOUT_SECONDS = 30.0
# How long NHPR gets to draw its "Load More" button after a page arrives.
LOAD_MORE_TIMEOUT_SECONDS = 20.0
# How long NHPR gets to answer a "Load More".
RESPONSE_TIMEOUT_SECONDS = 60.0


@dataclass
class TaskOutcome:
    response_ids: list[int] = field(default_factory=list)
    page_numbers: list[int] = field(default_factory=list)
    records: int = 0
    total_results: int | None = None

    @property
    def pages(self) -> int:
        return len(self.response_ids)

    @property
    def target(self) -> int:
        """How many facilities the site will show for this search."""
        if self.total_results is None:
            return RESULTS_DISPLAY_CAP
        return min(self.total_results, RESULTS_DISPLAY_CAP)

    @property
    def missing_pages(self) -> list[int]:
        return missing_pages(self.page_numbers)

    @property
    def hit_display_cap(self) -> bool:
        return self.total_results is not None and self.total_results > RESULTS_DISPLAY_CAP


def missing_pages(page_numbers: list[int]) -> list[int]:
    """Page numbers skipped between the first page (0) and the last one seen."""
    if not page_numbers:
        return []
    return sorted(set(range(max(page_numbers) + 1)) - set(page_numbers))


def _is_search(response: Response) -> bool:
    return is_search_response(response.url, response.request.method)


class NhprBrowser:
    def __init__(
        self, settings: CrawlSettings, store: Store, report: RunReport, run_id: int,
        min_delay: float, headless: bool = False,
    ):
        self.settings = settings
        self.store = store
        self.report = report
        self.run_id = run_id
        self.headless = headless
        # Pausing inside Playwright, not time.sleep, so responses that arrive
        # during a pause are still noticed.
        self.pacer = Pacer(min_delay, sleep=lambda seconds: self.page.wait_for_timeout(seconds * 1000))
        self.current_response_ids: list[int] = []
        self._master_responses: list[Response] = []
        self._search_responses: list[Response] = []
        self._attempt = 0  # which try at the current search this is, for backoff

    def __enter__(self) -> NhprBrowser:
        self._playwright = sync_playwright().start()
        # Headed unless a test says otherwise: a person has to see and type the CAPTCHA.
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        probe = self._browser.new_page()
        user_agent = f"{probe.evaluate('navigator.userAgent')} {self.settings.bot_token}"
        probe.close()
        self._context = self._browser.new_context(
            user_agent=user_agent, locale="en-IN", viewport={"width": 1280, "height": 900}
        )
        self.page = self._context.new_page()
        self.page.on("response", self._remember_response)
        return self

    def __exit__(self, *exc_info: object) -> None:
        for close in (self._context.close, self._browser.close, self._playwright.stop):
            with contextlib.suppress(PlaywrightError):  # the operator may have closed the window
                close()

    # -- one search ---------------------------------------------------------

    def crawl(self, task: CrawlTask, attempt: int = 0) -> TaskOutcome:
        self._attempt = attempt
        self.current_response_ids = []
        self._search_responses.clear()
        outcome = TaskOutcome()

        page_response = self._open_search_page()
        self._fill_search_form(task, page_response)
        self._save_master_lists()

        response, body, first = self._wait_for_operator_search(task)
        self._save_page(task, response, body, first, outcome)
        self._save_master_lists()

        while outcome.records < outcome.target:
            self.pacer.wait()
            # A "Load more" the operator pressed by hand counts like any other.
            if not self._search_responses:
                self._click_for_results(self._load_more_button(outcome))
            empty = self._save_pending_pages(task, outcome)
            if empty:
                raise TaskFailed(f"NHPR sent an empty page after {outcome.records} of "
                                 f"{outcome.target} facilities")

        if outcome.missing_pages:
            raise RetryTask(f"page(s) {outcome.missing_pages} of the results never arrived")
        return outcome

    def _save_pending_pages(self, task: CrawlTask, outcome: TaskOutcome) -> bool:
        """Store every results page received since last time. True if one was empty."""
        empty = False
        pending, self._search_responses = self._search_responses, []
        for response in pending:
            if response.status != 200:
                continue
            body = self._json(response)
            try:
                page = parse_search_page(body)
            except PageShapeError as exc:
                raise TaskFailed(f"unexpected 'Load more' response: {exc}") from exc
            self._save_page(task, response, body, page, outcome)
            empty = empty or not page.records
        return empty

    def _open_search_page(self) -> Response | None:
        self.pacer.wait()
        try:
            return self.page.goto(SEARCH_PAGE_URL, wait_until="domcontentloaded", timeout=60_000)
        except PlaywrightError as exc:
            if self.page.is_closed():
                raise
            raise RetryTask(f"the search page didn't load: {first_line(exc)}") from exc

    def _fill_search_form(self, task: CrawlTask, page_response: Response | None) -> None:
        page = self.page
        facility_tab = page.get_by_role("tab", name="Health Facility")
        if facility_tab.count():
            facility_tab.first.click()
        boxes = page.locator("input[role=combobox]")
        try:
            boxes.first.wait_for(timeout=FORM_TIMEOUT_SECONDS * 1000)
        except PlaywrightTimeout as exc:
            status = page_response.status if page_response else 200
            if status == 403:
                raise Blocked("NHPR answered the search page with HTTP 403") from exc
            if status == 429 or status >= 500:
                self._back_off(page_response, self._attempt)
                raise RetryTask(f"HTTP {status} on the search page") from exc
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
                raise OperatorAway(f"nobody entered the CAPTCHA for {task.label}") from exc

            self.pacer.mark()
            text = self._text(response)
            status = response.status
            verdict = classify_search_reply(status, text)
            if verdict == "results":
                self._search_responses.clear()  # this one, and any rejected attempts before it
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

    def _click_for_results(self, button: Locator) -> None:
        try:
            with self.page.expect_response(_is_search, timeout=RESPONSE_TIMEOUT_SECONDS * 1000) as info:
                button.click()
        except PlaywrightTimeout as exc:
            raise RetryTask("'Load more' got no response in time") from exc
        response = info.value
        if response.status == 200:
            return
        if response.status == 403:
            raise Blocked(f"NHPR answered 'Load more' with HTTP 403: {self._text(response)[:200]}")
        if response.status == 429 or response.status >= 500:
            self._back_off(response, self._attempt)
            raise RetryTask(f"HTTP {response.status} on 'Load more'")
        raise TaskFailed(f"'Load more' failed with HTTP {response.status}")

    def _load_more_button(self, outcome: TaskOutcome) -> Locator:
        """Wait for "Load More" to be drawn and enabled, then return it.

        The response arrives before the page has rendered it, so looking once
        and giving up would quietly keep only the first 10 results.
        """
        deadline = time.monotonic() + LOAD_MORE_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            button = self._find_load_more()
            if button is not None:
                return button
            self.page.wait_for_timeout(500)
        raise RetryTask(f"'Load more' never appeared after {outcome.records} of {outcome.target} "
                        "facilities")

    def _find_load_more(self) -> Locator | None:
        # Prefer a real button; fall back to any clickable element with that
        # text in case it's rendered as a link or span.
        label = re.compile(r"load\s*more", re.I)
        for candidates in (self.page.get_by_role("button", name=label), self.page.get_by_text(label)):
            if candidates.count() and candidates.first.is_visible() and candidates.first.is_enabled():
                return candidates.first
        return None

    # -- saving what the page received ---------------------------------------

    def _save_page(
        self, task: CrawlTask, response: Response, body: Any, page: SearchPage,
        outcome: TaskOutcome,
    ) -> None:
        page_no = page_number_from_url(response.url)
        if page_no is None:
            page_no = outcome.pages
        if page_no in outcome.page_numbers:
            return  # the same page delivered twice
        response_id = self.store.save_response(
            kind="search_page",
            source_key=f"{task.key}|page={page_no}",
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
        outcome.page_numbers.append(page_no)
        outcome.records += len(page.records)
        if page.total_results is not None:
            outcome.total_results = page.total_results
        self.report.search_pages_fetched += 1

    def _remember_response(self, response: Response) -> None:
        # Runs inside Playwright's event dispatch, so only note it here; the
        # bodies are read later.
        if classify_master(response.url):
            self._master_responses.append(response)
        elif _is_search(response):
            self._search_responses.append(response)

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


def first_line(exc: Exception) -> str:
    """Playwright's messages go on for pages; the first line says what happened."""
    return str(exc).partition("\n")[0]


def _request_body(response: Response) -> Any:
    """What the page asked for, minus the CAPTCHA answer (useless once spent)."""
    try:
        body = response.request.post_data_json
    except (PlaywrightError, ValueError):
        return None
    if isinstance(body, dict):
        body = {key: value for key, value in body.items() if key != "captchaValue"}
    return body
