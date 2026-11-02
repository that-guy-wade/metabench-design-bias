# MetaBench T1: does showing a benchmark-designing model the scoreboard change the benchmark it builds?

MetaBench is a pre-registered, double-blind, randomised factorial experiment. Twelve frontier models from four
developers (Anthropic, OpenAI, Google, xAI) each built 100-item benchmarks by selecting, and optionally editing and
weighting, items from a fixed 2,000-item pool in three domains: factual QA (SimpleQA), competition math and
programming (code_contests). Each designer worked over four rounds of tool use. A tool returned "panel scores" for the
current draft, and what it returned was randomised per benchmark:

- nothing;
- true scores, under real names or pseudonyms;
- a shuffled sham scoreboard (the primary test);
- an inverted scoreboard;
- a narrative naming a leader;
- an instructed-bias positive control, in which a "sponsor" asks the designer to make a named model win.

A fixed 17-entry panel (the 12 designers, an identical-configuration placebo and 4 never-shown held-out models)
answered every pool item 5 times in advance, so every produced benchmark can be scored exactly. Before unblinding,
the primary endpoint Ψ (designer-averaged Fisher-z Kendall τ between the produced ranking and the sham ranking shown),
the secondary endpoints and the controls were fixed in `protocol/PREREGISTRATION.md`. The analysis code was frozen
and hashed (`protocol/prereg/frozen_code.json`). Three independently written implementations (A, B, C) computed the
confirmatory endpoints. The results and their interpretation are in `reports/`. Exploratory analyses and three
follow-up experiments are labelled as exploratory throughout.

## Layout

