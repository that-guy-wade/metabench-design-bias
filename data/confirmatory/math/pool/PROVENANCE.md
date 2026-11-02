# Math pool provenance (MetaBench main study, Pool Author, 2026-10-25)

Pool: `pools/math/pool.jsonl`, **2,000 items**, domain `math`. Two layers, both built by `scripts/build_math_pool.py`
(deterministic) from the raw downloads written by `scripts/download_sources.py` into `pools/_work/math/raw/`:

1. **Base layer, ids within `M0001`..`M1209`** (competition items). The 2026-10-25 04:52 UTC build (1,209 items,
   full-line sha256 `52f3ece33d98d6f58a3fee56c58d440edbdd40853b6073609c47a38ca785f0ae`, ids drawn by seeded shuffle,
   seed 20261025) is frozen in `base_manifest.json` (id + content hash per item). The builder assigns base ids from
   the manifest and asserts that source, source_id, question and answer are unchanged; verification metadata may be
   upgraded. **1205 of 1,209 retained**: the later BRUMO/CMIMC official-PDF check excluded 4 items, which leave
   gaps in the id range (M0617, M0898, M0962, M1034; details under "official-pdf agreement"). HMMT, BRUMO and
   CMIMC keys were checked against the organisers' solutions PDFs (`scripts/hmmt_pdf_answers.py`,
   `scripts/other_pdf_answers.py` -> `hmmt_pdf_answers.json`, `other_pdf_answers.json`).
2. **Top-up layer, ids `M1210`..`M2004`** (795 = 2000 - 1205 Hendrycks MATH test Level-5 items;
   `scripts/add_math_level5.py`, seeded stratified sample, then a seeded shuffle among themselves). Added in the
   2026-10-25 follow-up at the coordinator's request; the source was approved by the coordinator on eligibility
   grounds. Final `pool.jsonl` sha256: `6d6e4e88a35b7c2e4a72a58f022df332c9ffc5e110e4ef522c3c977a0cbd73d9`
   (two consecutive rebuilds identical).

Blinding: no model was run on any item; no model answer, score or correctness was read; no LLM generated, selected,
rewrote, ranked or answered items. Judgement was used only for source eligibility, licences, dates and the
verification/exclusion procedures below, all of which were fixed in code before any result was inspected.

## Target and shortfall (base layer)

Requested size was about 2,000 with `MIN_ITEMS 1500`. The eligible universe from the originally named sources is 1,281
records (408 MathArena contest problems + 873 gneubig AIME problems from years not covered by MathArena) before
mechanical exclusions, so the base layer keeps **everything eligible (no down-sampling)**: 1,209 items, 1205 after the
BRUMO/CMIMC PDF check. The remaining 795 come from the Hendrycks MATH top-up described in its own section below;
`test_<domain>_schema.py` uses `MIN_ITEMS = 2000`. The HMMT archive (option 3) publishes problems only as rendered PDFs; pypdf extraction mangles
the mathematics, so it was used for key verification, not as a source of item text. The only other MathArena contest
datasets are subsets of ones already used (`aime_2025_I/II`, `aime_2026_I`), proof competitions (IMO, USAMO, IMC,
Putnam, Miklós) or Math Kangaroo (multiple-choice, grade 1-12, figure-heavy): none added.

## Sources

