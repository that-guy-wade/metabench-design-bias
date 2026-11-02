"""Builder 5 (2026-10-26): the math precompute's memory is bounded.

The math precompute was SIGTERM'd by the box memory manager at 29.1 GB RSS after 78,500 of 170,000 rows.  Cause: the
grader's sympy fallback.  (A) sympy memoises Integer/Rational/Pow construction in 1,000-entry LRU caches whose entries
can be arbitrarily large, so every big integer a model answer produced (2^{50000000} is 6 MB) stayed resident.
(B) a power tower such as 10^{10^{10}} is evaluated eagerly: hours of CPU on the event-loop thread and gigabytes.
Fix: clear sympy's caches after every comparison; refuse to evaluate anything estimated above MAX_EVAL_BITS.
Offline: fake provider methods under the real LLM.chat loop (tests/_memprobe.py); no key file, no network."""
import asyncio
import gc
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import _memprobe as M  # noqa: E402
from metabench import graders, panel  # noqa: E402
from metabench.llm import ModelSpec  # noqa: E402

ROW_KEYS = {"item", "model", "sample", "pred", "correct", "parsed", "grade", "grade_error", "grade_s", "in", "out", "stop", "text_tail"}


def _rss_mb() -> float:
    return int(open("/proc/self/statm").read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6


def test_precompute_rss_bounded_over_51k_long_math_rows(tmp_path):
    """600 items x 17 configurations x 5 samples = 51,000 rows, 5,000-10,000-token responses, 5% retryable errors,
    0.3% of answers a large power (about 150 of them): peak RSS under 1 GB and growth after the first 10% of rows
    under 250 MB.  Pre-fix (2026-10-26, this box): peak 1,2xx MB, growth about 1 GB (see docs/BUILD5_REPORT.md)."""
    out = tmp_path / "precompute.jsonl"
    r = M.run_probe(600, 5, 96, out, level="fake", error_rate=0.05, big_rate=0.003, every_s=1.0)
    assert r["rows"] == 51_000
    samples = r["samples"]
    at_10pct = next(m for _, n, m in samples if n >= 5_100)
    peak = max(m for _, _, m in samples)
    print({"maxrss_mb": r["maxrss_mb"], "rss_at_10pct_mb": at_10pct, "peak_sampled_mb": peak, "elapsed_s": r["elapsed_s"],
           "api_errors_total": r["api_errors_total"], "counts": r["counts"]})
    assert r["maxrss_mb"] < 1_000, r["maxrss_mb"]
    assert peak - at_10pct < 250, (at_10pct, peak)
    # output schema and resume bookkeeping unchanged
    rows = [json.loads(l) for l in open(out)]
    assert all(set(x) == ROW_KEYS for x in rows if "error" not in x)
    assert len({(x["item"], x["model"], x["sample"]) for x in rows}) == 51_000


def test_precompute_resume_skips_done_triples_and_keeps_existing_rows(tmp_path):
    specs = [ModelSpec("a", "openai", "m1", "low", 2048, "openai"), ModelSpec("b", "google", "m2", "low", 2048, "google")]
    pool = M.synthetic_math_pool(10)
    out = tmp_path / "pc.jsonl"
    saved = M.llm_mod.asyncio
    M.llm_mod.asyncio = M._fast_asyncio()
    try:
        llm = M.make_llm("fake", 0.0, None)
        llm.bind_pool(pool)
        asyncio.run(panel.precompute(pool, specs, 2, out, llm, concurrency=8, max_tokens=4096))
        lines = out.read_text().splitlines()
        assert len(lines) == 40
        kept = lines[::2]                     # simulate a crash half way: keep every other row
        out.write_text("\n".join(kept) + "\n")
        llm2 = M.make_llm("fake", 0.0, None)
        llm2.bind_pool(pool)
        counts = asyncio.run(panel.precompute(pool, specs, 2, out, llm2, concurrency=8, max_tokens=4096))
    finally:
        M.llm_mod.asyncio = saved
    lines2 = out.read_text().splitlines()
    assert lines2[: len(kept)] == kept                       # existing rows byte-identical
    assert len(lines2) == 40 and llm2.totals["calls"] == 20   # only the missing triples were re-run
    triples = [(r["item"], r["model"], r["sample"]) for r in map(json.loads, lines2)]
    assert len(set(triples)) == 40


def test_sympy_caches_do_not_retain_large_integers():
    """Ten distinct 6-7 MB integers graded in a row: resident memory must not grow by their size (pre-fix: +140 MB)."""
    graders.grade_math({"id": "x", "key_type": "integer", "answer": "7"}, "Answer: 2^{50000000}")
    gc.collect()
    before = _rss_mb()
    for i in range(10):
        graders.grade_math({"id": "x", "key_type": "integer", "answer": str(100 + i)}, f"Answer: 2^{{{50_500_000 + 500_000 * i}}}")
    gc.collect()
    growth = _rss_mb() - before
    assert growth < 40, growth


def test_magnitude_guard_bounds_power_towers_and_leaves_ordinary_verdicts_alone():
    key = {"id": "x", "key_type": "expression", "answer": "\\frac{5}{16}"}
    for tower in ("10^{10^{10}}", "9^{9^{9}}", "3^{3^{3^{3}}}", "2^{2^{100}}", "(10^{100})!", "\\binom{10^{20}}{10^{19}}"):
        t0 = time.time()
        g = graders.grade_math(key, "Answer: " + tower)
        assert (g.correct, g.parsed, g.method) == (0, 1, "mismatch"), tower
        assert time.time() - t0 < 2.0, tower
    # unchanged verdicts: exact, int, sympy (numeric, set, equation), parse failure, and large-but-legitimate equivalences
    assert graders.grade_math(key, "Answer: 0.3125").method == "sympy"
    assert graders.grade_math(key, "Answer: \\frac{10}{32}").method == "sympy"
    assert graders.grade_math(key, "Answer: \\frac{3}{16}").method == "mismatch"
    assert graders.grade_math(key, "No final answer.").method == "parse_fail"
    big = {"id": "y", "key_type": "expression", "answer": "2024^{4046}"}          # the pool's largest key (45 kbit)
    assert graders.grade_math(big, "Answer: (2024^{2023})^{2}").method == "sympy"
    assert graders.grade_math(big, "Answer: 2024^{4046}").method == "exact"
    mil = {"id": "z", "key_type": "expression", "answer": "2^{1000000}"}            # 1 Mbit: below MAX_EVAL_BITS, still evaluated
    assert graders.grade_math(mil, "Answer: 4^{500000}").method == "sympy"
    assert graders.grade_math(mil, "Answer: 4^{500001}").method == "mismatch"
    assert graders.grade_math({"id": "i", "key_type": "integer", "answer": "180"}, "Answer: 2^{99}+1").method == "mismatch"
    assert graders.grade_math({"id": "i", "key_type": "integer", "answer": "180"}, "Answer: 180.0").method == "sympy"