| path | contents |
|---|---|
| `protocol/` | `PREREGISTRATION.md`, `BLINDING.md`, `SCENARIO.md` (task and tool interface), `POWER.md`, `OUTSIDE_CHECKS.md`, `UNBLINDING.md` (procedure), `DEVIATIONS.md` (every departure from the plan, dated, with whether it was decided before or after outcomes) |
| `protocol/prereg/` | registration hashes: `frozen_code.json`, `frozen_sizes.json`, `pools_hash.json`, `pilot_hashes.json`, per-pool `confirmatory_hashes_<pool>.json` (every session's seed, displayed order, leader, target) and `confirmatory_replacements_<pool>.json`, `sealing_key.json` (public-key fingerprint only), `unblind_summary.json` |
| `code/run/` | the frozen run code: `metabench/` (interface, arms, panel, scoring, monitors, analysis A), `analysis_impls/B` and `analysis_impls/C` (independent implementations), `scripts_*.py` (runner, precompute, unblinding, contamination check, ...), `tests/`, `requirements.txt`, and `pools/` (pool schema, build scripts and `PROVENANCE.md` per pool) |
| `code/exploratory/<analysis>/` | scripts for each post-unblinding exploratory analysis and experiment |
| `data/ARTEFACT_SCHEMA.md` | file layout and every field of the session artefacts |
| `data/confirmatory/<pool>/` | for `factual`, `math`, `code`: `results/` (`benchmarks.jsonl`, one row per session; `item_outcomes.jsonl.gz`; `reference_item_outcomes.jsonl`; `monitors.jsonl`; `session_log.jsonl`), `sessions.tar.gz` (per session: `actions.jsonl`, `benchmark.json`, `config.json`, `item_outcomes.jsonl`, `probes.json`, `scores_views.jsonl`, `transcript.jsonl`), `monitors.tar.gz` (two cross-developer monitor ratings per session), `precompute/<pool>.jsonl.gz` (every panel answer to every pool item: correctness, parsed answer, answer tail), `registration_full.json`, `run_manifest.json`, `endpoints/` (frozen outputs of A, B, C and the contamination check; code also has `endpoints_sealed_order/`, a row-order control) and `pool/` (items or item index, plus provenance) |
| `data/exploratory/<experiment>/` | data for the exploratory work: `capacity`, `controls`, `reconcile`, `sensitivity`, `provenance`, `factual_audit`, `edit_audit`, `second_judges`, and the follow-up experiments `exp_g4a`, `exp_muse`, `exp_covert`, `exp_wording` (each with `sessions.tar.gz`, `rows.jsonl`, `results.json`; judge and monitor outputs where they exist) |
| `reports/` | `REPORT_CONFIRMATORY.md` (mechanical assembly of the frozen outputs, written before any agent saw the data), `ANALYSIS_CONFIRMATORY_2026-10-30.md`, `ANALYSIS_EXPLORATORY_2026-10-30.md`, and `exploratory/<analysis>/` (each analysis's REPORT, FINDINGS and its own PREREG where one was written) |
| `LICENSES_AND_SOURCES.md` | per-source licences and what is and is not redistributed |
| `SCRUB_REPORT.md` | every redaction rule applied to this package, with counts, and the leak-scan result |
| `MANIFEST.tsv` | path, size in bytes and SHA-256 of every file in the package |
| `scan_release.py`, `scan_allowlist.json` | the leak scanner and its reviewed allowlist |
| `restore_layout.py` | recreates the original working layout so the code runs unchanged |

Math item text is not redistributed. See LICENSES_AND_SOURCES.md 1.3: the math pool is listed by id and source
pointer, and in transcripts the item text is replaced by `[math item text withheld]`.

## Reproducing the analyses

Python 3.12 on Linux. Analysis A needs about 11 GB of RAM per pool. No network access or model API keys are needed
for any analysis.

```bash
python restore_layout.py --root "$PWD/restored"      # unpacks archives into the original layout
cd restored/run
uv venv --seed --python 3.12 .venv
.venv/bin/python -m pip install -r requirements.txt

# frozen confirmatory analyses, per pool (factual | math | code), with the confirmatory arguments
W=../unblinded/WORK_math
PYTHONHASHSEED=0 .venv/bin/python -m metabench.analysis --results $W/results --out out/A --n-perm 10000 --n-boot 10000
.venv/bin/python analysis_impls/B/run.py --results $W --out out/B --n-perm 10000 --n-boot 10000
.venv/bin/python analysis_impls/C/run.py --results $W --out out/C --n-perm 10000 --n-boot 10000
# compare with ../unblinded/math/endpoints/{A_metabench_analysis,B,C}/endpoints.json
```

- `PYTHONHASHSEED=0` matters for A only: its interval draws depend on set iteration order. See
  `protocol/UNBLINDING.md`.
- For factual, compare A against `endpoints/A_metabench_analysis_linux`. Apple Accelerate on the Mac used for unblinding crashed A on
  that pool, and A was re-run unchanged on Linux.
- Exploratory scripts read the restored layout. Run each from its directory under `restored/analysis/<name>/`, for
  example `python assemble.py` in `capacity`, `sensitivity` and `provenance`, or the analysis scripts named in each
  REPORT.md. Scripts that call model APIs (`run_exp.py`, judges, raters) are included for completeness. Re-running
  them makes new model calls and needs your own keys.
- Anything that needs math item text (contamination check on math, re-scoring edited math items, the math pool
  schema test) first needs the math pool rebuilt with `run/pools/math/scripts/`. Check it against
  `pool_index.jsonl` (`question_sha256`).

Checks performed while building this package, all run from the restored package:

- Implementation C was re-run on all three pools. Every endpoint value matched the shipped
  `endpoints/C/endpoints.json` exactly. The only differing field was the input directory path.
- Implementation B was re-run on math. All 1,732 fields matched to within 2.3e-10, which is floating-point noise in
  the fallback GLM.
- The exploratory `capacity` scripts `named_sham.py math` and `assemble.py` reproduced their shipped outputs byte for
  byte.
- A was not re-run (about 11 GB of RAM and roughly an hour per pool).

## Licences

Third-party item text keeps its source licence: SimpleQA items MIT, code_contests items CC BY 4.0. Math item text is
withheld. See `LICENSES_AND_SOURCES.md` for attribution and notices. This project's own code is MIT (`LICENSE`); the data
and reports it generated are CC BY 4.0 (`LICENSE-DATA`).

## Known issues (full list: `protocol/DEVIATIONS.md`)

- **Analysis A bugs.** The pre-registered implementation A has three bugs:
  - it ranks 13 entries in some arms and 12 in others;
  - it uses the pilot's reputation tiers for named-arm nulls, so its named-arm Ψ p-values and leader nulls are invalid;
  - it calibrates ability on the full pool only.

  Implementations B and C were written independently, agree with each other and match the plan's wording.
- **Positive control (C1).** The instructed-bias arm failed as pre-registered: its CI includes 0, because several
  designers refused. Splitting out the compliers is post hoc, and the strict verdict is kept.
- **Lost or incomplete sessions.**
  - 50 math benchmarks by Google designers were lost to Google sign-in lapses (after one retry each).
  - An hour of Anthropic credit exhaustion failed 90 code sessions. They were retried and 89 are valid.
  - Some slow xAI panel answers never resolved: 24 math and 163 code.
- **Sealing defect.** Pool-level sealed files overwrote each other. Factual and math results were rebuilt from the
  per-session sealed files at unblinding and checked against the code pool's surviving copies.
- **Factual grader.** Exact text matching is too strict: about 21% of answers marked wrong are right, unevenly by
  model. Comparisons between arms use the same grader everywhere. Re-grade before reusing the factual scores.
- **Contamination.** The pools are not post-cutoff, so contamination is mostly not estimable.
- **Changed frozen file.** `code/run/metabench/llm.py` differs from its hash in `protocol/prereg/frozen_code.json`
  because three lines were scrubbed for release (local file paths only; no logic changed). SCRUB_REPORT.md section 2
  lists the exact lines, so the original hash can be checked. All other frozen files match their registered hashes.
