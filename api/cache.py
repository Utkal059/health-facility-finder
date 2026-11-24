"""A tiny time-based cache for master lists and stats.

That data only changes when the scraper loads a new crawl, so serving it a
few minutes stale is fine, and expiry by time is the whole invalidation
story. The cache lives in each API process; nothing is shared or persisted.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

TTL_SECONDS = 300.0


class TtlCache:
    def __init__(self, ttl: float = TTL_SECONDS, clock: Callable[[], float] = time.monotonic):
        self.ttl = ttl
        self._clock = clock
        self._entries: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get_or_compute(self, key: str, compute: Callable[[], Any]) -> Any:
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry and now - entry[0] < self.ttl:
                return entry[1]
        value = compute()  # computed outside the lock; a rare double compute is harmless
        with self._lock:
            self._entries[key] = (now, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
