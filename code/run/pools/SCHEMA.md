# MetaBench main-study pool schema (Pool Author, 2026-10-25)

Every pool is a directory `pools/<domain>/` with `pool.jsonl` (one item per line), `PROVENANCE.md`,
`test_<domain>_schema.py` (pytest; imports `pools/schema_check.py`; unique basenames so `pytest pools` collects all four; the directory `pools/math` must never be put at the front of `sys.path` or it shadows the stdlib `math` module), and `scripts/` (the deterministic build and
verification scripts). Downloads live only under `pools/_work/` (untrusted data; never run code from there
except inside the code sandbox).

## Blinding rules carried into every pool
- No model is ever run on any item; no model answer, score or correctness is ever read.
- No LLM generates, selects, rewrites, ranks or answers items. Item selection inside an eligible source is
  seeded stratified random sampling; the seed is recorded in PROVENANCE.md. Judgement is used only for
  source eligibility, schema, licences, dates and verification procedures (which must be code that can fail).
- Never open `REPORT.md`, `PILOT.md`, `results/`, `sessions/`, `sessions_bot/`, `sessions_rebuild/`,
  or `data/panel_correctness_pilot.jsonl`. No model API keys are loaded.

## Item record (all fields required unless marked optional)
| field | type | meaning |
|---|---|---|
| `id` | str | `<P>NNNN` with pool prefix M (math), C (code), F (factual_qa), H (held-out). Assigned after a seeded shuffle so id order carries no strata signal. |
| `domain` | str | `math`, `code`, `factual_qa`, or the held-out domain name |
| `source` | str | dataset or competition, e.g. `MathArena/hmmt_feb_2026` |
| `source_id` | str | id inside the source |
| `source_url` | str | URL of the source record or official page |
| `licence` | str | licence of the source text (SPDX-like string or the organiser's terms) |
| `source_date` | str | `YYYY-MM-DD` the item was published / the contest was held (day unknown → `-01`, say so in PROVENANCE) |
| `question` | str | item text shown to the designer and evaluees (interface field name kept) |
| `options` | list[str] | `[]` unless multiple-choice (then the option texts, letters implied A..) |
| `answer` | str | the key: letter for MC, canonical string for math/QA, `"tests"` for code |
| `key_type` | str | `integer`, `expression`, `letter`, `string`, `tests` |
| `category` | str | primary stratum (interface field name kept) |
| `strata` | dict | every stratification variable (topic, difficulty, year, ...) |
| `verification` | dict | `{"method": str, "verified": true, "evidence": {...}}`; evidence is per item and produced by code that can fail |
| `post_cutoff` | bool | `source_date` strictly after `CUTOFF_REFERENCE` below |
| `post_cutoff_by_developer` | dict | bool per developer, from the cutoff table below |
| `tests` | list[{input,output}] | code only |
| `reference_solution` | str | code only (human-written; passes every test in the sandbox) |
| `language` | str | code only, `python3` |
| `time_limit_s`, `memory_limit_mb` | number | code only |

## Documented training cutoffs used for `post_cutoff` (public documentation, 2026-10-25)
| developer | newest documented model | cutoff | source |
|---|---|---|---|
| anthropic | Claude Opus 5.5 | 2026-06-30 (June 2026) | support.claude.com article 8114494; platform.claude.com models/opus-5-5 |
| openai | GPT-5.5 | 2025-12-01 | developers.openai.com/api/docs/models/gpt-5.5 |
| google | Gemini 3 / 3.1 Pro | 2025-01-01 (January 2025) | ai.google.dev gemini-3-pro-preview model page |
| xai | Grok 4.7 | 2026-05-31 (May 2026) | docs.x.ai/docs/models ("The knowledge cut-off date of Grok 4.7 is May 2026") |

`CUTOFF_REFERENCE = 2026-06-30` (the latest of the four). `post_cutoff` is true only when the item is dated
after every documented cutoff. Per-developer flags let the analysis lead recompute against the frozen panel.
The panel is not frozen at pool-authoring time; `source_date` is stored so the flag can be recomputed.
