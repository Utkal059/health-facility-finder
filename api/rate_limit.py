"""Per-IP rate limiting for the search endpoint.

A sliding window kept in memory. That is right for a single small instance;
running several instances would need the counts in a shared store (Redis),
which is noted in the README as a trade-off.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import Request

from api.errors import ApiError


class SlidingWindowLimiter:
    def __init__(self, limit: int, window: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window = window
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._calls = 0

    def hit(self, key: str) -> tuple[bool, int, float]:
        """Record a request. Returns (allowed, remaining, seconds until a slot frees up)."""
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False, 0, hits[0] + self.window - now
            hits.append(now)
            self._calls += 1
            if self._calls % 1000 == 0:
                self._forget_idle(now)
            return True, self.limit - len(hits), 0.0

    def _forget_idle(self, now: float) -> None:
        idle = [key for key, hits in self._hits.items() if not hits or hits[-1] <= now - self.window]
        for key in idle:
            del self._hits[key]


def client_ip(request: Request, trust_proxy_headers: bool) -> str:
    if trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def search_rate_limit(request: Request) -> None:
    """FastAPI dependency: refuse the request once the caller is over the limit."""
    limiter: SlidingWindowLimiter = request.app.state.search_limiter
    ip = client_ip(request, request.app.state.settings.trust_proxy_headers)
    allowed, remaining, retry_after = limiter.hit(ip)
    request.state.rate_limit_remaining = remaining
    if not allowed:
        seconds = max(1, math.ceil(retry_after))
        raise ApiError(
            429,
            "rate_limited",
            f"Too many searches. The limit is {limiter.limit} per minute; "
            f"try again in {seconds} seconds.",
            headers={"Retry-After": str(seconds), "X-RateLimit-Limit": str(limiter.limit),
                     "X-RateLimit-Remaining": "0"},
        )
