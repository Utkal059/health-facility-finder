"""Command line entry point: python -m scraper <command>

  crawl     search NHPR (you type each CAPTCHA) and load the database
  parse     rebuild the tables from stored raw responses, no network
  status    show crawl progress per search
  snapshot  export/load the raw scrape (data/snapshot/)
  fixture   save one stored response as a parser test fixture
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg

from db.env import REPO_ROOT, database_url
from db.migrate import migrate
from scraper.loader import MASTER_KINDS, Loader
from scraper.plan import load_plan
from scraper.report import RunReport
from scraper.storage import CrawlTask, Store

ALL_KINDS = (*MASTER_KINDS, "search_page")
DEFAULT_PLAN = REPO_ROOT / "scraper" / "crawl_plan.toml"
DEFAULT_SNAPSHOT = REPO_ROOT / "data" / "snapshot" / "nhpr_raw_responses.jsonl.gz"
REPORTS_DIR = REPO_ROOT / "reports"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scraper", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    crawl = commands.add_parser("crawl", help="search NHPR and load the database")
    crawl.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    crawl.add_argument("--refresh", action="store_true", help="search again even if already done")
    crawl.add_argument("--limit", type=int, help="stop after this many searches")

    commands.add_parser("parse", help="re-parse every stored raw response (no network)")
    commands.add_parser("status", help="show progress for each planned search")

    snapshot = commands.add_parser("snapshot", help="export or load the raw scrape")
    snapshot.add_argument("action", choices=["export", "load"])
    snapshot.add_argument("path", type=Path, nargs="?", default=DEFAULT_SNAPSHOT)
    snapshot.add_argument("--if-exists", action="store_true",
                          help="(load) do nothing if the file is missing instead of failing")

    fixture = commands.add_parser("fixture", help="save a stored response as a test fixture")
    fixture.add_argument("response_id", type=int)
    fixture.add_argument("path", type=Path)
    fixture.add_argument("--records", type=int, help="keep only the first N records of a search page")

    args = parser.parse_args(argv)
    handler = {
        "crawl": run_crawl, "parse": run_parse, "status": run_status,
        "snapshot": run_snapshot, "fixture": run_fixture,
    }[args.command]
    return handler(args)


def _connect() -> psycopg.Connection:
    url = database_url()
    migrate(url)
    return psycopg.connect(url, autocommit=True)


# -- crawl -------------------------------------------------------------------


def run_crawl(args: argparse.Namespace) -> int:
    # Imported here so the other commands (and the API image) don't need a browser.
    import httpx
    from playwright.sync_api import Error as PlaywrightError

    from scraper.config import load_crawl_settings
    from scraper.crawler import Blocked, LayoutChanged, NhprBrowser, OperatorAway
    from scraper.politeness import HttpResult, check_robots
    from scraper.sources import ROBOTS_URL, SEARCH_PAGE_URL

    settings = load_crawl_settings()
    tasks = load_plan(args.plan)
    report = RunReport(command="crawl")

    def fetch(url: str) -> HttpResult:
        reply = httpx.get(url, headers={"User-Agent": settings.bot_token}, timeout=20)
        return HttpResult(reply.status_code, reply.text)

    robots = check_robots(ROBOTS_URL, settings.bot_token, [SEARCH_PAGE_URL], fetch)
    report.robots = robots.note
    print(f"robots.txt: {robots.note}")
    if not robots.allowed:
        return 2
    min_delay = max(settings.min_delay, robots.crawl_delay or 0)

    with _connect() as conn:
        store, loader = Store(conn), Loader(conn, report)
        store.register_tasks(tasks)
        done = set() if args.refresh else store.done_task_keys()
        todo = [task for task in tasks if task.key not in done][: args.limit]
        print(f"{len(tasks)} searches planned, {len(tasks) - len(todo)} already done, "
              f"{len(todo)} to go. Pausing at least {min_delay:.0f}s between requests.")

        run_id = store.start_run("crawl")
        status = "finished"
        browser: NhprBrowser | None = None
        try:
            with NhprBrowser(settings, store, report, run_id, min_delay) as browser:
                for task in todo:
                    _crawl_with_retries(browser, store, report, task, settings)
                    # Even a search that failed part-way saved some good pages.
                    if browser.current_response_ids:
                        _load_and_check(store, loader, report, browser.current_response_ids)
        except Blocked as exc:
            status, report.stopped_because = "blocked", str(exc)
        except LayoutChanged as exc:
            status, report.stopped_because = "failed", f"NHPR's search page changed: {exc}"
        except OperatorAway as exc:
            status = "interrupted"
            report.stopped_because = f"{exc}; run the same command again to continue"
        except (KeyboardInterrupt, PlaywrightError) as exc:
            status = "interrupted"
            report.stopped_because = "stopped by the operator" if isinstance(
                exc, KeyboardInterrupt) else f"browser closed ({exc.__class__.__name__})"
        except _ShapeDrift as exc:
            status, report.stopped_because = "failed", str(exc)
        finally:
            # Pages saved by an interrupted search are still worth loading.
            if status != "finished" and browser and browser.current_response_ids:
                loader.load(store.responses(ALL_KINDS, browser.current_response_ids))
            _finish(store, run_id, status, report)
    return 0 if status == "finished" else 1


def _crawl_with_retries(
    browser, store: Store, report: RunReport, task: CrawlTask, settings
) -> None:
    from scraper.crawler import RetryTask, TaskFailed

    last_error = None
    for _ in range(settings.max_task_attempts):
        store.begin_task(task)
        try:
            outcome = browser.crawl(task)
        except RetryTask as exc:
            report.retries += 1
            last_error = str(exc)
            print(f"    {exc}. Starting this search again.")
            continue
        except TaskFailed as exc:
            last_error = str(exc)
            break
        store.update_task(
            task, status="done", pages_fetched=outcome.pages, records_seen=outcome.records,
            total_results=outcome.total_results, hit_display_cap=outcome.hit_display_cap,
            last_error=None,
        )
        report.tasks_done += 1
        report.tasks_hit_display_cap += outcome.hit_display_cap
        print(f"    {task.label}: {outcome.records} facilities over {outcome.pages} pages"
              + (f" (NHPR has {outcome.total_results}; the site shows 50)"
                 if outcome.hit_display_cap else ""))
        return

    print(f"    {task.label}: giving up ({last_error})")
    store.update_task(task, status="failed", last_error=last_error)
    report.tasks_failed += 1


class _ShapeDrift(Exception):
    pass


def _load_and_check(store: Store, loader: Loader, report: RunReport, response_ids: list[int]):
    before = (report.records_seen, report.records_unreadable, report.pages_unrecognised)
    loader.load(store.responses(MASTER_KINDS) + store.responses(("search_page",), response_ids))
    seen = report.records_seen - before[0]
    unreadable = report.records_unreadable - before[1]
    odd_pages = report.pages_unrecognised - before[2]
    problem = None
    if odd_pages:
        problem = f"{odd_pages} page(s) of the last search had no list of facilities in them."
    elif seen >= 5 and unreadable / seen > 0.8:
        problem = f"{unreadable} of {seen} records on the last search could not be read."
    if problem:
        raise _ShapeDrift(
            f"{problem} NHPR may have changed its response format. The raw pages are saved, "
            "so fix scraper/parser.py and run `python -m scraper parse`."
        )


def _finish(store: Store, run_id: int, status: str, report: RunReport) -> None:
    store.finish_run(run_id, status, report.as_dict())
    print()
    print(report.render())
    path = REPORTS_DIR / f"run-{run_id:04d}-{report.command}.json"
    try:
        REPORTS_DIR.mkdir(exist_ok=True)
        path.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    except OSError as exc:
        # The report is already in crawl_runs; a read-only disk shouldn't fail the run.
        print(f"\nCouldn't write {path} ({exc}); the report is saved in crawl_runs.")
        return
    print(f"\nReport saved to {path.relative_to(REPO_ROOT)}")


# -- offline commands ----------------------------------------------------------


def run_parse(args: argparse.Namespace) -> int:
    report = RunReport(command="parse")
    with _connect() as conn:
        store = Store(conn)
        run_id = store.start_run("parse")
        Loader(conn, report).rebuild(store.responses(ALL_KINDS))
        _finish(store, run_id, "finished", report)
    return 0


def run_status(args: argparse.Namespace) -> int:
    with _connect() as conn:
        rows = Store(conn).task_overview()
        facilities = conn.execute("SELECT count(*) FROM facilities").fetchone()[0]
        quarantined = conn.execute("SELECT count(*) FROM quarantined_records").fetchone()[0]
    if not rows:
        print("No searches registered yet. Run `python -m scraper crawl` first.")
        return 0
    print(f"{'state':<12} {'district':<20} {'filter':<6} {'status':<11} {'pages':>5} "
          f"{'records':>7} {'on NHPR':>7}")
    for state, district, own, status, pages, records, total, capped, error in rows:
        note = " (capped at 50)" if capped else f"  {error}" if error else ""
        print(f"{state:<12} {district:<20} {own:<6} {status:<11} {pages:>5} {records:>7} "
              f"{total if total is not None else '-':>7}{note}")
    print(f"\n{facilities} facilities loaded, {quarantined} records in quarantine.")
    return 0


def run_snapshot(args: argparse.Namespace) -> int:
    from scraper.snapshot import export_snapshot, import_snapshot

    if args.action == "export":
        with _connect() as conn:
            count = export_snapshot(conn, args.path)
        print(f"Wrote {count} raw responses to {args.path}")
        return 0

    if not args.path.exists():
        if args.if_exists:
            print(f"No snapshot at {args.path}; starting with an empty database.")
            return 0
        raise SystemExit(f"Snapshot not found: {args.path}")

    report = RunReport(command="snapshot-load")
    with _connect() as conn:
        count = import_snapshot(conn, args.path)
        print(f"Loaded {count} raw responses from {args.path}")
        store = Store(conn)
        run_id = store.start_run("snapshot-load")
        Loader(conn, report).rebuild(store.responses(ALL_KINDS))
        _finish(store, run_id, "finished", report)
    return 0


def run_fixture(args: argparse.Namespace) -> int:
    # Personal details have no place in a test fixture either.
    from scraper.snapshot import redact_personal

    with _connect() as conn:
        row = conn.execute("SELECT kind, body FROM raw_responses WHERE id = %s",
                           (args.response_id,)).fetchone()
    if row is None:
        raise SystemExit(f"No raw response with id {args.response_id}")

    args.path.parent.mkdir(parents=True, exist_ok=True)
    body = redact_personal(row[1])
    if args.records and isinstance(body, dict) and isinstance(body.get("content"), list):
        body["content"] = body["content"][: args.records]
    args.path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {row[0]} response {args.response_id} to {args.path}")
    return 0
