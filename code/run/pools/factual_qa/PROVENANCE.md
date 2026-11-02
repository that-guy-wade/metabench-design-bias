# factual_qa pool — provenance (Pool Author, 2026-10-25)

## Source
- **Dataset:** OpenAI SimpleQA, `simple_qa_test_set.csv` from `openai/simple-evals` (published 2024-10-30; 4,326 items;
  columns `metadata`, `problem`, `answer`; `metadata` is a Python-dict string with `topic`, `answer_type`, `urls`).
  Questions and keys were written and verified by human trainers (two independent trainers per item per the SimpleQA
  release); no LLM wrote or selected the keys.
- **Canonical file:** https://openaipublic.blob.core.windows.net/simple-evals/simple_qa_test_set.csv
  (2,012,910 bytes), downloaded 2026-10-25 by `scripts/download.py`.
  **sha256 `feee3f7e7db3617e94e8fcf1977b756ec420ef8568f4e0fcbbe0e92e9d5fc032`.**
- The HF mirror `basicv8vc/SimpleQA` carries the same rows; it was not used.
- **Licence:** MIT (github.com/openai/simple-evals). Cited pages remain under their own licences; Wikipedia text is
  CC BY-SA 4.0. Pool field `licence` = "MIT (simple-evals); cited pages under their own licences (Wikipedia CC BY-SA 4.0)".
- **Rejected derivatives:** *SimpleQA Verified* (Google, 2025) and any other re-filtered or re-labelled subset are not
  used: their construction pipelines include LLM-based filtering/answer reconciliation, and I cannot show that their keys
  are human-only. Only the original human-written, human-verified CSV is used.
- `source_date` = `2024-10-30` for every item (the release date; items were not dated individually).
  `source_id` = the 0-based row index in the canonical CSV. `source_url` = the cited URL whose text verified the key.
  `cited_urls` (extra field) = every URL cited in the item's metadata.

## Blinding
No model was run on any item; no model answers, scores or correctness were read; no LLM generated, selected, rewrote,
ranked or answered any item. The author's judgement was used only for source eligibility, licence, dates, the
deterministic fetch/match code and the mechanical rules below, all fixed before any page text or match result was
inspected. Item selection is seeded random (seed **20261025**).

## Verification (code that can fail; `scripts/fetch.py`, `scripts/verify.py`)
Every cited URL (deduplicated on the exact string) was fetched once with User-Agent
`MetaBenchPoolAuthor/1.0 (research; contact: pool-author@metabench.invalid)` (Wikimedia's robot policy returns 403 for a
UA without a contact token, so the contact was added to the required descriptive UA), 20 s timeout, one retry on transport
error / 5xx / 429 (honouring `Retry-After`, capped at 30 s), at most 8 concurrent requests overall and 2 per host.
Rules fixed before fetching:
- `*.wikipedia.org/wiki/<title>` URLs are requested from the REST v1 endpoint `/api/rest_v1/page/html/<title>`
  (bot-friendly; keeps tables, which the `plain`/`extracts` variants drop — `page/plain` does not exist on Wikimedia
  REST v1: it returned 404 with the accepted UA in the endpoint test, and the action-API `extracts` variant drops tables) and tag-stripped; every other URL is fetched as served and
  tag-stripped (`<script>`, `<style>`, `<noscript>`, `<template>` dropped; block tags become newlines). PDFs are not parsed
  (logged as `non_text:pdf`). Scheme-less citations (`www.x.org/...`) are requested over https.
- After 3 consecutive no-response failures on one host, that host's remaining URLs are logged as skipped (circuit open)
  without a request. A URL whose latest record is a 429 is retried on a later pass of `fetch.py`; every other record is
  terminal and never re-fetched. Page text is stored at `pools/_work/factual_qa/pages/<sha256(url)>.txt` (cap 2,000,000
  chars); `fetch_log.jsonl` holds one record per attempt (`verify.py` uses the latest per URL).

**Match rule (verbatim from `scripts/verify.py`, fixed 2026-10-25 before any page was inspected):**

> normalise(s) = NFKC -> casefold -> every char that is not a letter, digit or whitespace becomes a space -> collapse
> whitespace -> strip. An item is verified when, for at least one cited page, one of these forms is found:
> * exact : normalise(answer) (>= 2 chars) is a substring of normalise(page)
> * digits: numeric answers only (answer_type == Number, or the answer is only digits/space/.,): thousands commas are
>   removed from answer and page, the digits-only answer (>= 2 digits) must occur in normalise(page) bounded by
>   non-digits
> * date  : if the answer parses as D Month YYYY / Month D, YYYY / YYYY-MM-DD / Month YYYY (English month names or
>   3-letter abbreviations, optional ordinal suffix), any standard English long/short rendering of that same date is
>   accepted as a substring of normalise(page)
> Forms are tried in the order exact, digits, date; the first hit is the evidence. No fuzzy matching.

