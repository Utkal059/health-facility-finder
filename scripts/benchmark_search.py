"""Measure search latency against a running API.

    python scripts/benchmark_search.py --base-url http://localhost:8000 --rounds 50

Runs a fixed mix of realistic searches (by state, by district, by name with a
typo, combined filters, sorted by beds, facility ID) and prints p50/p95/p99
for each, plus overall. It reports both the time the client saw and the time
the server spent (the X-Response-Time-Ms header), so network latency to a
hosted API can be told apart from query time.

Search is rate limited to 60 requests a minute per IP. Locally, run the API
with RATE_LIMIT_PER_MINUTE=100000. Against the hosted API, keep the limit and
pace the requests instead:

    python scripts/benchmark_search.py --base-url https://YOUR-API --rounds 20 --delay 1.05
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time

import httpx


def build_queries(client: httpx.Client) -> dict[str, dict[str, str]]:
    """Pick real states, districts and an ID from the API so the mix fits the data."""
    states = client.get("/api/masters/states").json()["states"]
    state = max(states, key=lambda s: s["facilityCount"])
    districts = client.get(f"/api/masters/states/{state['code']}/districts").json()["districts"]
    district = max(districts, key=lambda d: d["facilityCount"])
    sample = client.get("/api/facilities", params={"state": state["code"]}).json()["facilities"]
    if not sample:
        sys.exit("The database has no facilities yet; load a crawl or snapshot first.")

    return {
        "state": {"state": state["code"]},
        "state + district": {"state": state["code"], "district": district["code"]},
        "name, partial": {"name": "hospital"},
        "name, with a typo": {"name": "hospitl"},
        "district + ICU + sort beds": {"district": district["code"], "icu": "yes", "sort": "beds"},
        "ownership + type": {"state": state["code"], "ownership": "P", "facilityType": "Hospital"},
        "facility ID": {"facilityId": sample[0]["facilityId"]},
        "state, page 5": {"state": state["code"], "page": "5"},
    }


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(pct / 100 * len(ordered)) - 1))
    return ordered[index]


def summarise(label: str, client_ms: list[float], server_ms: list[float]) -> str:
    return (
        f"{label:<28} {percentile(client_ms, 50):>7.1f} {percentile(client_ms, 95):>7.1f} "
        f"{percentile(client_ms, 99):>7.1f}   {statistics.median(server_ms):>7.1f} "
        f"{percentile(server_ms, 95):>7.1f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--rounds", type=int, default=50, help="requests per query (default 50)")
    parser.add_argument("--delay", type=float, default=0.0,
                        help="seconds to wait between searches, to stay under the rate limit")
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        queries = build_queries(client)
        for params in queries.values():  # warm up connections and caches once
            client.get("/api/facilities", params=params)
            time.sleep(args.delay)

        timings: dict[str, tuple[list[float], list[float]]] = {q: ([], []) for q in queries}
        for _ in range(args.rounds):
            for label, params in queries.items():
                started = time.perf_counter()
                response = client.get("/api/facilities", params=params)
                elapsed = (time.perf_counter() - started) * 1000
                if response.status_code == 429:
                    sys.exit("Rate limited: raise RATE_LIMIT_PER_MINUTE, or pass --delay 1.05.")
                response.raise_for_status()
                timings[label][0].append(elapsed)
                timings[label][1].append(float(response.headers.get("X-Response-Time-Ms", "nan")))
                time.sleep(args.delay)

    total = sum(len(c) for c, _ in timings.values())
    print(f"{total} searches against {args.base_url}\n")
    print(f"{'query':<28} {'client ms':^23}   {'server ms':^15}")
    print(f"{'':<28} {'p50':>7} {'p95':>7} {'p99':>7}   {'p50':>7} {'p95':>7}")
    for label, (client_ms, server_ms) in timings.items():
        print(summarise(label, client_ms, server_ms))
    all_client = [ms for c, _ in timings.values() for ms in c]
    all_server = [ms for _, s in timings.values() for ms in s]
    print("-" * 75)
    print(summarise("all searches", all_client, all_server))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