| source | URL | licence (HF card) | contest date(s) | raw n | n in pool | excluded by rule | date provenance |
|---|---|---|---|---|---|---|---|
| MathArena/aime_2026 | https://huggingface.co/datasets/MathArena/aime_2026 | CC-BY-NC-SA-4.0 | 2026-02-05 (I) / 2026-02-11 (II) | 30 | 28 | figure_reference=2 | MAA AMC schedule: AIME I Feb 5, AIME II Feb 11 2026 (maa.org, retrieved via web search 2026-10-25; maa.org returns 403 to this box) |
| MathArena/aime_2025 | https://huggingface.co/datasets/MathArena/aime_2025 | CC-BY-NC-SA-4.0 | 2025-02-06 (I) / 2025-02-12 (II) | 30 | 25 | figure_reference=5 | MAA schedule as reported by secondary sources; AoPS wiki says Feb 5 for AIME I (conflict; neither day changes any cutoff flag) |
| MathArena/aime_2024_I | https://huggingface.co/datasets/MathArena/aime_2024_I | CC-BY-NC-SA-4.0 | 2024-02-01 | 15 | 12 | figure_reference=3 | MAA: Thursday Feb 1, 2024 |
| MathArena/aime_2024_II | https://huggingface.co/datasets/MathArena/aime_2024_II | CC-BY-NC-SA-4.0 | 2024-02-07 | 15 | 14 | figure_reference=1 | MAA: Wednesday Feb 7, 2024 |
| MathArena/aime_2023_I | https://huggingface.co/datasets/MathArena/aime_2023_I | CC-BY-NC-SA-4.0 | 2023-02-07 | 15 | 13 | figure_reference=2 | MAA 2023 schedule (not re-verified this session; pre-cutoff for every developer regardless) |
| MathArena/aime_2023_II | https://huggingface.co/datasets/MathArena/aime_2023_II | CC-BY-NC-SA-4.0 | 2023-02-15 | 15 | 12 | figure_reference=3 | MAA 2023 schedule (not re-verified this session) |
| MathArena/hmmt_feb_2026 | https://huggingface.co/datasets/MathArena/hmmt_feb_2026 | CC-BY-NC-SA-4.0 | 2026-02-14 | 33 | 30 | proof_problem=3 | date printed in the organiser's solutions PDFs (hmmt-archive.s3.amazonaws.com/tournaments/2026/feb/*/solutions.pdf) |
| MathArena/hmmt_feb_2025 | https://huggingface.co/datasets/MathArena/hmmt_feb_2025 | CC-BY-NC-SA-4.0 | 2025-02-15 | 30 | 29 | official_pdf_disagreement=1 | organiser solutions PDFs |
| MathArena/hmmt_feb_2024 | https://huggingface.co/datasets/MathArena/hmmt_feb_2024 | CC-BY-NC-SA-4.0 | 2024-02-17 | 30 | 28 | figure_reference=1, official_pdf_disagreement=1 | organiser solutions PDFs |
| MathArena/hmmt_feb_2023 | https://huggingface.co/datasets/MathArena/hmmt_feb_2023 | CC-BY-NC-SA-4.0 | 2023-02-18 | 30 | 29 | figure_reference=1 | organiser solutions PDFs |
| MathArena/hmmt_nov_2025 | https://huggingface.co/datasets/MathArena/hmmt_nov_2025 | CC-BY-NC-SA-4.0 | 2025-11-08 | 30 | 28 | figure_reference=2 | organiser solutions PDFs |
| MathArena/brumo_2025 | https://huggingface.co/datasets/MathArena/brumo_2025 | CC-BY-NC-SA-4.0 | 2025-04-05 | 30 | 29 | official_pdf_disagreement=1 | date printed in the organiser's solutions PDFs (brumo.org/s/individual-solutions.pdf: "April 5, 2025") |
| MathArena/cmimc_2025 | https://huggingface.co/datasets/MathArena/cmimc_2025 | CC-BY-NC-SA-4.0 | 2025-03-15 | 40 | 36 | proof_problem=1, official_pdf_disagreement=3 | cmimc.math.cmu.edu/math: CMIMC Math held March 15, 2025 (the solutions PDFs carry no date) |
| MathArena/smt_2025 | https://huggingface.co/datasets/MathArena/smt_2025 | CC-BY-NC-SA-4.0 | 2025-04-12 | 53 | 51 | figure_reference=2 | stanfordmathtournament.com/competitions/smt-2025: in-person April 11-12, 2025; contest day taken as April 12 |
| MathArena/apex_2025 | https://huggingface.co/datasets/MathArena/apex_2025 | CC-BY-NC-SA-4.0 | 2025-01-01 | 12 | 9 | duplicate_text=3 | compilation of 2025 olympiad problems (per-item origin in strata.apex_source); month unknown -> January 1 (conservative: flags google as pre-cutoff) |
| gneubig/aime-1983-2024 | https://huggingface.co/datasets/gneubig/aime-1983-2024 | CC0-1.0 | YYYY-03-01 (1983-2021), 2022-02-08 (I) / 2022-02-16 (II) | 933 | 832 | aime_key_not_0_999=1, figure_reference=57, year_covered_by_matharena=43 | AIME was held in March through 2021: day unknown -> first of month; 2022 days from the MAA schedule (not re-verified; pre-cutoff regardless) |

