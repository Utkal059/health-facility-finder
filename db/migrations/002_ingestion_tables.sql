-- Bookkeeping for the scraper: what it was asked to crawl, what it fetched
-- (kept exactly as fetched, so parsing can be fixed and replayed offline),
-- and the records it refused to load.

CREATE TABLE crawl_runs (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    command     text        NOT NULL,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status      text        NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'finished', 'interrupted', 'blocked', 'failed')),
    report      jsonb
);

-- One row per (state, district, ownership filter) search. A crawl skips
-- tasks that are already done, which is what makes it resumable.
CREATE TABLE crawl_tasks (
    task_key         text PRIMARY KEY,
    state_name       text    NOT NULL,
    district_name    text    NOT NULL,
    ownership_filter text    REFERENCES ownership_types (code),
    status           text    NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'in_progress', 'done', 'failed')),
    attempts         integer NOT NULL DEFAULT 0,
    pages_fetched    integer NOT NULL DEFAULT 0,
    records_seen     integer NOT NULL DEFAULT 0,
    total_results    integer,          -- what NHPR said exists for this search
    hit_display_cap  boolean NOT NULL DEFAULT false,
    last_error       text,
    updated_at       timestamptz NOT NULL DEFAULT now()
);

-- Every useful response, keyed by what it answers. Fetching the same page
-- again replaces the stored copy instead of adding a second one.
CREATE TABLE raw_responses (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind            text     NOT NULL
                    CHECK (kind IN ('search_page', 'states', 'districts', 'facility_types', 'systems_of_medicine')),
    source_key      text     NOT NULL,
    url             text     NOT NULL,
    method          text     NOT NULL,
    request_body    jsonb,
    http_status     smallint NOT NULL,
    body            jsonb    NOT NULL,
    body_sha256     char(64) NOT NULL,
    -- Inline base64 images are cut out before storing (see README);
    -- this lists where they were, with their size and hash.
    stripped_fields jsonb    NOT NULL DEFAULT '[]'::jsonb,
    fetched_at      timestamptz NOT NULL,
    crawl_run_id    bigint REFERENCES crawl_runs (id) ON DELETE SET NULL,
    UNIQUE (kind, source_key)
);
CREATE INDEX raw_responses_order_idx ON raw_responses (kind, fetched_at, id);

-- Records that failed validation, with every reason they failed. Nothing is
-- dropped silently: if it was fetched, it is either loaded or listed here.
CREATE TABLE quarantined_records (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    response_id    bigint  NOT NULL REFERENCES raw_responses (id) ON DELETE CASCADE,
    record_index   integer NOT NULL,
    facility_id    text,
    reasons        text[]  NOT NULL CHECK (cardinality(reasons) > 0),
    record         jsonb   NOT NULL,
    quarantined_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (response_id, record_index)
);
CREATE INDEX quarantined_records_reasons_idx ON quarantined_records USING gin (reasons);
