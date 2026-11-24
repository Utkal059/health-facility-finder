# Parser fixtures

| File | Where it came from |
| --- | --- |
| `districts_of_state_3.json` | Real NHPR response (`/v4/hfr/master/lgdMasters/districtsOfState/3`), first four entries, captured from the public search page. |
| `search_page.json` | Hand-written. It follows the exact shape and field names NHPR's results and details pages read (`content`, `alternateId`, `facName`, `medicalInfraRequestDTO`, ...). The facilities are made up (`Sample ...`, IDs `IN0399...`) and seeded with the kinds of mess real registry data has. |

NHPR puts every search behind a CAPTCHA, so a real search page can only be
captured during a crawl that a person is running. After one, replace or extend
the hand-written page with a real one:

```powershell
python -m scraper status                      # find a search that went well
python -m scraper fixture <raw_response_id> scraper/tests/fixtures/search_page_real.json
```

`fixture` masks phone numbers and email addresses on the way out.