Not counted as independent sources:
- `di-zhang-fdu/AIME_1983_2024` (HF card: MIT): byte-identical to `gneubig/aime-1983-2024` (sha256
  `1fc3c34f...578e1e` for both JSONL dumps). Not a second transcription; ignored.
- `MathArena/final_answer_comps` (139 rows): a repackaging of `aime_2025`, `hmmt_feb_2025`, `brumo_2025`, `cmimc_2025`
  and 9 `apex_2025` rows. 131 pool items have whitespace-identical text in it; not double counted.
- Cross-check-only datasets (never contribute items): `opencompass/AIME2025` (MIT), `yentinglin/aime_2025` (no licence
  on card), `AI-MO/aimo-validation-aime` (Apache-2.0; AIME 2022-2024).

Rejected sources: AoPS wiki (403 from this box; not retried); `maa.org` (403; dates taken from secondary reports);
`sumo.stanford.edu` (only SMT 2011 PDFs linked) and `stanfordmathtournament.com/competitions/smt-2025` (404), so SMT
2025 items remain single-source. BRUMO 2025 and CMIMC 2025 solutions PDFs were parsed in the follow-up (see below).

## Eligibility and mechanical exclusion rules (fixed before results were seen)

1. Human-authored competition problems with an official final answer; proof problems excluded by regex
   `\b(prove|show that|proof)\b` -> 4 excluded (MathArena/hmmt_feb_2026#31, MathArena/hmmt_feb_2026#32, MathArena/hmmt_feb_2026#33, MathArena/cmimc_2025#38).
2. Figure/diagram references excluded by regex `[asy] | \begin{asy} | figure(s) | diagram(s) | as shown | shown (below|above|here|in the)
   | \includegraphics | picture(s) | drawing | ![ | .png/.jpg/.jpeg/.gif` -> 79 excluded (57 of them gneubig items with
   embedded Asymptote code).
3. Empty or non-parsable key excluded -> 0 empty; AIME key outside 0..999 or not an integer ->
   1 excluded: gneubig/aime-1983-2024 2022-II-8 (`080 or 081 (both were accepted)`).
4. gneubig years 2023 and 2024 dropped (covered by the MathArena AIME sets) -> 43 rows.
5. Duplicates (exact and whitespace-normalised, lower-cased question text) across all sources: one copy kept. Rule:
   the copy from the dataset dedicated to the originating contest wins (the APEX compilation names its origin in its
   `source` column, here `SMT 2025 P8/P42/P43`), then earliest `source_date`. 3 dropped:
- kept `MathArena/smt_2025` #8, dropped `MathArena/apex_2025` #9
- kept `MathArena/smt_2025` #42, dropped `MathArena/apex_2025` #10
- kept `MathArena/smt_2025` #43, dropped `MathArena/apex_2025` #3
6. Key normalisation: whitespace collapsed; integers stored without leading zeros; nothing else rewritten.
   `key_type` = `integer` when the key matches `-?\d+`, else `expression` (LaTeX as published by MathArena).

## Sampling

Eligible total (1209) is below the 2,000 target, so no stratified down-sampling was applied; the stratified
sampler (strata = contest family x 5-year band, seed 20261025) is in the script but did not trigger. Ids were assigned
after `random.Random(20261025).shuffle`.

## Verification methods and counts

| source | two-source agreement | official-pdf agreement | single-source |
|---|---|---|---|
| MathArena/aime_2023_I | 12 | 0 | 1 |
| MathArena/aime_2023_II | 12 | 0 | 0 |
| MathArena/aime_2024_I | 12 | 0 | 0 |
| MathArena/aime_2024_II | 14 | 0 | 0 |
| MathArena/aime_2025 | 24 | 0 | 1 |
| MathArena/aime_2026 | 0 | 0 | 28 |
| MathArena/apex_2025 | 0 | 0 | 9 |
| MathArena/brumo_2025 | 0 | 29 | 0 |
| MathArena/cmimc_2025 | 0 | 32 | 4 |
| MathArena/hmmt_feb_2023 | 0 | 29 | 0 |
| MathArena/hmmt_feb_2024 | 0 | 28 | 0 |
| MathArena/hmmt_feb_2025 | 0 | 29 | 0 |
| MathArena/hmmt_feb_2026 | 0 | 30 | 0 |
| MathArena/hmmt_nov_2025 | 0 | 28 | 0 |
| MathArena/smt_2025 | 0 | 0 | 51 |
| gneubig/aime-1983-2024 | 26 | 0 | 806 |

- **two-source agreement** (100): the MathArena/gneubig key equals the key of the text-matched problem in an
  independent transcription (opencompass/AIME2025 and yentinglin/aime_2025 for AIME 2025; AI-MO/aimo-validation-aime
  for AIME 2022-2024). Text match = `difflib.SequenceMatcher` ratio >= 0.6 on letters+digits only; answers compared after
  stripping `$`, degree signs, `\dfrac`->`\frac`, whitespace, leading zeros. Disagreements: 0. Two AIME items
  (aime_2023_I, aime_2025: one each) had no text match >= 0.6 in any cross-source and fell back to single-source
  (`cross_source_attempted: true`).
- **official-pdf agreement** (205 = 144 HMMT + 29 BRUMO + 32 CMIMC): keys compared with the `Answer:`/`Answer.` line of the
  organiser's solutions PDF (HMMT: `hmmt-archive.s3.amazonaws.com/tournaments/<year>/<feb|nov>/<round>/solutions.pdf`;
  BRUMO: `brumo.org/s/individual-solutions.pdf`, `team-solutions.pdf` (idx 1-15 / 16-30; PDFs are dated April 5, 2025);
  CMIMC: `cmimc.math.cmu.edu/archive/cmimc2025/<algnt|combo|geo|team>_sol.pdf` (idx 1-10/11-20/21-30/31-40)), parsed
  sequentially per round with pypdf 6.21.2. Two parser fixes were made after the first BRUMO/CMIMC dry run and before
  the final build (both alignment/robustness, neither changes the agreement rule): the "answer up to the next
  Solution line" pattern is capped at 120 characters (CMIMC #2 had swallowed a paragraph), and a PDF answer is only
  compared when the PDF problem head matches the item text (letters+digits similarity >= 0.5; CMIMC team round
  mis-numbered on a list inside a solution). 4 CMIMC items (idx 23, 32, 33, 34) have no aligned PDF answer and stay
  single-source (`official_pdf_result: "answer line not parsed"`). Canonical form: `√`->`sqrt`, `π`->`pi`, `\frac`/`\dfrac` removed, other LaTeX commands removed,
  then letters+digits only; the PDF's `a = b` alternatives all count (" or " alternatives do NOT; the rule was fixed
  before the BRUMO/CMIMC run and not relaxed afterwards). HMMT: 150 of the 153 raw rows had a parsed PDF answer (Feb
  2026 idx 31-33, proof-excluded anyway, did not); 148 agreed. BRUMO: 30 compared, 29 agreed. CMIMC: 36 aligned, 32
  agreed. **6 disagreements, all excluded** (the base ids they had are now gaps). CMIMC #7 (932 vs 930) is a genuine
  key discrepancy between MathArena and the organiser; the other five look like extraction/notation/form
  differences, but the rule is mechanical and no judgement was used to rescue them:
