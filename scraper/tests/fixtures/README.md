# Parser fixtures

| File | Where it came from |
| --- | --- |
| `search_page_real.json` | Real NHPR response: the first four records of one results page for Ludhiana, Punjab. Phone numbers, emails, contact people and health IDs are removed; photos were cut out at fetch time. |
| `districts_of_state_3.json` | Real NHPR response (`/v4/hfr/master/lgdMasters/districtsOfState/3`), first four entries, captured from the public search page. |
| `search_page.json` | Hand-written, in NHPR's shape. The facilities are made up (`Sample ...`, IDs `IN0399...`) and cover the kinds of mess the real page above doesn't happen to contain: swapped coordinates, bad pincodes, ICU beds above total beds, missing names. |

To add another real page after a crawl:

```powershell
python -m scraper fixture <raw_response_id> scraper/tests/fixtures/<name>.json --records 4
```

`fixture` removes personal details on the way out.
