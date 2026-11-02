# Held-out domain pool: clinical medicine (MedQA USMLE, 4-option)

Built 2026-10-25 by the Pool Author role. 1,000 items, ids `H0001..H1000`, domain `clinical_medicine`.
Purpose: the held-out *domain* pool for replication (BLINDING.md §6). Distinct from the three main-study
constructs (math, code, factual QA) and from the pilot pool (MMLU-Pro non-math; MMLU-Pro has a `health`
category but no MedQA items, and no item text is shared: the pilot pool is MMLU-Pro `test` rows only).

## Source
| source | URL | licence | date | rows |
|---|---|---|---|---|
| GBaker/MedQA-USMLE-4-options, split `test` | https://huggingface.co/datasets/GBaker/MedQA-USMLE-4-options | CC-BY-4.0 (HF card); the original MedQA release (github.com/jind11/MedQA, Jin et al. 2020, arXiv:2009.13081) is MIT | 2020-09-28 (arXiv v1 of the paper; the questions are USMLE-style items from professional question banks compiled before that) | 1,273 |
| bigbio/med_qa `med_qa_en_4options_source`, split `test` (official 4-option release, mirror) | https://huggingface.co/datasets/bigbio/med_qa | card says `unknown`; upstream MIT | same | 1,273 |
| bigbio/med_qa `med_qa_en_source`, split `test` (official 5-option release, mirror) | same | same | same | 1,273 |

Keys were written by the question-bank authors (human); no model produced or filtered any key.

## Eligibility and mechanical exclusion rules (fixed before running)
Exclude when: the 4-option record does not have exactly options A–D; the key letter's option text differs
from the record's answer text; the question is missing from the official 4-option mirror, or its answer text
or option set differs there; the answer text is missing from the official 5-option release for the same
question, or the 4-option set is not a subset of the 5-option set; duplicate option texts; duplicate question
text (keep first). Result: **0 exclusions; 1,273 / 1,273 verified** (`build_summary.json`).

## Verification method and evidence
`verification.method`: three-way cross-source agreement (see above). `verification.evidence` per item:
the answer text, `sources_agreeing: 3`, the two bigbio config names. The schema test re-verifies every
pool item against the official 4-option mirror at test time and runs a negative control (shifting every
key letter by one must break agreement for every item), so the check is shown to be able to fail.

## Sampling
Seeded stratified random sample, seed `20261025` (`random.Random`), strata = USMLE step (`meta_info`:
`step1` 679 verified, `step2&3` 594 verified), proportional allocation with largest remainders:
`step1` 533, `step2&3` 467. Rows sorted by source index before shuffling so the draw is reproducible.
Ids assigned after a final seeded shuffle so id order carries no stratum signal.
Script: `scripts/build_heldout_pool.py` (deterministic; re-run reproduces `pool.jsonl` byte-for-byte).

## Cutoff status
`source_date` 2020-09-28 is before every documented cutoff in `pools/SCHEMA.md`; `post_cutoff` is false for
all four developers. Contamination: OUTSIDE_CHECKS.md §1 applies (ConStat-style twin-set regression run by
the analysis lead before unblinding; MedQA is a widely used public benchmark and should be assumed exposed).
This pool is used only for arm *contrasts* on the same items, where contamination is constant across arms.

## Rejected alternatives for the held-out domain
- GPQA (Idavidrein/gpqa): 448 items, below the 1,000 target; gated.
- MMLU-Pro any category: pilot domain, excluded by PREREGISTRATION §5.
- ARC-Challenge: grade-school science, saturated; weak discrimination among frontier panel models.
- LogiQA 2.0: CC BY-NC-SA and exam-translation provenance; not pursued given MedQA met every criterion.
- Lichess puzzles: keys are engine-generated (a model produced them).