- `MathArena/hmmt_feb_2025` problem_idx 30: pool key `\sqrt{\frac{95}{24}}`; evidence `{"official_pdf": "https://hmmt-archive.s3.amazonaws.com/tournaments/2025/feb/geo/solutions.pdf", "pdf_answer_raw": "q\n95\n24"}`
- `MathArena/hmmt_feb_2024` problem_idx 9: pool key `0,i\sqrt{6},-i\sqrt{6}`; evidence `{"official_pdf": "https://hmmt-archive.s3.amazonaws.com/tournaments/2024/feb/algnt/solutions.pdf", "pdf_answer_raw": "0,±i\n√\n6"}`
- `MathArena/brumo_2025` problem_idx 28: pool key `5\sqrt{2}`; evidence `{"official_pdf": "https://www.brumo.org/s/team-solutions.pdf", "pdf_answer_raw": "5\n√\n2\n5"}`
- `MathArena/cmimc_2025` problem_idx 7: pool key `932`; evidence `{"official_pdf": "https://cmimc.math.cmu.edu/archive/cmimc2025/algnt_sol.pdf", "pdf_answer_raw": "930"}`
- `MathArena/cmimc_2025` problem_idx 17: pool key `\frac{1507^{2}}{360^{2}}`; evidence `{"official_pdf": "https://cmimc.math.cmu.edu/archive/cmimc2025/combo_sol.pdf", "pdf_answer_raw": "1372 · 112\n3602"}`
- `MathArena/cmimc_2025` problem_idx 36: pool key `3+\sqrt{2}+\sqrt{3}+\sqrt{6}`; evidence `{"official_pdf": "https://cmimc.math.cmu.edu/archive/cmimc2025/team_sol.pdf", "pdf_answer_raw": "3 +\n√\n2 +\n√\n3 +\n√\n6 or 3 +\n√\n3 + 2\np\n2 +\n√\n3"}`
  PDF-printed contest dates: HMMT Feb 2023: 2023-02-18, HMMT Feb 2024: 2024-02-17, HMMT Feb 2025: 2025-02-15, HMMT Feb 2026: 2026-02-14, HMMT Nov 2025: 2025-11-08.
