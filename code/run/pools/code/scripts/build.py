"""Deterministic builder for the MetaBench code pool (deepmind/code_contests -> pools/code/pool.jsonl).

Phases (all re-runnable):
  extract   scan the downloaded parquet shards, apply the mechanical candidate rules, write
            pools/_work/code/candidates.jsonl + extract_stats.json
  verify    process candidates in the seeded stratified order with a 4-worker pool, run every program in the
            bwrap sandbox, write pools/_work/code/verify_log.jsonl (stop when TARGET verified)
  assemble  seeded shuffle of verified items -> ids C0001.., write pools/code/pool.jsonl + build_stats.json
  pilot N   verify the first N candidates in order and report throughput (writes nothing persistent)

No model is run anywhere; selection is seeded random (SEED); every judgement is a fixed mechanical rule below.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import multiprocessing as mp
import random
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
RUN = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.append(str(RUN / "pools"))  # append: pools/math must not shadow stdlib math
import sandbox  # noqa: E402
from schema_check import CUTOFF_REFERENCE, DEVELOPER_CUTOFFS, parse_date  # noqa: E402

SEED = 20261025
TARGET = 2000
WORKERS = 4
MAX_TESTS = 40
MAX_TEST_BYTES = 32768          # per test, len(input)+len(output); larger tests are left out of the sampling frame
MIN_TESTS = 3
MAX_DESC_CHARS = 6000
MAX_SOLUTIONS_TRIED = 3
WORK = RUN / "pools" / "_work" / "code"
PARQUET = WORK / "parquet"
OUT = RUN / "pools" / "code"
CANDIDATES = WORK / "candidates.jsonl"
VERIFY_LOG = WORK / "verify_log.jsonl"
HF_URL = "https://huggingface.co/datasets/deepmind/code_contests"
DEFAULT_DATE = "2022-02-01"   # code_contests / AlphaCode published 2022-02; every problem predates it
LICENCE = "CC-BY-4.0 (code_contests); problem text © the originating judge"

# Enums from the dataset card (README.md, read 2026-10-25).
SOURCE_NAMES = {0: "UNKNOWN_SOURCE", 1: "CODECHEF", 2: "CODEFORCES", 3: "HACKEREARTH", 4: "CODEJAM",
                5: "ATCODER", 6: "AIZU"}
DIFFICULTY_NAMES = {0: "UNKNOWN_DIFFICULTY", 1: "EASY", 2: "MEDIUM", 3: "HARD", 4: "HARDER", 5: "HARDEST",
                    6: "EXTERNAL", **{6 + i: ch for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUV", start=1)}}
LANG_PYTHON3 = 3
EXCLUDE_PHRASES = ("interactive", "special judge", "multiple correct answers", "any of them", "print any",
                   "<image>", "figure")
CF_BANDS = [(1200, "cf<1200"), (1600, "cf1200-1599"), (2000, "cf1600-1999"), (2400, "cf2000-2399"),
            (10**9, "cf>=2400")]


def shard_files() -> list[Path]:
    files = sorted(PARQUET.glob("test-*.parquet")) + sorted(PARQUET.glob("valid-*.parquet"))
    return files + sorted(PARQUET.glob("train-*.parquet"))


def split_of(path: Path) -> str:
    return path.name.split("-")[0]


def norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def difficulty_band(platform: str, difficulty: str, cf_rating: int | None) -> str:
    if platform == "CODEFORCES" and cf_rating:
        return next(b for hi, b in CF_BANDS if cf_rating < hi)
    return difficulty


def select_tests(row: dict, rng: random.Random) -> tuple[list[dict], int, int]:
    """All public tests first (seeded subsample if >MAX_TESTS), then a seeded sample of private+generated tests.
    Returns (tests, n_total_tests, n_in_frame)."""
    def pairs(block):
        return [{"input": i, "output": o} for i, o in zip(block["input"], block["output"])]
    pub = pairs(row["public_tests"])
    rest = pairs(row["private_tests"]) + pairs(row["generated_tests"])
    n_total = len(pub) + len(rest)
    fits = lambda t: len(t["input"]) + len(t["output"]) <= MAX_TEST_BYTES  # noqa: E731
    pub, rest = [t for t in pub if fits(t)], [t for t in rest if fits(t)]
    if len(pub) > MAX_TESTS:
        pub = rng.sample(pub, MAX_TESTS)
    k = min(MAX_TESTS - len(pub), len(rest))
    return pub + rng.sample(rest, k), n_total, len(pub) + len(rest)


def extract() -> None:
    stats = Counter()
    seen_names, seen_text = set(), set()
    n_out = 0
    with open(CANDIDATES, "w") as out:
        for path in shard_files():
            split = split_of(path)
            pf = pq.ParquetFile(path)
            for batch in pf.iter_batches(batch_size=16):
                for row in batch.to_pylist():
                    stats["rows"] += 1
                    desc = row["description"] or ""
                    low = desc.lower()
                    rng = random.Random(f"{SEED}:{split}:{row['name']}")
                    py3 = [s for lang, s in zip(row["solutions"]["language"], row["solutions"]["solution"])
                           if lang == LANG_PYTHON3]
                    reason = None
                    if not py3:
                        reason = "no_python3_solution"
                    elif row["input_file"] or row["output_file"]:
                        reason = "file_io"
                    elif len(desc) > MAX_DESC_CHARS:
                        reason = "description_too_long"
                    elif not desc.strip():
                        reason = "empty_description"
                    else:
                        hit = [p for p in EXCLUDE_PHRASES if p in low]
                        if hit:
                            reason = "phrase:" + hit[0]
                    if reason is None:
                        tests, n_total, n_frame = select_tests(row, rng)
                        if n_total < MIN_TESTS:
                            reason = "fewer_than_3_tests"
                        elif n_frame < MIN_TESTS:
                            reason = "fewer_than_3_tests_under_size_cap"
                    if reason is None:
                        if row["name"] in seen_names:
                            reason = "duplicate_name"
                        elif norm_text(desc) in seen_text:
                            reason = "duplicate_statement"
                    if reason is not None:
                        stats["excluded:" + reason] += 1
                        continue
                    seen_names.add(row["name"])
                    seen_text.add(norm_text(desc))
                    rng.shuffle(py3)
                    inc = [s for lang, s in zip(row["incorrect_solutions"]["language"],
                                                row["incorrect_solutions"]["solution"]) if lang == LANG_PYTHON3]
                    rng.shuffle(inc)
                    tl = row["time_limit"]
                    time_limit_s = (tl["seconds"] + tl["nanos"] / 1e9) if tl else 1.0
                    platform = SOURCE_NAMES.get(row["source"], "UNKNOWN_SOURCE")
                    difficulty = DIFFICULTY_NAMES.get(row["difficulty"], "UNKNOWN_DIFFICULTY")
                    cf_rating = int(row["cf_rating"]) if row["cf_rating"] else None
                    cand = {
                        "name": row["name"], "split": split, "description": desc, "platform": platform,
                        "difficulty": difficulty, "band": difficulty_band(platform, difficulty, cf_rating),
                        "cf_contest_id": row["cf_contest_id"] or 0, "cf_index": row["cf_index"] or "",
                        "cf_rating": cf_rating, "cf_tags": list(row["cf_tags"] or []),
                        "time_limit_s": time_limit_s, "time_limit_missing": tl is None,
                        "memory_limit_mb": round(row["memory_limit_bytes"] / 1e6, 3),
                        "memory_limit_bytes": row["memory_limit_bytes"], "tests": tests,
                        "n_tests_total": n_total, "n_tests_in_frame": n_frame,
                        "n_python3_solutions": len(py3), "solutions": py3[:MAX_SOLUTIONS_TRIED],
                        "incorrect_solution": inc[0] if inc else None,
                    }
                    out.write(json.dumps(cand) + "\n")
                    n_out += 1
                    stats["candidates"] += 1
            print(f"{path.name}: rows so far {stats['rows']}, candidates {n_out}", flush=True)
    (WORK / "extract_stats.json").write_text(json.dumps(dict(stats), indent=1, sort_keys=True))
    print(json.dumps(dict(stats), indent=1, sort_keys=True))


def ordered_candidates() -> list[dict]:
    """Seeded stratified ordering: shuffle within each (platform, band) stratum, then round-robin over strata."""
    cands = [json.loads(l) for l in open(CANDIDATES)]
    rng = random.Random(SEED)
    strata = defaultdict(list)
    for c in cands:
        strata[(c["platform"], c["band"])].append(c)
    keys = sorted(strata)
    rng.shuffle(keys)
    for k in keys:
        rng.shuffle(strata[k])
    order = []
    i = 0
    while any(len(strata[k]) > i for k in keys):
        order += [strata[k][i] for k in keys if len(strata[k]) > i]
        i += 1
    return order


def verify_one(c: dict) -> dict:
    timeout = max(2.0, 3.0 * c["time_limit_s"])
    mem = max(1 << 30, 2 * int(c["memory_limit_bytes"] or 0))
    tests = c["tests"]
    attempts = []
    chosen = None
    t0 = time.time()
    for sol in c["solutions"]:
        r = sandbox.run_suite(sol, tests, timeout, mem, "stop")
        if r["driver_error"]:
            attempts.append({"outcome": "driver_error", "detail": r["driver_error"], "n_run": 0})
            continue
        if r["n_pass"] == len(tests):
            attempts.append({"outcome": "pass", "n_run": r["n_run"], "max_time": r["max_time"]})
            chosen = (sol, r)
            break
        first_bad = next(x for x in r["results"] if x["status"] != "pass")
        outcome = {"fail": "wrong_output", "timeout": "timeout", "error": "runtime_error"}[first_bad["status"]]
        attempts.append({"outcome": outcome, "n_run": r["n_run"], "n_pass": r["n_pass"], "max_time": r["max_time"]})
    rec = {"name": c["name"], "split": c["split"], "n_tests": len(tests), "attempts": attempts,
           "wall_s": None}
    if chosen is None:
        rec.update(verified=False, reason="no_passing_solution:" + attempts[0]["outcome"])
        rec["wall_s"] = time.time() - t0
        return rec
    sol, r = chosen
    empty = sandbox.run_suite(sandbox.EMPTY_PROGRAM, tests, timeout, mem, "all")
    wrong = sandbox.run_suite(sandbox.WRONG_PROGRAM, tests, timeout, mem, "all")
    evidence = {
        "n_tests": len(tests), "reference_pass": r["n_pass"], "empty_pass": empty["n_pass"],
        "wrong_pass": wrong["n_pass"], "solution_sha256": hashlib.sha256(sol.encode()).hexdigest(),
        "max_runtime_s": round(r["max_time"], 4), "timeout_s": timeout, "memory_limit_bytes_sandbox": mem,
        "solutions_tried": len(attempts), "n_tests_total_in_source": c["n_tests_total"],
        "incorrect_solution": None,
    }
    if c["incorrect_solution"] is not None:
        inc = sandbox.run_suite(c["incorrect_solution"], tests, timeout, mem, "stop")
        evidence["incorrect_solution"] = {
            "sha256": hashlib.sha256(c["incorrect_solution"].encode()).hexdigest(),
            "n_run": inc["n_run"], "n_failed": inc["n_run"] - inc["n_pass"],
            "driver_error": inc["driver_error"], "note": "run stops at the first failing test",
        }
    ok = (empty["n_pass"] < len(tests) and wrong["n_pass"] < len(tests)
          and not empty["driver_error"] and not wrong["driver_error"])
    rec.update(verified=ok, reason=None if ok else "empty_or_wrong_program_passes_all", evidence=evidence,
               reference_solution=sol)
    rec["wall_s"] = time.time() - t0
    return rec


def verify(limit: int | None, log_path: Path, target: int) -> dict:
    order = ordered_candidates()
    if limit:
        order = order[:limit]
    n_ok = n_done = 0
    t0 = time.time()
    with open(log_path, "w") as log, mp.Pool(WORKERS) as pool:
        for rec in pool.imap(verify_one, order, chunksize=1):
            n_done += 1
            n_ok += rec["verified"]
            log.write(json.dumps(rec) + "\n")
            log.flush()
            if n_done % 50 == 0 or n_done == len(order):
                el = time.time() - t0
                print(f"done {n_done} verified {n_ok} elapsed {el:.0f}s ({n_done / el:.2f} items/s)", flush=True)
            if n_ok >= target:
                break
        pool.terminate()
    el = time.time() - t0
    summary = {"processed": n_done, "verified": n_ok, "elapsed_s": round(el, 1),
               "items_per_s": round(n_done / el, 3), "candidates_total": len(ordered_candidates()) if not limit else None}
    print(json.dumps(summary))
    return summary


def cf_dates() -> dict[int, str]:
    p = WORK / "cf_contest_list.json"
    if not p.exists():
        return {}
    d = json.load(open(p))
    return {c["id"]: datetime.fromtimestamp(c["startTimeSeconds"], timezone.utc).strftime("%Y-%m-%d")
            for c in d["result"] if "startTimeSeconds" in c}


def assemble() -> None:
    cands = {(c["split"], c["name"]): c for c in map(json.loads, open(CANDIDATES))}
    recs = [r for r in map(json.loads, open(VERIFY_LOG)) if r["verified"]]
    dates = cf_dates()
    random.Random(SEED).shuffle(recs)
    stats = Counter()
    n_dated = 0
    with open(OUT / "pool.jsonl", "w") as out:
        for i, r in enumerate(recs, start=1):
            c = cands[(r["split"], r["name"])]
            cf = c["cf_contest_id"]
            date = dates.get(cf, DEFAULT_DATE) if c["platform"] == "CODEFORCES" and cf else DEFAULT_DATE
            n_dated += date != DEFAULT_DATE
            d = parse_date(date)
            url = (f"https://codeforces.com/problemset/problem/{cf}/{c['cf_index']}"
                   if c["platform"] == "CODEFORCES" and cf and c["cf_index"] else HF_URL)
            item = {
                "id": f"C{i:04d}", "domain": "code", "source": f"deepmind/code_contests:{c['split']}",
                "source_id": c["name"], "source_url": url, "licence": LICENCE, "source_date": date,
                "question": c["description"], "options": [], "answer": "tests", "key_type": "tests",
                "category": c["platform"],
                "strata": {"platform": c["platform"], "difficulty": c["difficulty"], "difficulty_band": c["band"],
                           "cf_rating": c["cf_rating"], "tags": c["cf_tags"], "n_tests": r["n_tests"],
                           "split": c["split"]},
                "verification": {"method": "sandboxed execution of a human PYTHON3 solution from code_contests "
                                           "against the stored tests (bwrap, system python3); empty and "
                                           "print(0) programs must fail at least one test",
                                 "verified": True, "evidence": r["evidence"]},
                "post_cutoff": d > CUTOFF_REFERENCE,
                "post_cutoff_by_developer": {dev: d > cut for dev, cut in DEVELOPER_CUTOFFS.items()},
                "tests": c["tests"], "reference_solution": r["reference_solution"], "language": "python3",
                "time_limit_s": c["time_limit_s"], "memory_limit_mb": c["memory_limit_mb"],
            }
            out.write(json.dumps(item, ensure_ascii=False) + "\n")
            stats[f"platform:{c['platform']}"] += 1
            stats[f"difficulty:{c['platform']}:{c['difficulty']}"] += 1
            stats[f"band:{c['band']}"] += 1
            stats[f"split:{c['split']}"] += 1
    stats["items"] = len(recs)
    stats["dated_from_codeforces_contest_list"] = n_dated
    (OUT / "build_stats.json").write_text(json.dumps(dict(stats), indent=1, sort_keys=True))
    print(json.dumps(dict(stats), indent=1, sort_keys=True))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["extract", "verify", "assemble", "pilot"])
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--target", type=int, default=TARGET)
    a = ap.parse_args()
    if a.phase == "extract":
        extract()
    elif a.phase == "pilot":
        verify(a.n, WORK / "pilot_log.jsonl", 10**9)
    elif a.phase == "verify":
        verify(None, VERIFY_LOG, a.target)
    else:
        assemble()
