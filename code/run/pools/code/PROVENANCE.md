# Code pool provenance (MetaBench main study, Pool Author, 2026-10-25)

## Source
- Dataset: `deepmind/code_contests` on HuggingFace (https://huggingface.co/datasets/deepmind/code_contests), revision `main`
  (lastModified 2023-06-11 per the HF API). Shards used: `test` (165 rows), `valid` (117 rows) and the first
  26 of 39 `train` shards (test-00000, valid-00000, train-00000, train-00001, train-00002, train-00003, train-00004, train-00005, train-00006, train-00007, train-00008, train-00009, train-00010, train-00011, train-00012, train-00013, train-00014, train-00015, train-00016, train-00017, train-00018, train-00019, train-00020, train-00021, train-00022, train-00023, train-00024, train-00025),
  downloaded by `scripts/download.sh` into `pools/_work/code/parquet/` (9174 rows read). The remaining train
  shards were not downloaded because the first 26 gave enough candidates.
- Licence (dataset card, read 2026-10-25): CC BY 4.0 for the dataset; Codeforces materials are sourced from
  codeforces.com; Description2Code materials (CodeChef, Codeforces, HackerEarth) are MIT; CodeNet materials
  (AtCoder, Aizu) are Apache 2.0. Items carry `licence = "CC-BY-4.0 (code_contests); problem text © the originating judge"`.
- Enums (dataset card): `source` 0 UNKNOWN_SOURCE, 1 CODECHEF, 2 CODEFORCES, 3 HACKEREARTH, 4 CODEJAM, 5 ATCODER,
  6 AIZU (note: the task brief listed 4 AIZU / 5 ATCODER; the card says 4 CODEJAM / 5 ATCODER / 6 AIZU and the card
  was used). `difficulty` 0 UNKNOWN_DIFFICULTY, 1 EASY, 2 MEDIUM, 3 HARD, 4 HARDER, 5 HARDEST, 6 EXTERNAL,
  7..28 = A..V (per-contest problem index; non-comparable across platforms, `cf_rating` is the better measure for
  Codeforces). `solutions.language` 0 UNKNOWN, 1 PYTHON (Python 2), 2 CPP, 3 PYTHON3, 4 JAVA.
- Dates: Codeforces items are dated from the contest `startTimeSeconds` in the public Codeforces API
  (`contest.list?gym=false`, fetched 2026-10-25 into `pools/_work/code/cf_contest_list.json`;
  1442 items dated this way). Every other item carries `source_date =
  2022-02-01`: code_contests / AlphaCode was published 2022-02 (arXiv 2203.07814, dataset created
  2022-07-19 on HF) and every problem predates it; the exact contest day is not derivable from the dataset for
  CodeChef, HackerEarth, AtCoder and Aizu.
- `source_url`: `https://codeforces.com/problemset/problem/<contest>/<index>` for Codeforces items, else the HF
  dataset URL. `source_id` = the dataset `name` field; `source` = `deepmind/code_contests:<split>`.

## Blinding
No model was run on any item and no model output was read. No LLM generated, selected, rewrote, ranked or answered
anything. The only judgement calls are the mechanical rules below, fixed before any verification ran. Selection is
seeded random (seed 20261025) and stratified by (platform, difficulty band).

## Candidate rules (mechanical; `scripts/build.py extract`)
A row is a candidate iff, in this order: it has >= 1 PYTHON3 (language 3) correct solution; `input_file` and
`output_file` are empty (stdin/stdout); description <= 6000 chars and non-empty; the lower-cased
description contains none of ['interactive', 'special judge', 'multiple correct answers', 'any of them', 'print any', '<image>', 'figure'] (the first four need a checker; `<image>`/`figure`
reference a picture; "figure" also matches "figure out", which is accepted as a mechanical cost); it has >= 3
tests in total and >= 3 tests of size <= 32768 bytes (input+output; larger tests are left out of
the sampling frame to bound pool size); its `name` and its whitespace-normalised description were not seen earlier
in the shard order (test, valid, train-00000, ...).

| exclusion reason | rows |
|---|---|
| description_too_long | 6 |
| duplicate_statement | 140 |
| fewer_than_3_tests | 13 |
| file_io | 3 |
| no_python3_solution | 3537 |
| phrase:<image> | 1060 |
| phrase:any of them | 535 |
| phrase:figure | 72 |
| phrase:interactive | 31 |
| phrase:multiple correct answers | 18 |
| phrase:print any | 151 |

Rows read: 9174; candidates: 3608; candidates by platform: {'CODEFORCES': 2213, 'ATCODER': 752, 'AIZU': 643}. CODECHEF and
HACKEREARTH rows (and CODEJAM, absent from the shards read) carry no PYTHON3 solutions at all in the shards read (their
solutions come from Description2Code and are Python 2 / C++ / Java), so the first rule removes every one of them; the
pool therefore covers Codeforces, AtCoder and Aizu only.

Per candidate (seeded `random.Random(f"{SEED}:{split}:{name}")`): tests = all public tests (seeded subsample if more
than 40) plus a seeded sample of private+generated tests up to 40 in total; PYTHON3 correct
solutions seeded-shuffled and the first 3 kept to try; one seeded-random PYTHON3 incorrect solution
kept (informational). Difficulty band: Codeforces with `cf_rating` -> ['cf<1200', 'cf1200-1599', 'cf1600-1999', 'cf2000-2399', 'cf>=2400'];
otherwise the `difficulty` enum name.

## Ordering (`build.ordered_candidates`)
Candidates grouped by (platform, band); strata order and each stratum's internal order shuffled with
`random.Random(20261025)`; the processing order is a round-robin over strata (balanced, not proportional).
Verification runs in that order with 4 worker processes (`multiprocessing.Pool.imap`, ordered) and stops
once 2000 items are verified, so the pool is "the first 2000 verified candidates in the fixed order".
Ids C0001.. are assigned after a `random.Random(20261025).shuffle` of the verified records.

## Sandbox (`scripts/sandbox.py`, `scripts/sbx_driver.py`)
bwrap --unshare-all --die-with-parent --ro-bind /usr /usr --ro-bind /lib /lib --ro-bind /lib64 /lib64 --ro-bind /bin /bin --proc /proc --dev /dev --tmpfs /tmp (256 MiB) --ro-bind <job dir> /src --dir /tmp/w --chdir /tmp/w /usr/bin/python3 -I /src/sbx_driver.py ...; the in-sandbox driver runs /usr/bin/python3 <solution> per test with stdin from the test input, wall-clock timeout max(2 s, 3 x time_limit), RLIMIT_AS = max(1 GiB, 2 x memory_limit), RLIMIT_FSIZE 32 MiB, no network, system Python 3.12.3.
Output comparison (`sbx_driver.tokens_match`): whitespace tokens, same count; integer-looking tokens compared
exactly as integers; tokens that both parse as finite floats compared with abs/rel tolerance 1e-6; otherwise
exact. Stdout larger than 8 MiB counts as a failure. A test is `timeout` if the wall clock exceeds the limit,
`error` on non-zero exit.

## Verification procedure (`build.verify_one`)
For each candidate: try the kept PYTHON3 solutions in order, stopping a suite at the first non-passing test; the
first solution passing ALL tests is the reference. If none passes the problem is excluded with the first attempt's
failure type. Then the empty program and `print(0)` are run on every test and must each fail at least one. Then the
incorrect solution, if any, is run (stopping at the first failure; informational only). Evidence stored per item:
`n_tests, reference_pass, empty_pass, wrong_pass, solution_sha256, max_runtime_s, timeout_s,
memory_limit_bytes_sandbox, solutions_tried, n_tests_total_in_source, incorrect_solution`.

## Counts
- Candidates in the fixed order: 3608; processed before reaching the target: 2247; verified:
  2000; excluded during verification: 247.
- Exclusion reasons: {'no_passing_solution:wrong_output': 140, 'no_passing_solution:timeout': 15, 'no_passing_solution:runtime_error': 90, 'empty_or_wrong_program_passes_all': 2}.
- Solution attempts by outcome: {'pass': 2002, 'wrong_output': 431, 'timeout': 35, 'runtime_error': 281}; solutions tried per problem: {1: 1937, 2: 118, 3: 192}.
- Incorrect solutions run: 1862; of which failed >= 1 of the tests they ran: 1619 (the rest passed every
  stored test; informational, the stored tests are a <= 40-test subset).
- Pool: 2000 items, 20.9 MB; tests per item: {3: 1, 6: 2, 7: 1, 8: 3, 9: 2, 10: 4, 11: 2, 12: 1, 13: 2, 14: 2, 15: 1, 16: 1, 19: 1, 20: 2, 22: 2, 24: 1, 26: 1, 27: 4, 28: 1, 29: 2, 31: 1, 33: 1, 34: 1, 35: 3, 36: 1, 37: 1, 40: 1956}.

| platform | items |
|---|---|
| AIZU | 270 |
| ATCODER | 288 |
| CODEFORCES | 1442 |

| difficulty band | items |
|---|---|
| A | 5 |
| B | 5 |
| C | 4 |
| D | 2 |
| E | 1 |
| F | 2 |
| G | 2 |
| UNKNOWN_DIFFICULTY | 558 |
| cf1200-1599 | 329 |
| cf1600-1999 | 319 |
| cf2000-2399 | 313 |
| cf<1200 | 328 |
| cf>=2400 | 132 |

| platform:difficulty enum | items |
|---|---|
| AIZU:UNKNOWN_DIFFICULTY | 270 |
| ATCODER:UNKNOWN_DIFFICULTY | 288 |
| CODEFORCES:A | 329 |
| CODEFORCES:B | 315 |
| CODEFORCES:C | 251 |
| CODEFORCES:D | 243 |
| CODEFORCES:E | 185 |
| CODEFORCES:F | 83 |
| CODEFORCES:G | 19 |
| CODEFORCES:H | 5 |
| CODEFORCES:I | 2 |
| CODEFORCES:J | 4 |
| CODEFORCES:K | 2 |
| CODEFORCES:M | 2 |
| CODEFORCES:O | 1 |
| CODEFORCES:S | 1 |

| split | items |
|---|---|
| test | 47 |
| train | 1920 |
| valid | 33 |

## Throughput
Pilot (20 items, 4 workers): 20 verified, median wall per item
3.7 s. Full run: 2247 candidates processed, per-item wall median
2.6 s, mean 3.8 s, max 104.3 s; aggregate about 1.06 items/s
with 4 workers on a box whose other 7 cores were busy (see the run's `verify.log` for elapsed time).
Per-item wall is dominated by interpreter start-ups (about 17 ms each; up to 40 tests x 3-4 suites).

## Contamination note
Every item is pre-cutoff for every developer in `schema_check.DEVELOPER_CUTOFFS` (`post_cutoff` is false
everywhere; the newest Codeforces contest date is 2021-12-27; all other items carry 2022-02-01). code_contests is a well-known
training set (AlphaCode fine-tuning data, public since 2022), so memorisation is plausible for all items. The
OUTSIDE_CHECKS section 1 twin-set protocol must be run by the analysis lead; this pool does not attempt it.

## Re-verification
`scripts/rerun_sample.py` re-executes 25 seeded-random items (reference, empty and print(0)) in the same sandbox and
asserts the stored evidence still holds. Timeouts are the only non-deterministic verdicts (wall-clock under load);
`max_runtime_s` per item is stored so slow references can be identified.

## Re-run
```
scripts/download.sh 26
.venv/bin/python -I pools/code/scripts/build.py extract
.venv/bin/python -I pools/code/scripts/build.py pilot --n 20
.venv/bin/python -I pools/code/scripts/build.py verify
.venv/bin/python -I pools/code/scripts/build.py assemble
.venv/bin/python -I pools/code/scripts/write_provenance.py
.venv/bin/python -I pools/code/scripts/rerun_sample.py
```
