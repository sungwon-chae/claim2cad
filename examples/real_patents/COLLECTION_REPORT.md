# Phase V1-1 — Real Patent Collection Report

Collected 25 expired pre-2000 mechanical patents from Google Patents.

## Method

- **Source priority** (per the brief): Google Patents → USPTO PatentsView → WIPO PATENTSCOPE.
- **Reality:** USPTO PatentsView API was retired in 2025 and now redirects to a transition page on `data.uspto.gov` (verified by HEAD/POST request). Pivoted to a hand-curated seed list of well-known mechanical patents fetched directly from `patents.google.com`. This is more deterministic than scraping Google Patents' search page (which is JS-heavy and brittle).

- **Rate limit:** ≥2.2 s between fetches; cached HTML and figure binaries in `.cache/patents/`. Re-runs are free.
- **User-Agent:** `Claim2CAD-research/1.0 (https://github.com/sungwon-chae/claim2cad)`

## Distribution by class

- USPC 074: 10
- USPC 901: 9
- USPC 414: 3
- USPC 16: 3

## Working set: 25 patents

Every patent in this directory has:

- a non-empty claim 1 (100 ≤ chars ≤ 8000)
- a title
- ≥ 1 figure successfully downloaded
- a `source_metadata.json` with the fetch URL and timestamp

Pipeline-validation results land in V1-2's `COLLECTION_VALIDATION_REPORT.md`.
