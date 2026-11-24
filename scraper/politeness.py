"""Rules that keep the crawl polite: robots.txt, pacing and backoff."""

from __future__ import annotations

import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

MAX_BACKOFF_SECONDS = 300.0


@dataclass(frozen=True)
class RobotsDecision:
    allowed: bool
    crawl_delay: float | None
    note: str


@dataclass(frozen=True)
class HttpResult:
    status: int
    text: str


def check_robots(
    robots_url: str,
    user_agent: str,
    paths: list[str],
    fetch: Callable[[str], HttpResult],
) -> RobotsDecision:
    """Decide whether we may crawl `paths`, following RFC 9309.

    - 200: obey Disallow rules and any Crawl-delay.
    - 4xx: there is no robots.txt, so nothing is disallowed.
    - 5xx: the RFC says to assume everything is disallowed, because the file
      might exist but be unreachable. NHPR, though, answers *every* unknown
      URL with the same 503 page, so we fetch a made-up path too: if that
      gets the identical answer, the 503 is the site's catch-all for paths it
      doesn't serve, i.e. there is no robots.txt to obey.
    """
    robots = fetch(robots_url)

    if robots.status == 200:
        parser = RobotFileParser()
        parser.parse(robots.text.splitlines())
        blocked = [p for p in paths if not parser.can_fetch(user_agent, p)]
        delay = parser.crawl_delay(user_agent)
        if blocked:
            return RobotsDecision(False, None, f"robots.txt disallows {', '.join(blocked)}")
        return RobotsDecision(True, float(delay) if delay else None, "robots.txt allows these pages")

    if 400 <= robots.status < 500:
        return RobotsDecision(True, None, f"no robots.txt (HTTP {robots.status})")

    probe = fetch(urljoin(robots_url, f"/{uuid.uuid4().hex}.txt"))
    if probe.status == robots.status and probe.text.strip() == robots.text.strip():
        return RobotsDecision(
            True,
            None,
            f"no robots.txt: the site answers every unknown path with HTTP {robots.status} "
            f"({robots.text.strip()[:60]!r})",
        )
    return RobotsDecision(
        False, None, f"robots.txt unreachable (HTTP {robots.status}); assuming crawling is disallowed"
    )


def retry_after_seconds(header: str | None, now: datetime | None = None) -> float | None:
    """Parse a Retry-After header, which is either seconds or an HTTP date."""
    if not header:
        return None
    header = header.strip()
    if header.isdigit():
        return min(float(header), MAX_BACKOFF_SECONDS)
    try:
        when = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    seconds = (when - (now or datetime.now(UTC))).total_seconds()
    return min(max(seconds, 0.0), MAX_BACKOFF_SECONDS)


def backoff_seconds(attempt: int, base: float = 10.0, rng: random.Random | None = None) -> float:
    """Exponential backoff with jitter: about 10s, 20s, 40s ... capped at 5 minutes."""
    rng = rng or random.Random()
    delay = base * (2**attempt)
    return min(delay + rng.uniform(0, delay / 2), MAX_BACKOFF_SECONDS)


class Pacer:
    """Keeps a minimum gap, plus some jitter, between requests we trigger."""

    def __init__(
        self,
        min_delay: float,
        jitter: float = 1.5,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ):
        self.min_delay = min_delay
        self.jitter = jitter
        self._clock = clock
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._last: float | None = None

    def wait(self) -> float:
        """Sleep until we're allowed to send the next request. Returns the pause."""
        pause = 0.0
        if self._last is not None:
            gap = self.min_delay + self._rng.uniform(0, self.jitter)
            pause = max(0.0, gap - (self._clock() - self._last))
            if pause:
                self._sleep(pause)
        self._last = self._clock()
        return pause

    def mark(self) -> None:
        """A request was made outside wait() (the operator pressed Search)."""
        self._last = self._clock()

    def slow_down(self, factor: float = 1.5, ceiling: float = 60.0) -> None:
        """After the server pushes back, stay slower for the rest of the run."""
        self.min_delay = min(self.min_delay * factor, ceiling)
