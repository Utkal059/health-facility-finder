# Health Facility Finder

Search India's registered health facilities by state, district, name, type,
ownership and services. The data is collected from the public
[NHPR facility search](https://nhpr.abdm.gov.in/nhpr/v4/search/facility),
cleaned and validated into Postgres, served by a FastAPI service and searched
from a small React app.

| | |
|---|---|
| Web app | _fill in: Vercel URL_ |
| API | _fill in: Render URL_ (OpenAPI docs at `/docs`) |
| Data | _fill in: N facilities, 5 states, M districts_ (see [Run report](#run-report)) |

---

## Contents

1. [Run it locally](#run-it-locally)
2. [Architecture](#architecture)
3. [Data model](#data-model)
4. [The scraper](#the-scraper)
5. [The API](#the-api)
6. [The frontend](#the-frontend)
7. [Performance](#performance)
8. [Tests](#tests)
9. [Deployment](#deployment)
10. [Decisions and trade-offs](#decisions-and-trade-offs)
11. [Known issues](#known-issues)
12. [With more time](#with-more-time)
13. [Use of AI tools](#use-of-ai-tools)

---

## Run it locally

### Everything at once

```bash
docker compose up --build
```

| Service | What it does | URL |
|---|---|---|
| `db` | Postgres 16 (also creates an empty `hff_test` database for the tests) | `localhost:5432` |
| `seed` | applies the migrations, then loads the committed scrape snapshot through the real parser | runs once |
| `api` | FastAPI | <http://localhost:8000/docs> |
| `web` | the built React app behind nginx | <http://localhost:8080> |

`seed` runs the same code as a live crawl (parse, validate, quarantine,
dedupe), so the data you see is rebuilt from raw NHPR responses rather than
from a pre-baked dump.

### For development

Python 3.12 and Node 20+.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                 # Windows: copy .env.example .env

docker compose up -d db              # or any Postgres 16 with pg_trgm
python -m db.migrate
python -m scraper snapshot load      # load the committed data

uvicorn api.main:create_app --factory --reload          # http://localhost:8000

cd frontend
npm install
npm run dev                                             # http://localhost:5173
```

### Repository layout

```
db/migrations/      SQL migrations, applied in order by `python -m db.migrate`
scraper/            crawler, parser, validation, loader, CLI  (python -m scraper ...)
scraper/tests/      parser and normalisation tests on fixtures, loader integration tests
api/                FastAPI app: search query builder, routes, rate limit, cache
api/tests/          query-builder unit tests, API integration tests
frontend/           React + TypeScript (Vite)
scripts/            latency benchmark
data/snapshot/      the raw scrape, gzipped JSON lines (see its README)
```

---

## Architecture

```mermaid
flowchart LR
    NHPR["NHPR public search<br/>(browser + CAPTCHA)"]
    subgraph Ingestion["Ingestion (python -m scraper)"]
        Crawler["Crawler<br/>Playwright, one tab,<br/>operator types CAPTCHA"]
        Raw[("raw_responses<br/>exactly what NHPR sent")]
        Loader["Parser, validator,<br/>loader"]
    end
    subgraph Serving
        DB[("facilities + masters<br/>Postgres")]
        Q[("quarantined_records")]
        API["FastAPI"]
        Web["React app"]
    end
    NHPR --> Crawler --> Raw --> Loader
    Loader --> DB
    Loader --> Q
    DB --> API --> Web
    Raw -. "snapshot export" .-> Snap["data/snapshot/*.jsonl.gz"]
    Snap -. "snapshot load / docker compose" .-> Raw
```

The one idea that shapes the rest is **fetching and parsing are separate
steps**. The crawler only fetches and stores raw JSON. The loader turns stored
raw JSON into rows. That means:

- re-parsing never touches NHPR (`python -m scraper parse`), so a parser fix
  is free to apply to the whole scrape;
- `docker compose up` and a fresh deploy run the same ingestion code as the
  crawl, from the committed snapshot;
- every facility row can be traced back to the response it came from.

---

## Data model

```mermaid
erDiagram
    states ||--o{ districts : contains
    districts ||--o{ sub_districts : contains
    states ||--o{ facilities : "located in"
    districts ||--o{ facilities : "located in"
    sub_districts |o--o{ facilities : "located in"
    ownership_types |o--o{ facilities : "owned as"
    facility_types |o--o{ facilities : "is a"
    facilities ||--o| facility_infrastructure : has
    facilities ||--o{ facility_specialities : offers
    specialities ||--o{ facility_specialities : "offered by"
    facilities ||--o{ facility_systems_of_medicine : practises
    systems_of_medicine ||--o{ facility_systems_of_medicine : "practised by"
    crawl_runs ||--o{ raw_responses : fetched
    raw_responses ||--o{ facility_sightings : "seen in"
    facilities ||--o{ facility_sightings : "seen as"
    raw_responses ||--o{ quarantined_records : rejected

    states {
        smallint lgd_code PK
        text name UK
    }
    districts {
        int lgd_code PK
        smallint state_lgd_code FK
        text name
    }
    sub_districts {
        int lgd_code PK
        int district_lgd_code FK
        text name
    }
    ownership_types {
        text code PK "G, P, PP"
        text name UK
    }
    facility_types {
        int id PK
        text code UK
        text name UK
    }
    systems_of_medicine {
        int id PK
        text code UK
        text name UK
    }
    specialities {
        int id PK
        text code UK
        text name UK
    }
    facilities {
        char12 facility_id PK "IN + 2-digit state LGD + 8 digits"
        text name
        text status
        text ownership_code FK
        int facility_type_id FK
        smallint state_lgd_code FK
        int district_lgd_code FK
        int sub_district_lgd_code FK
        text address
        char6 pincode
        numeric latitude
        numeric longitude
        bool abdm_software
        text phone
        timestamptz first_seen_at
        timestamptz last_seen_at
    }
    facility_infrastructure {
        char12 facility_id PK, FK
        bool has_icu_beds
        int total_beds
        int icu_beds
        int ventilators
    }
    facility_specialities {
        char12 facility_id PK, FK
        int speciality_id PK, FK
    }
    facility_systems_of_medicine {
        char12 facility_id PK, FK
        int system_id PK, FK
    }
    raw_responses {
        bigint id PK
        text kind
        text source_key UK
        jsonb body
        char64 body_sha256
        timestamptz fetched_at
    }
    quarantined_records {
        bigint id PK
        bigint response_id FK
        int record_index
        text_array reasons
        jsonb record
    }
    facility_sightings {
        char12 facility_id PK, FK
        bigint response_id PK, FK
    }
    crawl_runs {
        int id PK
        text status
        jsonb report
    }
```

The database enforces the rules itself. Validation in the parser is the first
line of defence, not the only one:

- `facility_id` must match `^IN[0-9]{10}$`; `pincode` must be six digits not
  starting with 0; coordinates must fall inside India's bounding box, and both
  or neither must be set; `icu_beds <= total_beds`; counts are non-negative;
  phones are stored as `+91XXXXXXXXXX` or not at all.
- **A district must belong to the facility's state, and a sub-district to its
  district.** These are composite foreign keys (`(district, state) → districts`),
  so a record claiming "Amritsar, Gujarat" cannot be stored, whatever the code
  above it does.
- Name search uses a `pg_trgm` GIN index, which serves both `ILIKE '%term%'`
  and the typo-tolerant word-similarity operator. The other filters and sorts
  have plain or partial B-tree indexes (`db/migrations/004_search_indexes.sql`).

Migrations are plain SQL files, applied in order inside a transaction each,
under an advisory lock, and recorded with a checksum so an edited migration
is caught instead of silently skipped.

---

## The scraper

### What NHPR's search looks like

The scraper's design started from the site's public JavaScript bundle and the
network calls the search page makes. Four things decided it:

1. **Every new search needs a CAPTCHA.** The search API refuses requests
   without a fresh one. "Load more" on an existing search does not need one.
2. **The results list stops at 50.** The UI loads 10 at a time and offers no
   way past 50 results for one search, even when NHPR reports thousands of
   matches. So one search is one (state, district) pair, optionally split
   further by ownership.
3. **The results already contain everything the details page shows.** NHPR's
   details page renders the record the search already returned and fetches
   nothing else, so opening it would add over a thousand page loads and no data.
   The brief asks for each details page to be opened; this is the one step I
   left out on purpose, as the more polite way to get the same fields. The
   encodings are mixed, though: `hasIcuBeds` is `"Yes"`/`"No"`
   while `abdmSoftware` is `"1"`/`"0"`, so the normaliser accepts both, and
   withdrawn specialities stay in the list marked `activeYn: "N"`, so those are
   skipped.
4. **`robots.txt` doesn't really exist.** `https://nhpr.abdm.gov.in/robots.txt`
   answers `503`, but so does any random path: it is a firewall's catch-all,
   not a robots file that is temporarily unavailable. RFC 9309 says to assume
   "disallow everything" on a 5xx, so the scraper checks a random path as
   well. If both get the same catch-all answer, it records "no robots.txt
   published" and carries on politely. If a real robots file ever appears,
   its rules and `Crawl-delay` are obeyed.

### How the crawl works

I did **not** try to solve or get around the CAPTCHA. The brief says not to
defeat access controls, and a CAPTCHA is exactly that. Instead the crawl
is human-in-the-loop:

1. The scraper opens a real Chromium window (Playwright), fills in the state,
   district and ownership filter for the next planned search, and focuses the
   CAPTCHA box.
2. The operator types the CAPTCHA and presses Search. This takes a few seconds
   per search, and there are about 30 searches. If NHPR rejects the CAPTCHA
   (a `400`/`401`, or a reply that mentions it), the scraper simply asks
   again, up to 5 times, instead of failing that district.
3. The scraper captures the JSON response, then clicks "Load more" until it
   has every result the site will show (up to 50), saving each page as it
   arrives. It waits for the button to be drawn, keeps a page the operator
   loaded by hand, and checks that no page number was skipped.
4. The pages are parsed and loaded straight away, so problems show up during
   the crawl instead of at the end.

It is slower than a fully automated crawl, but it's the honest way to use a
CAPTCHA-protected public site. And because it saves every raw page, it only
ever needs doing once.

**Politeness.** One browser, one tab, one request in flight. At least 4
seconds between requests, plus jitter. A User-Agent that names the bot and a
contact address. On `429`/`5xx` it backs off exponentially, honours
`Retry-After`, and slows the pace for the rest of the run, whether the answer
came from the search page itself, a search or a "Load more". On `403` it stops
the run and doesn't argue.

**Resumable and idempotent.** The plan (`scraper/crawl_plan.toml`) becomes a
list of tasks in `crawl_tasks`. Finished tasks are skipped on the next run,
so a crash, Ctrl+C or closed window loses at most the search in progress. A
search only counts as finished when it has everything the site shows for it;
one that stopped short runs again. If nobody types a CAPTCHA for five minutes
the run stops instead of opening the remaining searches for no one.
Raw pages are upserted on `(kind, source_key)`, and loading is idempotent (see
below), so running anything twice changes nothing.

**"Load more" can't be retried safely.** If a "Load more" request fails, the
site has already advanced its page counter, and asking again skips a page. So
on any failure mid-search the scraper starts that whole search again (new
CAPTCHA) rather than ending up with a silent gap.

### Running it

```bash
pip install -r requirements-scraper.txt
python -m playwright install chromium
# .env needs DATABASE_URL and SCRAPER_CONTACT (an email for the User-Agent)

python -m scraper crawl              # work through crawl_plan.toml; type CAPTCHAs when asked
python -m scraper status             # progress per search, totals, capped searches
python -m scraper parse              # re-parse every stored response (no network)
python -m scraper snapshot export    # write data/snapshot/nhpr_raw_responses.jsonl.gz
python -m scraper snapshot load      # load a snapshot into an empty database
```

`crawl --limit 3` does just a few searches. `crawl --refresh` searches again
even where a search is already done.

### Run report

Every run prints this and saves it to `reports/run-NNNN-<command>.json` and to
`crawl_runs.report`:

```
_fill in: paste the report printed at the end of your final crawl_
```

The format (these numbers come from the 7-record test fixture, not the crawl):

```
Run report (parse)
--------------------------------------------
Duration               0.2s
robots.txt             not checked
Search pages fetched   0
Master lists fetched   0
Retries                0
HTTP errors            none
Tasks done / failed    0 / 0
Searches capped at 50  0
Records seen           7
Facilities saved       4 (4 new, 0 updated)
Duplicates merged      0
Records quarantined    3
Rejected by reason:
  icu_beds_exceed_total_beds         1
  invalid_pincode                    1
  coordinates_outside_india          1
  invalid_facility_id                1
  missing_name                       1
Warnings (record kept):
  coordinates_swapped                1
  phone_dropped                      1
  facility_id_state_mismatch         1
```

### Cleaning and validation

The parser (`scraper/parser.py`, `scraper/normalize.py`) turns one raw record
into either a clean `FacilityRecord` or a list of reasons it can't be one.

**Normalised:** names (Unicode NFKC, collapsed whitespace, repeated
punctuation, case kept as published), addresses (parts joined, duplicate lines
removed), pincodes (`"143 001"` → `143001`), phones (first valid Indian number
→ `+91XXXXXXXXXX`), coordinates (6 decimal places, swapped lat/lon detected and
fixed), Yes/No flags, bed counts, status capitalisation, website schemes.
Placeholders like `"NA"`, `"null"`, `"-"` and `0,0` coordinates count as
missing.

**Rejected into `quarantined_records`, with every reason that applies:**

| Reason | Meaning |
|---|---|
| `missing_facility_id`, `invalid_facility_id` | no ID, or not `IN` + 10 digits |
| `missing_name`, `missing_status` | required field empty |
| `missing_state`, `missing_district`, `invalid_state`, `invalid_district` | location missing or not an LGD code |
| `invalid_pincode` | not 6 digits |
| `coordinates_outside_india`, `incomplete_coordinates`, `invalid_coordinates` | bad or half-present location |
| `icu_beds_exceed_total_beds` | the brief's sanity rule |
| `invalid_*`, `negative_*` | a count that isn't a whole, non-negative number |
| `district_not_in_state` | the district's LGD code belongs to another state |
| `db_rejected:<constraint>` | the database refused it; the constraint name says why |
| `unrecognised_page_shape` | a whole page without a facility list (stored once per page) |

**Kept, with a warning** (counted in the report): `coordinates_swapped`,
`phone_dropped` (an unusable phone is dropped, not worth losing the facility),
`sub_district_dropped`, `village_not_in_sub_district` (NHPR joins some
facilities to the wrong village: several in Ludhiana came back with villages
in Kashmir, so a village whose parent isn't the facility's own sub-district is
left out), `unknown_ownership`, `facility_id_state_mismatch` (the
ID's state digits disagree with the record's state; NHPR IDs don't change when
district boundaries do, so this is common and harmless).

A quarantined row keeps the full raw record, so any rejection can be looked
at, and fixed by a parser change plus `python -m scraper parse`.

### Deduplication rule

**The NHPR facility ID is the identity.** The same facility turns up more than
once when searches overlap (an ownership-filtered search and an unfiltered
one), or when a district is crawled again later. For each facility ID:

- there is exactly one row in `facilities`;
- **the most recently fetched copy wins, field by field, but a missing value
  never erases a known one.** If yesterday's copy had a pincode and today's
  doesn't, the pincode stays;
- grouped data (bed counts, specialities, systems of medicine, coordinates) is
  replaced as a whole when the newer copy has it, never mixed from two
  copies;
- every sighting is recorded in `facility_sightings (facility_id,
  response_id)`, and `first_seen_at`/`last_seen_at` come from fetch times, so
  you can always see where a value came from and when.

Responses are processed in fetch order, so the result doesn't depend on load
order. Loading the same data twice is a no-op (there is a test for exactly
that).

I deliberately do **not** merge different IDs that look alike (same name,
same address). On NHPR those are separate registrations, and guessing they're
the same would hide data. See [Known issues](#known-issues).

### When NHPR changes

- Field names are read with fallbacks (NHPR's names first, then the names
  Appendix A of the brief uses), so a renamed field degrades gracefully.
- **Format-change detection:** if a search's pages have no facility list, or
  more than 80% of a search's records can't be read at all, the crawl stops and
  says so, instead of filling the quarantine with thousands of rejects. The
  raw pages are already saved, so after fixing the parser,
  `python -m scraper parse` recovers everything without fetching again.
- A layout change in the search form (a missing dropdown or button) stops the
  run with a clear error instead of clicking at random.
- `python -m scraper fixture <response_id> <path>` saves any stored response as
  a test fixture (with phone numbers and emails masked), so a new format becomes
  a failing test first.

---

## The API

Interactive docs: `/docs` (OpenAPI at `/openapi.json`).

| Endpoint | |
|---|---|
| `GET /api/facilities` | search (below) |
| `GET /api/facilities/{facilityId}` | one facility, with beds, ICU, ventilators, specialities, systems of medicine |
| `GET /api/masters/states` | states, with how many loaded facilities each has |
| `GET /api/masters/states/{stateCode}/districts` | districts of one state |
| `GET /api/masters/{type}` | `ownership`, `facility-types`, `systems-of-medicine`, `specialities` |
| `GET /api/stats` | totals, counts by state/type/ownership/status, beds by district |
| `GET /health` | liveness including a database round trip |

**Search parameters:** `state`, `district`, `subDistrict` (LGD code or name),
`pincode`, `name`, `facilityId`, `ownership` (code or name), `facilityType`,
`systemOfMedicine`, `speciality`, `icu` (`yes`/`no`), `status`, `sort`
(`name`, `district`, `beds`), `page` (default 1), `pageSize` (default 10, max
50).

- At least one filter is required; an empty search is a `400`.
- `facilityId`, when given, overrides every other filter.
- `name` matches partial names (`ILIKE`) and small typos (trigram word
  similarity), so `civl hospitl` finds "Civil Hospital". With no `sort`, name
  searches come back best match first.
- The response follows the HFR shape:
  `{"facilities": [...], "totalFacilities": n, "numberOfPages": n, "message": "Request processed successfully"}`.
- Values are always bound parameters. The query builder (`api/search.py`) has
  no FastAPI or database code in it, so its rules are unit-tested directly.

**Errors** always look like this, whatever went wrong:

```json
{"error": {"code": "invalid_parameters", "message": "Some parameters are not valid.",
           "details": [{"parameter": "pageSize", "problem": "Input should be less than or equal to 50"}]}}
```

`400 empty_search`, `400 invalid_parameters`, `404 facility_not_found`,
`404 state_not_found`, `404 unknown_master_type`, `429 rate_limited` (with
`Retry-After`), `503 database_unavailable`, `500 internal_error`.

**Rate limit:** search is limited to 60 requests a minute per client IP (a
sliding window, with `X-RateLimit-Limit`/`X-RateLimit-Remaining` headers).
**Caching:** master lists and stats only change when data is loaded, so they
are cached in memory for 5 minutes and sent with `Cache-Control: max-age=300`.
**CORS** allows only the origins in `ALLOWED_ORIGINS`, and only `GET`.

---

## The frontend

React 18 + TypeScript on Vite, with no UI library: about 60 kB gzipped.

- **Search** with the State → District cascade, a "Search by" selector
  (facility name, facility type, facility ID, system of medicine), an "All
  filters" panel (ownership, ICU services, speciality), Reset filters, and
  Sort by.
- **Result cards** with name, status badge (Approved is green with a tick,
  everything else is grey and dashed, so it doesn't rely on colour alone), ID,
  ownership, type, ICU, ABDM software, address, district, state, pincode and a
  map link. Total count and pagination.
- **`/facility/:id`** details page, with a link back to the same results.
- **The whole search lives in the URL** with the API's own parameter names, so
  results can be bookmarked and shared, and back/forward work.
- **Loading, empty and error states** everywhere, including rate limiting and
  the server being unreachable, each with a retry.
- **Accessibility:** every control has a visible label, the ICU choice is a
  real radio group, focus moves to the results heading when the page changes,
  a skip link, visible focus rings, 44px touch targets. It works from the
  keyboard alone and at 360px wide with no horizontal scrolling. It follows
  the OS dark mode.
- **Coverage page** (`/stats`): headline numbers, bar charts of facilities by
  state, type and ownership (each can switch to a table), and bed capacity by
  district.

---

## Performance

Measured with `scripts/benchmark_search.py`, which runs a fixed mix of eight
realistic searches and reports client-side and server-side
(`X-Response-Time-Ms`) percentiles.

| Where | Searches | p50 | p95 | p99 |
|---|---|---|---|---|
| Local (Docker, laptop) | _fill in_ | _fill in_ | _fill in_ | _fill in_ |
| Hosted (Render ↔ Neon, measured from India) | _fill in_ | _fill in_ | _fill in_ | _fill in_ |

```bash
# local: lift the rate limit for the benchmark
RATE_LIMIT_PER_MINUTE=100000 uvicorn api.main:create_app --factory
python scripts/benchmark_search.py --rounds 50

# hosted: keep the limit and pace the requests
python scripts/benchmark_search.py --base-url https://YOUR-API --rounds 20 --delay 1.05
```

Why it's fast enough: every filter has an index, the count and the page are
two cheap queries, the count query skips the joins it doesn't need, and the
dataset is small. Hosted latency is mostly the network. Render's free tier
also sleeps after 15 idle minutes, so the first request after a pause takes
up to a minute. The benchmark warms up first, and the numbers above are for a
warm service.

---

## Tests

```bash
pytest                                   # unit tests (no database needed)

# integration tests need a disposable database; docker compose creates one
TEST_DATABASE_URL=postgresql://hff:hff@localhost:5432/hff_test pytest

cd frontend && npm test                  # URL state and pagination
ruff check .
```

| Suite | What it covers |
|---|---|
| `scraper/tests/test_parser.py` | parser on a real NHPR page and hand-written fixtures: clean records, messy-but-valid ones, every rejection reason, page shapes, master lists |
| `scraper/tests/test_normalize.py` | names, addresses, pincodes, phones, coordinates, counts |
| `scraper/tests/test_politeness.py` | robots.txt handling (including the catch-all 503), Retry-After, backoff, pacing |
| `scraper/tests/test_crawler_replies.py` | how the crawler reads NHPR's answer to a search: results, rejected CAPTCHA, block, slow down |
| `scraper/tests/test_plan_and_sources.py` | the crawl plan file, recognising NHPR's search and master-list URLs, stripping base64 images from raw pages |
| `scraper/tests/test_crawler_browser.py` | the crawler in headless Chromium against a fake NHPR page: late or missing Load More, failed and empty pages, an absent operator (skipped without Chromium) |
| `scraper/tests/test_snapshot.py` | personal details are stripped before the snapshot is committed |
| `scraper/tests/test_loader_db.py` | loading into Postgres: quarantine with reasons, idempotency, newest-copy-wins dedup, cross-state districts, format-change stop, snapshot round trip, clean rebuild, unfinished searches run again |
| `api/tests/test_search_query.py` | the query builder: empty search, facilityId override, every filter, typo matching, LIKE escaping, sort and paging |
| `api/tests/test_rate_limit_and_cache.py` | the 60/min sliding-window limiter, client IP behind a proxy, the TTL cache |
| `api/tests/test_api_integration.py` | every endpoint against a real database: HFR response shape, typo search, paging, 400/404/429 errors, CORS, OpenAPI |

CI (`.github/workflows/ci.yml`) runs ruff and the full pytest suite against a
Postgres service, then the frontend tests and production build, on every push
and pull request.

---

## Deployment

Postgres on **Neon**, the API on **Render**, the web app on **Vercel**. All free tiers.

1. **Neon:** create a project (region: Singapore, close to Render's), and copy
   the *direct* connection string (not the `-pooler` one; psycopg uses
   prepared statements).
2. **Load the data** from your machine:
   ```bash
   DATABASE_URL="postgresql://...neon.tech/neondb?sslmode=require" python -m db.migrate
   DATABASE_URL="postgresql://...neon.tech/neondb?sslmode=require" python -m scraper snapshot load
   ```
3. **Render:** New → Blueprint → this repository (`render.yaml`). Set
   `DATABASE_URL` to the Neon string.
4. **Vercel:** import the repository, set the root directory to `frontend`, and
   set `VITE_API_BASE_URL` to the Render URL.
5. Put the Vercel URL into `ALLOWED_ORIGINS` in `render.yaml` and push (a
   service made without the blueprint needs it in the Render dashboard
   instead), then check `/health`, a search, and a details page.

No secret is in the repository. Everything comes from environment variables
(`.env.example` lists them), and `.env` is git-ignored.

---

## Decisions and trade-offs

- **Human-typed CAPTCHAs instead of automation.** This is the slowest part of
  the project, and it's deliberate: solving or bypassing the CAPTCHA would be
  defeating an access control. About 30 searches typed by hand is a
  reasonable price, and the raw store means it only has to happen once.
- **Search per district, not per state.** The site shows at most 50 results per
  search, so district searches (optionally split by ownership) get far more
  coverage. The report counts searches that hit the cap, so the coverage is
  stated honestly instead of implied.
- **Raw first, parse second.** Storing NHPR's responses verbatim costs a
  little space and buys re-parsing without re-crawling, reproducible test
  fixtures, an audit trail, and a deployment seeded through the real pipeline.
- **The database enforces the rules too.** Check constraints and composite
  foreign keys mean bad data cannot get in even through a bug in the loader.
  The loader catches a database refusal per record (with a savepoint), so one
  bad record never sinks a page.
- **Postgres trigram search, not Elasticsearch.** At this size, `pg_trgm`
  gives partial and typo-tolerant search in one index with nothing extra to
  run.
- **Synchronous FastAPI + psycopg pool.** Simple, and fast enough. Each request
  is two short indexed queries.
- **In-memory rate limit and cache.** Right for one small instance. Running
  several would need Redis for both.
- **No personal details in the committed snapshot.** NHPR's responses carry
  contact people's names, phone numbers, emails and health IDs. A git
  repository keeps what goes into it forever and search needs none of it, so
  the export removes them, including inside free text.
- **`parse` rebuilds instead of merging.** Merging keeps a known value when a
  newer copy lacks it, which would also keep values an older parser got wrong.
  Re-parsing deletes the parsed rows and reloads them from the raw responses
  in one transaction.

### Assumptions

- "Facility" means what NHPR's facility search returns, with its own ID as the
  identity.
- Bed counts are as published. Many facilities publish none, which the UI
  shows as "Not published" and the stats treat as unknown (not zero).
- `hasIcuBeds` "No" also covers "not published", which matches what NHPR shows.
- LGD codes from NHPR's own master lists are the reference for states,
  districts and sub-districts.

---

## Known issues

- **At most 50 facilities per search.** Busy districts have more than NHPR will
  show. Splitting by ownership (`ownership_filters = ["G", "P", "PP"]` in the
  plan) raises the ceiling to 150 per district; going further would need more
  filter combinations.
- **The crawl needs a person** for each new search because of the CAPTCHA, so
  it can't run on a schedule.
- **Sub-districts have codes but no names.** NHPR's results send only the
  sub-district's LGD code, and its search page never loads a sub-district
  list. `subDistrict` filters by code; `subDistrictName` is empty.
- **No fuzzy dedup across IDs.** Two registrations of what is clearly the same
  clinic stay as two facilities.
- **Rate limiting trusts `X-Forwarded-For` on Render**, which a determined
  client can spoof. It's there to keep the service fair, not as a security
  boundary.
- **Cold starts:** Render's free tier sleeps when idle, and Neon suspends
  compute, so the first request after a quiet spell is slow. The API checks
  each pooled connection before using it, so a suspended database costs a
  short wait and not an error.
- The facility ID's state digits sometimes disagree with the facility's
  current state (warning `facility_id_state_mismatch`). I keep these records,
  because NHPR IDs don't change when boundaries do.

## With more time

- Track changes between crawls (status changes, beds added) using the
  sightings table, and show "last verified" more prominently.
- A map view using the coordinates, with clustering.
- Move the rate limit and cache to Redis, and add request IDs and structured
  logs.
- Frontend component tests (React Testing Library) and an end-to-end smoke
  test (Playwright) in CI.
- Ask NHPR/ABDM for proper API access: the public search was never meant to be
  the source for a dataset.

---

## Use of AI tools

- **Gemini**: an early brainstorm of the stack and schema.
- **Claude (Claude Code)**: investigating NHPR's public JavaScript and network
  calls, and writing tests, from the brief
  and my instructions.

The reasoning behind the design is in
[Decisions and trade-offs](#decisions-and-trade-offs).