Per-item evidence (`verification.evidence`): `url` (the matching cited URL), `fetched_at` (UTC ISO timestamp of the
fetch), `page_sha256` (sha256 of the stored stripped text), `match_form` (`exact`/`digits`/`date`), `matched` (the exact
normalised string found) and `snippet` (100 normalised chars either side of the match). `test_<domain>_schema.py` re-applies the
rule to every snippet.

Known limitations of the rule (reported, not corrected): a short key (a year, a small number, a common surname) can
match a page without the page supporting the question's specific claim; answers given as "X or Y" alternatives are
matched as one literal string and usually fail; answers whose cited pages are behind bot protection (403), require
JavaScript (202/203), moved (404/410) or are PDFs are excluded as *fetch failed* rather than *wrong*. SimpleQA keys
describe facts as of 2024, and a cited page may have changed since; the evidence snippet is what was verified today
(2026-10-25). Exclusion is a property of today's fetch, not a judgement on the item.

## Sampling (`scripts/build.py`)
From the verified items, after dropping duplicate normalised question texts (lowest row index kept), a seeded
(`random.Random(20261025)`) stratified random sample of 2,000 items with strata = `topic` and proportional allocation by
largest remainders (within a stratum, `rng.sample` over items sorted by row index). The sample is then shuffled with the
same generator and ids `F0001..` assigned in shuffled order. `category` = topic; `strata` = {topic, answer_type, n_urls}.

## Contamination
`source_date` 2024-10-30 is before every documented developer cutoff in `schema_check.DEVELOPER_CUTOFFS`
(anthropic 2026-06-30, openai 2025-12-01, google 2025-01-01, xai 2026-02-01), so `post_cutoff` and every
`post_cutoff_by_developer` flag are **false**. SimpleQA is public and widely used; this construct therefore relies on the
twin-set test (OUTSIDE_CHECKS §1), which the analysis lead runs. The cited Wikipedia pages are themselves training data
for every developer.

## Re-running
```
cd <run>; export HF_HOME=<run>/pools/_work/hf_cache
.venv/bin/python -I pools/factual_qa/scripts/download.py   # CSV + sha256 (skips if present)
.venv/bin/python -I pools/factual_qa/scripts/fetch.py      # only URLs without a terminal record (or with a 429) are requested
.venv/bin/python -I pools/factual_qa/scripts/verify.py     # -> pools/_work/factual_qa/verified.jsonl (cached pages only; deterministic)
.venv/bin/python -I pools/factual_qa/scripts/build.py      # -> pools/factual_qa/pool.jsonl, pools/_work/factual_qa/stats.json
.venv/bin/python -I pools/factual_qa/scripts/report.py     # -> the tables below
.venv/bin/python -I -m pytest pools/factual_qa -q
```
`verify.py` and `build.py` are deterministic given the cached pages and the log.

## Fetch runs (2026-10-25 UTC)
Three passes of `scripts/fetch.py` over the 12,683 unique cited URLs (12,685 before trimming whitespace):
04:46–04:50 (first 3,114 URLs; stopped to add `Retry-After` handling and 429 re-queueing after en.wikipedia.org
returned 429 for 20 URLs), 04:52–05:19 (the remaining 9,623 URLs plus the 429s), and two short passes at 05:21–05:23 for
the 429s. All 4,049 en.wikipedia.org URLs ended with a definitive answer (3,992 stored, 56 HTTP 404 for malformed titles,
1 transport error). 36 URLs on 16 hosts (15 at www.metmuseum.org) still returned 429 on the third pass and are counted
as fetch failures. 73 metadata entries are not URLs at all (free-text notes, several URLs pasted into one field, or
URLs wrapped in quotes); they are logged under an empty host and counted as fetch failures. No fetched content was
executed; pages are stored only as stripped text.

## Statistics (generated by `scripts/report.py`; copied verbatim)

Unique cited URLs with a terminal fetch record: 12683

### Fetch outcome by status