- **single-source** (965): format check only (AIME integer 0..999 / non-empty LaTeX); evidence records the official
  page and whether a cross-source or PDF check was attempted. These items are flagged in `verification.method` and
  should be treated as less certain by the analysis lead.

## Cutoff table (copied from SCHEMA.md as of 2026-10-25 04:44 UTC) and per-source status

| developer | newest documented model | cutoff | source |
|---|---|---|---|
| anthropic | Claude Opus 5.5 | 2026-06-30 (June 2026) | support.claude.com article 8114494; platform.claude.com models/opus-5-5 |
| openai | GPT-5.5 | 2025-12-01 | developers.openai.com/api/docs/models/gpt-5.5 |
| google | Gemini 3 / 3.1 Pro | 2025-01-01 (January 2025) | ai.google.dev gemini-3-pro-preview model page |
| xai | Grok 4.7 | 2026-05-31 (May 2026) | docs.x.ai/docs/models ("The knowledge cut-off date of Grok 4.7 is May 2026") |

`CUTOFF_REFERENCE = 2026-06-30`. **No item is after every cutoff (`post_cutoff` = 0)**: the newest contests in the pool are
AIME 2026 (Feb 5/11) and HMMT Feb 2026 (Feb 14). Items after each developer's cutoff (`post_cutoff_by_developer`):

| contest | anthropic | openai | google | xai |
|---|---|---|---|---|
| AIME 2025 I | 0 | 0 | 13 | 0 |
| AIME 2025 II | 0 | 0 | 12 | 0 |
| AIME 2026 I | 0 | 14 | 14 | 0 |
| AIME 2026 II | 0 | 14 | 14 | 0 |
| APEX 2025 | 0 | 0 | 0 | 0 |
| BRUMO 2025 | 0 | 0 | 29 | 0 |
| CMIMC 2025 | 0 | 0 | 36 | 0 |
| HMMT Feb 2025 | 0 | 0 | 29 | 0 |
| HMMT Feb 2026 | 0 | 30 | 30 | 0 |
| HMMT Nov 2025 | 0 | 0 | 28 | 0 |
| SMT 2025 | 0 | 0 | 51 | 0 |
| pre-2025 | 0 | 0 | 0 | 0 |

Totals: {"anthropic": 0, "openai": 58, "google": 256, "xai": 0}. Flags are computed from `source_date` with
`schema_check.DEVELOPER_CUTOFFS` at build time; rebuild to recompute against a frozen panel.

## Contamination protocol note (OUTSIDE_CHECKS §1 date-split)

- After the OpenAI cutoff (2025-12-01): the 58 AIME 2026 + HMMT Feb 2026 items. After the Google cutoff (2025-01-01):
  all 256 items from 2025-2026 contests (MATH items are all pre-cutoff). Nothing is after the Anthropic or xAI cutoffs.
- Twin set for the ConStat-style test (run by the analysis lead, not here): the pre-cutoff items from the same contest
  families, i.e. AIME 1983-2025 (908 items) and HMMT Feb 2023-2025 + Nov 2025
  (114 items), matched to the post-cutoff AIME 2026 / HMMT Feb 2026 items by `strata.problem_number`
  (difficulty proxy) and `strata.topic` where present.

## Top-up source: Hendrycks MATH, test split, Level 5

