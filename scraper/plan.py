"""Read the crawl plan: which states and districts to search, and how."""

from __future__ import annotations

import tomllib
from pathlib import Path

from scraper.sources import OWNERSHIP_LABELS
from scraper.storage import CrawlTask


class PlanError(ValueError):
    pass


def load_plan(path: str | Path) -> list[CrawlTask]:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return tasks_from_plan(data)


def tasks_from_plan(data: dict) -> list[CrawlTask]:
    default_filters = data.get("ownership_filters", ["all"])
    tasks: list[CrawlTask] = []
    for state in data.get("states", []):
        name = state.get("name", "").strip()
        districts = [d.strip() for d in state.get("districts", []) if d.strip()]
        if not name or not districts:
            raise PlanError(f"every [[states]] entry needs a name and districts: {state!r}")
        for district in districts:
            for ownership in state.get("ownership_filters", default_filters):
                if ownership != "all" and ownership not in OWNERSHIP_LABELS:
                    raise PlanError(f"unknown ownership filter {ownership!r}")
                tasks.append(CrawlTask(name, district, None if ownership == "all" else ownership))

    keys = [task.key for task in tasks]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise PlanError(f"plan lists the same search twice: {', '.join(duplicates)}")
    if not tasks:
        raise PlanError("plan has no searches in it")
    return tasks
