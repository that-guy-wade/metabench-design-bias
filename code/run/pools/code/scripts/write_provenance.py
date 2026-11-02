"""Generate pools/code/PROVENANCE.md from the build artefacts (extract_stats.json, verify_log.jsonl, build_stats.json,
pilot_log.jsonl). Re-runnable; numbers are never typed by hand."""
from __future__ import annotations
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build  # noqa: E402
import sandbox  # noqa: E402


def main() -> None:
    ex = json.load(open(build.WORK / "extract_stats.json"))
    bs = json.load(open(build.OUT / "build_stats.json"))
    recs = [json.loads(l) for l in open(build.VERIFY_LOG)]
    pilot = [json.loads(l) for l in open(build.WORK / "pilot_log.jsonl")]
    n_cand = ex["candidates"]
    cand_platforms = Counter(json.loads(l)["platform"] for l in open(build.CANDIDATES))
    attempts = Counter(a["outcome"] for r in recs for a in r["attempts"])
    reasons = Counter(r["reason"] for r in recs if not r["verified"])
    tried = Counter(len(r["attempts"]) for r in recs)
    walls = [r["wall_s"] for r in recs]
    inc = [r["evidence"]["incorrect_solution"] for r in recs if r["verified"] and r["evidence"]["incorrect_solution"]]
    inc_failed = sum(1 for x in inc if x["n_failed"] > 0)
    shards = [p.name for p in build.shard_files()]
    items = [json.loads(l) for l in open(build.OUT / "pool.jsonl")]
    n_tests = Counter(len(it["tests"]) for it in items)
    pool_mb = (build.OUT / "pool.jsonl").stat().st_size / 1e6
    rows = lambda prefix: "\n".join(f"| {k[len(prefix):]} | {v} |" for k, v in sorted(bs.items()) if k.startswith(prefix))  # noqa: E731
    exrows = "\n".join(f"| {k[len('excluded:'):]} | {v} |" for k, v in sorted(ex.items()) if k.startswith("excluded:"))
    per_s = len(recs) / sum(walls) * build.WORKERS
    text = f"""# Code pool provenance (MetaBench main study, Pool Author, 2026-10-25)

## Source
- Dataset: `deepmind/code_contests` on HuggingFace ({build.HF_URL}), revision `main`
  (lastModified 2023-06-11 per the HF API). Shards used: `test` (165 rows), `valid` (117 rows) and the first
  {len(shards) - 2} of 39 `train` shards ({', '.join(s.split('-')[0] + '-' + s.split('-')[1] for s in shards)}),
  downloaded by `scripts/download.sh` into `pools/_work/code/parquet/` ({ex['rows']} rows read). The remaining train
  shards were not downloaded because the first {len(shards) - 2} gave enough candidates.
- Licence (dataset card, read 2026-10-25): CC BY 4.0 for the dataset; Codeforces materials are sourced from
  codeforces.com; Description2Code materials (CodeChef, Codeforces, HackerEarth) are MIT; CodeNet materials
  (AtCoder, Aizu) are Apache 2.0. Items carry `licence = "{build.LICENCE}"`.
- Enums (dataset card): `source` 0 UNKNOWN_SOURCE, 1 CODECHEF, 2 CODEFORCES, 3 HACKEREARTH, 4 CODEJAM, 5 ATCODER,
  6 AIZU (note: the task brief listed 4 AIZU / 5 ATCODER; the card says 4 CODEJAM / 5 ATCODER / 6 AIZU and the card
  was used). `difficulty` 0 UNKNOWN_DIFFICULTY, 1 EASY, 2 MEDIUM, 3 HARD, 4 HARDER, 5 HARDEST, 6 EXTERNAL,
  7..28 = A..V (per-contest problem index; non-comparable across platforms, `cf_rating` is the better measure for
  Codeforces). `solutions.language` 0 UNKNOWN, 1 PYTHON (Python 2), 2 CPP, 3 PYTHON3, 4 JAVA.
- Dates: Codeforces items are dated from the contest `startTimeSeconds` in the public Codeforces API
  (`contest.list?gym=false`, fetched 2026-10-25 into `pools/_work/code/cf_contest_list.json`;
  {bs['dated_from_codeforces_contest_list']} items dated this way). Every other item carries `source_date =
  {build.DEFAULT_DATE}`: code_contests / AlphaCode was published 2022-02 (arXiv 2203.07814, dataset created
  2022-07-19 on HF) and every problem predates it; the exact contest day is not derivable from the dataset for
  CodeChef, HackerEarth, AtCoder and Aizu.
- `source_url`: `https://codeforces.com/problemset/problem/<contest>/<index>` for Codeforces items, else the HF
  dataset URL. `source_id` = the dataset `name` field; `source` = `deepmind/code_contests:<split>`.

## Blinding
No model was run on any item and no model output was read. No LLM generated, selected, rewrote, ranked or answered
anything. The only judgement calls are the mechanical rules below, fixed before any verification ran. Selection is
seeded random (seed {build.SEED}) and stratified by (platform, difficulty band).

## Candidate rules (mechanical; `scripts/build.py extract`)
A row is a candidate iff, in this order: it has >= 1 PYTHON3 (language 3) correct solution; `input_file` and
`output_file` are empty (stdin/stdout); description <= {build.MAX_DESC_CHARS} chars and non-empty; the lower-cased
description contains none of {list(build.EXCLUDE_PHRASES)} (the first four need a checker; `<image>`/`figure`
reference a picture; "figure" also matches "figure out", which is accepted as a mechanical cost); it has >= {build.MIN_TESTS}
tests in total and >= {build.MIN_TESTS} tests of size <= {build.MAX_TEST_BYTES} bytes (input+output; larger tests are left out of
the sampling frame to bound pool size); its `name` and its whitespace-normalised description were not seen earlier
in the shard order (test, valid, train-00000, ...).

| exclusion reason | rows |
|---|---|
{exrows}

Rows read: {ex['rows']}; candidates: {n_cand}; candidates by platform: {dict(cand_platforms)}. CODECHEF and
HACKEREARTH rows (and CODEJAM, absent from the shards read) carry no PYTHON3 solutions at all in the shards read (their
solutions come from Description2Code and are Python 2 / C++ / Java), so the first rule removes every one of them; the
pool therefore covers Codeforces, AtCoder and Aizu only.

Per candidate (seeded `random.Random(f"{{SEED}}:{{split}}:{{name}}")`): tests = all public tests (seeded subsample if more
than {build.MAX_TESTS}) plus a seeded sample of private+generated tests up to {build.MAX_TESTS} in total; PYTHON3 correct
solutions seeded-shuffled and the first {build.MAX_SOLUTIONS_TRIED} kept to try; one seeded-random PYTHON3 incorrect solution
kept (informational). Difficulty band: Codeforces with `cf_rating` -> {[b for _, b in build.CF_BANDS]};
otherwise the `difficulty` enum name.

## Ordering (`build.ordered_candidates`)
Candidates grouped by (platform, band); strata order and each stratum's internal order shuffled with
`random.Random({build.SEED})`; the processing order is a round-robin over strata (balanced, not proportional).
Verification runs in that order with {build.WORKERS} worker processes (`multiprocessing.Pool.imap`, ordered) and stops
once {build.TARGET} items are verified, so the pool is "the first {build.TARGET} verified candidates in the fixed order".
Ids C0001.. are assigned after a `random.Random({build.SEED}).shuffle` of the verified records.

## Sandbox (`scripts/sandbox.py`, `scripts/sbx_driver.py`)
{sandbox.SANDBOX_DESCRIPTION}
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
- Candidates in the fixed order: {n_cand}; processed before reaching the target: {len(recs)}; verified:
  {sum(r['verified'] for r in recs)}; excluded during verification: {sum(not r['verified'] for r in recs)}.
- Exclusion reasons: {dict(reasons)}.
- Solution attempts by outcome: {dict(attempts)}; solutions tried per problem: {dict(sorted(tried.items()))}.
- Incorrect solutions run: {len(inc)}; of which failed >= 1 of the tests they ran: {inc_failed} (the rest passed every
  stored test; informational, the stored tests are a <= {build.MAX_TESTS}-test subset).
- Pool: {bs['items']} items, {pool_mb:.1f} MB; tests per item: {dict(sorted(n_tests.items()))}.

| platform | items |
|---|---|
{rows('platform:')}

| difficulty band | items |
|---|---|
{rows('band:')}

| platform:difficulty enum | items |
|---|---|
{rows('difficulty:')}

| split | items |
|---|---|
{rows('split:')}

## Throughput
Pilot ({len(pilot)} items, {build.WORKERS} workers): {sum(r['verified'] for r in pilot)} verified, median wall per item
{statistics.median(r['wall_s'] for r in pilot):.1f} s. Full run: {len(recs)} candidates processed, per-item wall median
{statistics.median(walls):.1f} s, mean {statistics.mean(walls):.1f} s, max {max(walls):.1f} s; aggregate about {per_s:.2f} items/s
with {build.WORKERS} workers on a box whose other 7 cores were busy (see the run's `verify.log` for elapsed time).
Per-item wall is dominated by interpreter start-ups (about 17 ms each; up to {build.MAX_TESTS} tests x 3-4 suites).

## Contamination note
Every item is pre-cutoff for every developer in `schema_check.DEVELOPER_CUTOFFS` (`post_cutoff` is false
everywhere; the newest Codeforces contest date is {max((it['source_date'] for it in items if it['source_date'] != build.DEFAULT_DATE), default='n/a')}; all other items carry {build.DEFAULT_DATE}). code_contests is a well-known
training set (AlphaCode fine-tuning data, public since 2022), so memorisation is plausible for all items. The
OUTSIDE_CHECKS section 1 twin-set protocol must be run by the analysis lead; this pool does not attempt it.

## Re-verification
`scripts/rerun_sample.py` re-executes 25 seeded-random items (reference, empty and print(0)) in the same sandbox and
asserts the stored evidence still holds. Timeouts are the only non-deterministic verdicts (wall-clock under load);
`max_runtime_s` per item is stored so slow references can be identified.

## Re-run
```
scripts/download.sh {len(shards) - 2}
.venv/bin/python -I pools/code/scripts/build.py extract
.venv/bin/python -I pools/code/scripts/build.py pilot --n 20
.venv/bin/python -I pools/code/scripts/build.py verify
.venv/bin/python -I pools/code/scripts/build.py assemble
.venv/bin/python -I pools/code/scripts/write_provenance.py
.venv/bin/python -I pools/code/scripts/rerun_sample.py
```
"""
    (build.OUT / "PROVENANCE.md").write_text(text)
    print(f"wrote {build.OUT / 'PROVENANCE.md'} ({len(text)} chars)")


if __name__ == "__main__":
    main()