| source | URL | licence | date | universe (test, Level 5) | verified | excluded by rule | sampled |
|---|---|---|---|---|---|---|---|
| hendrycks MATH test L5, read from `qwedsacf/competition_math` (original) and `EleutherAI/hendrycks_math` (mirror) | https://huggingface.co/datasets/qwedsacf/competition_math ; https://huggingface.co/datasets/EleutherAI/hendrycks_math | MIT (github.com/hendrycks/math LICENSE; both HF cards say `mit`) | 2021-03-05 (arXiv 2103.03874 v1; published 2021-03, day = arXiv v1) | 1324 | 1167 | figure_reference=132, boxed_count_not_one=24, duplicate_of_existing_pool=1, no_match/ambiguous/answer_mismatch/solution_mismatch=0 | 795 |

- **Which copies.** The coordinator named `hendrycks/competition_math` (data/MATH.zip) as copy (a); that HF repo is
  `disabled: true` (401 on download) and the authors' Berkeley tarball returned 504, so copy (a) is
  `qwedsacf/competition_math`, the copy the authors' GitHub README (github.com/hendrycks/math) now links as the
  official download. It is one 12,500-row `train` split (train+test, no split column, columns problem/level/type/
  solution), so test membership and per-row ids come from the mirror: `source_id` = `<subject>/<row index in the
  EleutherAI test split>`; the qwedsacf row index is stored in `evidence.original_row`. The MATH.zip per-file JSON
  names requested for `source_id` are therefore not available.
- **Rehosting note.** AoPS filed a DMCA claim against some HF copies of MATH in 2024 (the original HF repo is disabled
  for that reason). In any public release of this pool, MATH item text is referenced (source + source_id), not
  rehosted.
