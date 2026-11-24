# Scrape snapshot

`nhpr_raw_responses.jsonl.gz` is the raw output of the crawl: one JSON line per
NHPR response (search pages and master lists), exactly as stored in the
`raw_responses` table, with two changes:

- large base64 blobs (facility photos) were cut out at fetch time; their path,
  length and sha256 are kept in `stripped_fields`;
- phone numbers and email addresses are removed on export (see
  `scraper/snapshot.py` for why).

It holds raw responses rather than parsed rows on purpose. Loading it runs the
same parser, validation, quarantine and dedup as a live crawl:

```
python -m scraper snapshot load            # into $DATABASE_URL
docker compose up --build                  # does the same in the `seed` service
```

To refresh it after a new crawl:

```
python -m scraper snapshot export
```

The file is byte-for-byte reproducible (sorted rows, fixed gzip timestamp), so
re-exporting unchanged data produces no git diff.
