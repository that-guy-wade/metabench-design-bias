# Unblinding: rebuild per-pool trees, run the frozen analyses, write REPORT_CONFIRMATORY.md

For Seth, on his Mac, after decrypting `run/sealed/` into `~/Downloads/unsealed/` (a mirror of sealed/ without the `.gpg`
suffix, plus `MANIFEST.json`). No network and no model keys are needed for the run itself. Package installation in
step 1 does need network.

**BLINDING.md section 5:** `REPORT_CONFIRMATORY.md` must exist before any agent reads the data. Run this yourself, with no
agent in the loop. Hand the report or the data to an agent only after it has been written.

## Why a rebuild (DEVIATIONS 2026-10-29 17:45)

All three pools sealed into the same `sealed/` directory with the same relative paths. The per-pool paths survived for
every pool: `sessions/T1_<pool>_*`, `monitors/T1_<pool>_*.json` and `precompute/<pool>.jsonl`. The pool-level paths hold
only the last pool sealed, which is code: `results/*`, `registration_full.json`, `run_manifest.json`,
`reference_item_outcomes.jsonl`, `endpoints/`, `health/` and `llm_calls.jsonl`. `scripts_unblind.py` rebuilds each pool's
WORK tree with the runner's own code and the plaintext registration in `prereg/`. It then checks the trees, uses the
code pool as a control, runs the frozen analyses and assembles the report.

## 1. Environment, from a fresh copy of the run/ code

```bash
cd ~/metabench-run            # your copy of run/ (code, pools/, prereg/, analysis_impls/; no sealed data needed here)
uv venv --seed --python 3.12 .venv          # the run used Python 3.12
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip --version           # must print a path inside ~/metabench-run/.venv/...
.venv/bin/python -c "import sys; print(sys.prefix)"   # must print ~/metabench-run/.venv
```

Optional before you run: `.venv/bin/python scripts_freeze.py verify` confirms that the code you copied matches
`prereg/frozen_code.json` (BLINDING.md section 5 step 1). `scripts_unblind.py` itself is not a frozen file.

## 2. Run

```bash
cd ~/metabench-run
.venv/bin/python scripts_unblind.py --unsealed ~/Downloads/unsealed --prereg prereg \
    --out ~/Downloads/unblinded --n-perm 10000 --n-boot 10000 --jobs 2 2>&1 | tee ~/Downloads/unblind_console.txt
```

- `--pools factual,math,code` is the default. The report always uses that order.
- `--n-perm 10000 --n-boot 10000` are the runner's defaults, i.e. the confirmatory arguments.
- Each analysis subprocess gets `PYTHONHASHSEED=0` unless you set it yourself.
  - Why: A (`metabench.analysis`) iterates Python sets of designer keys while drawing from its seeded RNG, for example in
    `self_rank_by_identity`. Its Monte Carlo intervals therefore change from one process to the next with Python's
    string-hash randomisation, even on identical input. On a synthetic tree, two runs differed in 20 keys beyond 1e-6.
  - The runner left the hash seed random and did not record it. With the seed fixed, the recomputed report reproduces:
    reruns agree to within 1e-6.
  - B and C are unaffected.
- `--jobs N` runs N analysis processes at once. With N > 1 each process gets `cpu_count // N` BLAS/OpenMP threads.
  Without that cap, parallel analyses thrash: on synthetic trees A took 30 s alone and over 450 s with 6 in parallel.
- Memory: A peaked near **11 GB** RSS on a full-size pool. Choose `--jobs 1` for 16 GB of RAM, `--jobs 2` for 32 GB and
  `--jobs 4` for 64 GB or more. The runner's 20 GiB address-space cap applies on Linux only; macOS has no usable
  RLIMIT_AS.

### Expected runtime

All figures were measured on the 8-CPU run box (BUILD4_REPORT section 4) and are rough:

| step | time |
|---|---|
| integrity and rebuild | a few minutes; mostly reading the three 170,000-row precompute files and linking the session files |
| A (`metabench.analysis`) | about 25 min per pool, up to about 11 GB |
| B | up to about 32 min per pool; its mixed model has its own 1,800 s bound and falls back to the GLM after that, labelled in its output |
| C | about 3 min per pool |
| contamination | under a minute per pool |

There are 15 analysis runs in all: 4 per pool plus 3 for the code row-order control. Total time is about 3 to 4 h with
`--jobs 1` and about 1.5 to 2 h with `--jobs 2`.

Disk: the session files are hard-linked from `--unsealed` into `--out` when both are on the same volume, and copied
otherwise. Each analysis gets a 4 h timeout, as in the runner.

## 3. What the console prints (counts only, never content)