- **Verification** (`verification.method` = "two-mirror transcription check of a human-written boxed answer
  (qwedsacf/competition_math vs EleutherAI/hendrycks_math; not two independent keyings)"): for each Level-5 test
  problem in the mirror, the original row is found by exact whitespace-normalised problem text (every one of the
  1324 matched exactly one original row: no_match = 0, ambiguous = 0); the final `\boxed{...}` is extracted from the
  human `solution` field of both copies with a brace-balanced parser (`add_math_level5.extract_boxed`); verified only
  if exactly one `\boxed` in each copy, the two boxed strings are identical after whitespace normalisation, and the
  two solution texts are identical after whitespace normalisation. Evidence per item: boxed_answer_original,
  boxed_answer_mirror, solution_sha256, subject, level, original_row, mirror_row. Results: 1167 verified;
  24 excluded for boxed count != 1; 0 answer mismatches; 0 solution mismatches (the two copies are
  content-identical on every matched row, so this check establishes transcription integrity only, not an
  independent keying). `test_boxed_check_can_fail` shows the comparison fails on a mutated boxed answer, an extra
  `\boxed`, and an edited solution.
- **Mechanical exclusions** (fixed before results): `[asy]` / figure / diagram / "shown" / includegraphics / picture
  references -> 132; zero or multiple `\boxed` -> 24; whitespace-normalised duplicate of an existing
  pool item -> 1 (`intermediate_algebra/406`); duplicates inside MATH -> 0. Boxed strings containing
  "or"/"and"/"," are kept whole as the key (never split). `key_type` = integer if the key matches `-?\d+`
  (438 items), else expression (353).
- **Sampling.** 795 = 2000 - 1205 needed; proportional allocation over the 7 subjects from the verified universe with
  largest remainders, `random.Random(20261025).sample` inside each subject (rows sorted by source_id first), then a
  seeded shuffle of the 795 before ids M1210..M2004. Verified per subject -> sampled: algebra 285 -> 194, counting_and_probability 112 -> 76, geometry 81 -> 55, intermediate_algebra 264 -> 180, number_theory 151 -> 103, prealgebra 152 -> 104, precalculus 122 -> 83.
- **Strata**: category `MATH`; strata {contest: "MATH", year: null, subject, level: 5, difficulty_proxy: 5}.
- **Cutoff status**: `source_date` 2021-03-05 is before every developer cutoff, so `post_cutoff` and all
  `post_cutoff_by_developer` flags are false for the 795 items. MATH is pre-cutoff and very widely exposed (it is a
  standard training/eval set), so the date-split contamination check (OUTSIDE_CHECKS §1) cannot be applied to it;
  the twin-set regression run by the analysis lead is the only contamination check for this layer.

## Counts per contest (base layer)

| contest | n |
|---|---|
| AIME 1983 | 10 |
| AIME 1984 | 13 |
| AIME 1985 | 12 |
| AIME 1986 | 14 |
| AIME 1987 | 11 |
| AIME 1988 | 10 |
| AIME 1989 | 9 |
| AIME 1990 | 11 |
| AIME 1991 | 10 |
| AIME 1992 | 13 |
| AIME 1993 | 13 |
| AIME 1994 | 7 |
| AIME 1995 | 12 |
| AIME 1996 | 14 |
| AIME 1997 | 13 |
| AIME 1998 | 15 |
| AIME 1999 | 13 |
| AIME 2000 I | 14 |
| AIME 2000 II | 12 |
| AIME 2001 I | 15 |
| AIME 2001 II | 15 |
| AIME 2002 I | 12 |
| AIME 2002 II | 13 |
| AIME 2003 I | 14 |
| AIME 2003 II | 14 |
| AIME 2004 I | 14 |
| AIME 2004 II | 14 |
| AIME 2005 I | 14 |
| AIME 2005 II | 15 |
| AIME 2006 I | 11 |
| AIME 2006 II | 13 |
| AIME 2007 I | 14 |
| AIME 2007 II | 12 |
| AIME 2008 I | 14 |
| AIME 2008 II | 13 |
| AIME 2009 I | 15 |
| AIME 2009 II | 14 |
| AIME 2010 I | 15 |
| AIME 2010 II | 13 |
| AIME 2011 I | 14 |
| AIME 2011 II | 15 |
| AIME 2012 I | 12 |
| AIME 2012 II | 14 |
| AIME 2013 I | 12 |
| AIME 2013 II | 15 |
| AIME 2014 I | 13 |
| AIME 2014 II | 14 |
| AIME 2015 I | 12 |
| AIME 2015 II | 13 |
| AIME 2016 I | 14 |
| AIME 2016 II | 14 |
| AIME 2017 I | 14 |
| AIME 2017 II | 14 |
| AIME 2018 I | 14 |
| AIME 2018 II | 14 |
| AIME 2019 I | 15 |
| AIME 2019 II | 15 |
| AIME 2020 I | 15 |
| AIME 2020 II | 15 |
| AIME 2021 I | 14 |
| AIME 2021 II | 14 |
| AIME 2022 I | 14 |
| AIME 2022 II | 12 |
| AIME 2023 I | 13 |
| AIME 2023 II | 12 |
| AIME 2024 I | 12 |
| AIME 2024 II | 14 |
| AIME 2025 I | 13 |
| AIME 2025 II | 12 |
| AIME 2026 I | 14 |
| AIME 2026 II | 14 |
| APEX 2025 | 9 |
| BRUMO 2025 | 29 |
| CMIMC 2025 | 36 |
| HMMT Feb 2023 | 29 |
| HMMT Feb 2024 | 28 |
| HMMT Feb 2025 | 29 |
| HMMT Feb 2026 | 30 |
| HMMT Nov 2025 | 28 |
| SMT 2025 | 51 |

## Strata

`category` = contest family (AIME, HMMT, BRUMO, CMIMC, SMT, APEX). `strata` = {contest, year, problem_number,
topic (MathArena `problem_type` list or null), difficulty_proxy (= problem number within the contest/round),
apex_source (APEX only)}. For AIME 2025/2026 MathArena's `problem_idx` 1-15 is AIME I and 16-30 is AIME II
(checked for 2025 by text match against the per-exam opencompass/yentinglin splits; assumed for 2026).

## Counts for the top-up layer

MATH Level 5: 795 items (algebra 194, counting_and_probability 76, geometry 55, intermediate_algebra 180, number_theory 103, prealgebra 104, precalculus 83).

## Not done inside the timebox

- SMT 2025 answer PDFs were not found online (sumo.stanford.edu lists 2011 only; stanfordmathtournament.com/competitions/smt-2025 is 404); the 51 SMT items are single-source.
- HMMT archive items from other years were not transcribed (PDF-only source).
- The 2025 AIME I day (Feb 5 vs Feb 6) and the 2023/2022 AIME days were not confirmed against maa.org (403).
