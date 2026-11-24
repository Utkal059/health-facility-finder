"""The per-run summary the brief asks for, printed and stored with the run."""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

# Reasons that mean we could not read the record at all, as opposed to a
# readable record with bad values. A burst of these points at a format change.
STRUCTURAL_REASONS = frozenset({
    "missing_facility_id", "missing_name", "missing_state", "missing_district",
    "record_not_an_object",
})


@dataclass
class RunReport:
    command: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _clock_start: float = field(default_factory=time.monotonic, repr=False)

    robots: str = "not checked"
    search_pages_fetched: int = 0
    master_lists_fetched: int = 0
    retries: int = 0
    http_errors: Counter = field(default_factory=Counter)

    tasks_done: int = 0
    tasks_failed: int = 0
    tasks_hit_display_cap: int = 0

    records_seen: int = 0
    facilities_inserted: int = 0
    facilities_updated: int = 0
    duplicates_merged: int = 0
    records_quarantined: int = 0
    records_unreadable: int = 0
    pages_unrecognised: int = 0
    rejected: Counter = field(default_factory=Counter)
    warnings: Counter = field(default_factory=Counter)

    stopped_because: str | None = None

    @property
    def duration_seconds(self) -> float:
        return round(time.monotonic() - self._clock_start, 1)

    @property
    def facilities_saved(self) -> int:
        return self.facilities_inserted + self.facilities_updated

    def as_dict(self) -> dict:
        return {
            "command": self.command,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "duration_seconds": self.duration_seconds,
            "robots": self.robots,
            "search_pages_fetched": self.search_pages_fetched,
            "master_lists_fetched": self.master_lists_fetched,
            "retries": self.retries,
            "http_errors": dict(self.http_errors),
            "tasks_done": self.tasks_done,
            "tasks_failed": self.tasks_failed,
            "tasks_hit_display_cap": self.tasks_hit_display_cap,
            "records_seen": self.records_seen,
            "facilities_saved": self.facilities_saved,
            "facilities_inserted": self.facilities_inserted,
            "facilities_updated": self.facilities_updated,
            "duplicates_merged": self.duplicates_merged,
            "records_quarantined": self.records_quarantined,
            "pages_unrecognised": self.pages_unrecognised,
            "rejected_by_reason": dict(self.rejected.most_common()),
            "warnings_by_reason": dict(self.warnings.most_common()),
            "stopped_because": self.stopped_because,
        }

    def render(self) -> str:
        rows = [
            ("Duration", f"{self.duration_seconds}s"),
            ("robots.txt", self.robots),
            ("Search pages fetched", self.search_pages_fetched),
            ("Master lists fetched", self.master_lists_fetched),
            ("Retries", self.retries),
            ("HTTP errors", _counter_text(self.http_errors)),
            ("Tasks done / failed", f"{self.tasks_done} / {self.tasks_failed}"),
            ("Searches capped at 50", self.tasks_hit_display_cap),
            ("Records seen", self.records_seen),
            ("Facilities saved", f"{self.facilities_saved} "
             f"({self.facilities_inserted} new, {self.facilities_updated} updated)"),
            ("Duplicates merged", self.duplicates_merged),
            ("Records quarantined", self.records_quarantined),
        ]
        if self.pages_unrecognised:
            rows.append(("Pages not understood", self.pages_unrecognised))
        width = max(len(label) for label, _ in rows)
        lines = [f"Run report ({self.command})", "-" * 44]
        lines += [f"{label:<{width}}  {value}" for label, value in rows]
        for title, counter in (("Rejected by reason", self.rejected),
                               ("Warnings (record kept)", self.warnings)):
            if counter:
                lines.append(f"{title}:")
                lines += [f"  {reason:<34} {count}" for reason, count in counter.most_common()]
        if self.stopped_because:
            lines.append(f"Stopped early: {self.stopped_because}")
        return "\n".join(lines)


def _counter_text(counter: Counter) -> str:
    return ", ".join(f"{key}: {count}" for key, count in sorted(counter.items())) or "none"