| outcome | URLs |
|---|---|
| 200 (text stored) | 8797 |
| 403 | 2375 |
| 404 | 418 |
| 202 | 274 |
| 200 but non-text (pdf) | 209 |
| no response: ConnectError | 150 |
| no response: skipped (host circuit open) | 103 |
| no response: ConnectTimeout | 64 |
| no response: ReadTimeout | 47 |
| 429 | 36 |
| 401 | 33 |
| 405 | 25 |
| 402 | 24 |
| 410 | 23 |
| 500 | 21 |
| 503 | 15 |
| no response: RemoteProtocolError | 10 |
| 522 | 10 |
| 203 | 9 |
| no response: ValueError | 6 |
| 307 | 6 |
| no response: UnsupportedProtocol | 4 |
| 502 | 4 |
| 999 | 4 |
| no response: TooManyRedirects | 3 |
| no response: ReadError | 3 |
| 504 | 3 |
| 400 | 2 |
| 409 | 1 |
| 445 | 1 |
| 530 | 1 |
| 495 | 1 |
| 204 | 1 |

### Top 25 hosts (unique URLs, text stored)

| host | URLs | text stored |
|---|---|---|
| en.wikipedia.org | 4049 | 3992 |
| www.imdb.com | 134 | 0 |
| mathshistory.st-andrews.ac.uk | 121 | 121 |
| www.wikiwand.com | 103 | 0 |
| es.wikipedia.org | 77 | 76 |
| kids.kiddle.co | 75 | 75 |
| www.britannica.com | 74 | 0 |
| (no scheme/host) | 73 | 0 |
| www.familysearch.org | 53 | 0 |
| dbpedia.org | 48 | 48 |
| web.archive.org | 48 | 25 |
| alchetron.com | 43 | 43 |
| www.researchgate.net | 42 | 0 |
| www.youtube.com | 37 | 37 |
| www.findagrave.com | 36 | 0 |
| www.wikidata.org | 35 | 35 |
| timesofindia.indiatimes.com | 33 | 33 |
| www.discogs.com | 31 | 0 |
| www.nytimes.com | 30 | 1 |
| www.encyclopedia.com | 28 | 28 |
| www.rsc.org | 26 | 0 |
| wikiroulette.co | 25 | 25 |
| commons.wikimedia.org | 25 | 24 |
| www.puebliandoporantioquia.com.co | 25 | 24 |
| www.theguardian.com | 24 | 24 |

Hosts total: 4469; items (CSV rows): 4326; status counts: {'fetch_failed': 128, 'no_match': 470, 'verified': 3728}

### Verified fraction per topic

| topic | items | verified | fraction | in pool |
|---|---|---|---|---|
| Art | 550 | 498 | 0.905 | 267 |
| Geography | 424 | 381 | 0.899 | 204 |
| History | 173 | 149 | 0.861 | 80 |
| Music | 341 | 288 | 0.845 | 155 |
| Other | 475 | 397 | 0.836 | 213 |
| Politics | 709 | 654 | 0.922 | 351 |
| Science and technology | 858 | 770 | 0.897 | 413 |
| Sports | 368 | 292 | 0.793 | 157 |
| TV shows | 293 | 202 | 0.689 | 108 |
| Video games | 135 | 97 | 0.719 | 52 |

### Verified fraction per answer_type

| answer_type | items | verified | fraction | in pool |
|---|---|---|---|---|
| Date | 1418 | 1309 | 0.923 | 736 |
| Number | 663 | 446 | 0.673 | 226 |
| Other | 777 | 640 | 0.824 | 339 |
| Person | 1041 | 936 | 0.899 | 485 |
| Place | 427 | 397 | 0.93 | 214 |

### Match form among verified items

| form | items |
|---|---|
| date | 161 |
| digits | 47 |
| exact | 3520 |

### Exclusions by reason and topic

| topic | fetch_failed | no_match |
|---|---|---|
| Art | 6 | 46 |
| Geography | 12 | 31 |
| History | 5 | 19 |
| Music | 7 | 46 |
| Other | 15 | 63 |
| Politics | 4 | 51 |
| Science and technology | 31 | 57 |
| Sports | 9 | 67 |
| TV shows | 23 | 68 |
| Video games | 16 | 22 |
| total | 128 | 470 |

Duplicate question texts dropped before sampling: 0; seed 20261025; target 2000; pool size 2000.

Items are excluded only for *fetch failed* (no cited page yielded text) or *no match* (text from at least one cited
page, none containing the key under the rule). 3,728 / 4,326 = 86.2 % verified; the pool holds 2,000 of them.
The per-topic allocation is proportional to verified counts (largest remainders), so the pool's topic mix mirrors the
verified set, not the original SimpleQA mix; `TV shows`, `Video games` and `Sports` verify least often (their citations
are more often IMDb, fandom wikis and bot-protected sites, see the host table).
