from types import SimpleNamespace

from api.cache import TtlCache
from api.rate_limit import SlidingWindowLimiter, client_ip


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_limit_applies_per_client_and_frees_up_after_the_window():
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=3, window=60, clock=clock)
    assert [limiter.hit("a")[0] for _ in range(3)] == [True, True, True]

    allowed, remaining, retry_after = limiter.hit("a")
    assert (allowed, remaining, retry_after) == (False, 0, 60)
    assert limiter.hit("b")[0] is True  # someone else is unaffected

    clock.now += 60.5
    assert limiter.hit("a") == (True, 2, 0.0)


def test_client_ip_only_trusts_forwarded_header_when_told_to():
    request = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.9, 10.0.0.1"},
        client=SimpleNamespace(host="10.0.0.1"),
    )
    assert client_ip(request, trust_proxy_headers=False) == "10.0.0.1"
    assert client_ip(request, trust_proxy_headers=True) == "203.0.113.9"


def test_cache_recomputes_after_ttl():
    clock = FakeClock()
    cache = TtlCache(ttl=300, clock=clock)
    calls = []

    def compute():
        calls.append(1)
        return len(calls)

    assert cache.get_or_compute("k", compute) == 1
    assert cache.get_or_compute("k", compute) == 1
    clock.now += 301
    assert cache.get_or_compute("k", compute) == 2