1. `integrity: N manifest entries, N present with the listed byte count, 0 missing, 0 size mismatches; K files ... not in
   MANIFEST`. Any missing file or size mismatch aborts before anything is rebuilt.
   - K > 0 is not an error. Pools that sealed concurrently each rewrote `MANIFEST.json` from their own in-memory copy, so
     some decrypted files can be absent from it.
   - The report also counts how many of each pool's rebuild inputs are unlisted.
2. Per pool: `<pool>: rebuilt WORK_<pool>: R registered, P replacements, N rows, V valid; registration check passed
   (N/N hashes); W warnings`.
   - The run aborts on any of these: a registered or declared session that is missing, duplicated or undeclared; a
     config hash (config.json or benchmark.json) that differs from the registered one; a pool file that does not match
     the registered sha256; or a broken replacement rule.
   - Warnings do not abort; they are listed in the report:
     - the runner's `make_cfg` does not reproduce a config;
     - a row's reference scores differ from those rebuilt from the precompute;
     - the precompute file differs from the registered `panel_correctness_sha256`;
     - a monitor file is present or absent against the runner's rule.
3. Control lines for the code pool, whose sealed pool-level files are its own:
   - `control results/<file>: identical (N rows; row order same|differs)`. The rebuilt rows and the sealed rows are equal
     as multisets keyed by session id and item. "Row order differs" is expected: the runner appended rows in completion
     order.
   - `control registration_full.json: identical`. Alternatively the line may say the registration differs only in
     `written_at`, which is the one tolerated, content-free reason: a later `register` found the registration unchanged.
   - `control run_manifest.json: identical (... not compared: run_id, started_at, ended_at, concurrency,
     api_errors_total)`. Those fields are wall-clock or process facts. A rebuild cannot know them, and no analysis reads
     them.
   - Anything else stops the script before any analysis runs (`control failed for k files: ...`).
4. `analysis <pool>/endpoints/<name>: rc=0 in Ss` for each run.
5. `control endpoints <name> (registered row order|sealed row order) vs sealed: identical` or
   `k of n keys differ (e run-environment keys: paths/timings; m other keys beyond relative 1e-06)`.
   - **Sealed row order**: the rebuilt code tree with its `results/*.jsonl` rows in the sealed files' order. Expect
     `identical` apart from run-environment keys (B's and C's `results_dir` path, timings).
   - **Registered row order**: the tree whose endpoints the report uses for every pool. A's permutation and bootstrap
     draws follow its input row order, so A's p-values and intervals can differ from the sealed ones by Monte Carlo noise
     only. B and C sort by session id.
   - A's hash-seed dependence (above) means a few of A's interval keys cannot match the sealed run, even in sealed row
     order.
   - Two machine differences can also show up as "other keys". First, a different BLAS (macOS Accelerate/OpenBLAS on
     arm64 vs Linux x86) changes the last digits of fitted values. Second, B's mixed model may finish within its 1,800 s
     bound on one machine and fall back to the GLM on the other. The report shows both the sealed and the recomputed
     code endpoints.

### Row order (why the registered order)

The runner appended each session's rows to `results/*.jsonl` when the session finished, with 16 to 48 sessions in
flight. Only the code pool's completion order survives, in its sealed files. For every pool the rebuild writes the rows
in the registered order (`prereg/confirmatory_hashes_<pool>.json` `sessions`), followed by the replacements in the
order of `prereg/confirmatory_replacements_<pool>.json`. That is the runner's plan order, it does not depend on the
data, and the same rule applies to all pools. Point estimates do not depend on row order. A's Monte Carlo p-values and
intervals do, at the level of their Monte Carlo error.

## 4. Output

- `~/Downloads/unblinded/REPORT_CONFIRMATORY.md`: the report. At the top it states that the math and factual endpoints
  were recomputed at unblinding and that the code endpoints were both sealed and recomputed. Then come integrity, and for
  factual, math and code in that order:
  - the run facts;
  - the registration check;
  - the controls (code);
  - the rc lines;
  - each implementation's `endpoints.md`, or its `endpoints.json` verbatim;
  - the contamination output;
  - for code, the sealed endpoints as well.
- `~/Downloads/unblinded/<pool>/endpoints/<name>/` holds each run's output and `log.txt` (rc, stdout, stderr), as in
  the runner. `code/endpoints_sealed_order/` holds the row-order control.
- `~/Downloads/unblinded/WORK_<pool>/`: the rebuilt trees, for later exploratory work.
- `~/Downloads/unblinded/unblind_summary.json`: every count above in machine-readable form.

The exit code is 0 when every analysis returned rc=0. Otherwise it is 1, and the report is still written.

## 5. Not covered here

- The outage-window sensitivity analysis (DEVIATIONS 2026-10-27 10:40) is not part of this script.
- The 50 Google-designer math sessions that were lost, invalid and not re-run (2026-10-28 16:10) appear only as invalid
  rows in the run facts.
- The precompute error last-rows per provider asked for in DEVIATIONS 2026-10-26 12:58 are in each pool's run facts.
