"""Precompute cost and time estimate per main-study pool at 17 configurations x 2,000 items x 5 samples, measured from a
20-item throwaway slice per pool with every reachable provider (Builder 2, 2026-10-25).

Blinding: the slice outputs (which contain answers and correctness) are written to tmpfs and deleted at the end; the
summary reads ONLY status, token, latency, cost, parse and grader-error fields (`SAFE_FIELDS`), aggregated per model
for tokens/latency/cost and per pool (never per model) for parse failures.  Nothing per item is written anywhere.

usage: .venv/bin/python scripts_precompute_estimate.py [--pools math,code,factual] [--n 20] [--out docs/PRECOMPUTE_ESTIMATE.md]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from metabench import panel  # noqa: E402
from metabench.llm import LLM, load_keys_from_env_file  # noqa: E402
from metabench.pool import load_pool  # noqa: E402

POOL_PATHS = {"math": "pools/math/pool.jsonl", "code": "pools/code/pool.jsonl", "factual": "pools/factual_qa/pool.jsonl"}
FULL = {"items": 2000, "samples": 5}
# the runner's per-provider concurrency (scripts_runner.Runner.make_llm)
PROVIDER_CONCURRENCY = {"anthropic": 40, "openai": 56, "google": 32, "xai": 32}
SAFE_FIELDS = ("model", "in", "out", "stop", "parsed", "error", "grade_error", "grade_s")


def summarise(records: list[dict], calls: list[dict]) -> dict:
    """Per-model token/latency/cost means and per-pool parse-failure counts.  Reads only SAFE_FIELDS of the precompute
    records and the per-call log (tag, in, out, cost, latency); never 'correct' or 'pred'."""
    recs = [{k: r.get(k) for k in SAFE_FIELDS} for r in records]
    per_model: dict[str, dict] = {}
    for c in calls:
        m = c["tag"].split(":", 1)[1] if c["tag"].startswith("panel:") else None
        if not m:
            continue
        d = per_model.setdefault(m, {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "latency": 0.0})
        d["calls"] += 1; d["in"] += c["in"]; d["out"] += c["out"]; d["cost"] += c["cost"]; d["latency"] += c["latency"]
    for m, d in per_model.items():
        n = max(1, d["calls"])
        d.update(mean_in=round(d["in"] / n, 1), mean_out=round(d["out"] / n, 1), cost_per_call=d["cost"] / n, mean_latency=round(d["latency"] / n, 2))
    api_errors = sum(1 for r in recs if r.get("error"))
    parse_fail = sum(1 for r in recs if not r.get("error") and not r.get("parsed"))
    grade_err = sum(1 for r in recs if r.get("grade_error"))
    gs = [r["grade_s"] for r in recs if r.get("grade_s") is not None]
    stops: dict[str, int] = {}
    for r in recs:
        if not r.get("error"):
            stops[str(r.get("stop"))] = stops.get(str(r.get("stop")), 0) + 1
    parse_fail_truncated = sum(1 for r in recs if not r.get("error") and not r.get("parsed") and str(r.get("stop")) in ("max_tokens", "length"))
    return {"per_model": per_model, "n_records": len(recs), "api_errors": api_errors, "parse_failures": parse_fail,
            "parse_failures_at_max_tokens": parse_fail_truncated, "stop_reasons": stops,
            "grader_errors": grade_err, "mean_grade_s": (sum(gs) / len(gs)) if gs else 0.0, "max_grade_s": max(gs, default=0.0)}


def extrapolate(summary: dict, n_slice_items: int, slice_samples: int) -> dict:
    scale = FULL["items"] * FULL["samples"]          # calls per model at full size
    cost = sum(d["cost_per_call"] * scale for d in summary["per_model"].values())
    by_prov: dict[str, float] = {}
    for m, d in summary["per_model"].items():
        prov = panel.spec_by_key(m).provider
        by_prov[prov] = by_prov.get(prov, 0.0) + scale * d["mean_latency"] / PROVIDER_CONCURRENCY[prov]
    api_wall = max(by_prov.values()) if by_prov else 0.0
    grade_cpu = summary["mean_grade_s"] * scale * len(summary["per_model"])
    return {"calls_full": scale * len(summary["per_model"]), "cost_usd": cost, "api_wall_s_by_provider": by_prov,
            "api_wall_s": api_wall, "grading_cpu_s": grade_cpu, "grading_wall_s_at_6_workers": grade_cpu / 6}


async def run_slice(pool_name: str, n: int, work: Path, llm: LLM) -> tuple[dict, float]:
    from metabench.panel import precompute
    full = load_pool(ROOT / POOL_PATHS[pool_name])
    ids = sorted(full)
    random.Random(20261025).shuffle(ids)
    sl = {i: full[i] for i in ids[:n]}
    out = work / f"{pool_name}_slice_precompute.jsonl"
    t0 = time.time()
    await precompute(sl, panel.PANEL, 1, out, llm, concurrency=48)
    wall = time.time() - t0
    recs = [json.loads(l) for l in open(out)]
    calls = [json.loads(l) for l in open(llm.log_path)] if Path(llm.log_path).exists() else []
    summ = summarise(recs, calls)
    out.unlink()                                   # answers/correctness never leave tmpfs
    return summ, wall


def render(pool_name: str, n: int, summ: dict, wall: float, est: dict) -> str:
    lines = [f"## {pool_name} (slice of {n} items x 17 configurations x 1 sample = {summ['n_records']} records; wall {wall:.0f} s)", "",
             f"Slice totals: api errors {summ['api_errors']}, parse failures {summ['parse_failures']} (of which at the 2,048-token output cap: "
             f"{summ.get('parse_failures_at_max_tokens', '?')}), stop reasons {summ.get('stop_reasons', {})}, grader errors {summ['grader_errors']}, "
             f"mean grading time {summ['mean_grade_s']:.3f} s (max {summ['max_grade_s']:.2f} s).", "",
             "| model | provider | calls | mean in | mean out | mean latency s | cost/call $ | cost at 2000x5 $ |", "|---|---|---|---|---|---|---|---|"]
    for m in [s.key for s in panel.PANEL]:
        d = summ["per_model"].get(m)
        if not d:
            lines.append(f"| {m} | {panel.spec_by_key(m).provider} | 0 | - | - | - | - | unreachable |"); continue
        lines.append(f"| {m} | {panel.spec_by_key(m).provider} | {d['calls']} | {d['mean_in']} | {d['mean_out']} | {d['mean_latency']} | {d['cost_per_call']:.5f} | {d['cost_per_call'] * FULL['items'] * FULL['samples']:.0f} |")
    lines += ["", f"**Estimate at 17 x 2,000 x 5 = {est['calls_full']:,} calls: cost ${est['cost_usd']:,.0f}; API wall "
              f"{est['api_wall_s'] / 3600:.1f} h (max over providers of calls x mean latency / runner concurrency: "
              + ", ".join(f"{p} {v / 3600:.1f} h" for p, v in sorted(est['api_wall_s_by_provider'].items()))
              + f"); grading CPU {est['grading_cpu_s'] / 3600:.1f} h ({est['grading_wall_s_at_6_workers'] / 3600:.1f} h wall at 6 sandbox workers, overlapping the API wall).**", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pools", default="math,code,factual")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--out", default=str(ROOT / "docs" / "PRECOMPUTE_ESTIMATE.md"))
    ap.add_argument("--work", default="/dev/shm/mb_precompute_estimate")
    a = ap.parse_args(argv)
    assert a.n <= 20, "throwaway slices are capped at 20 items (BLINDING: Builder 2 brief)"
    panel.set_active("confirmatory")
    load_keys_from_env_file()
    work = Path(a.work); shutil.rmtree(work, ignore_errors=True); work.mkdir(parents=True, mode=0o700)
    sections = [f"# Precompute cost and time estimate (measured {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} UTC from {a.n}-item throwaway slices; "
                "status, token counts, latency and cost only)", "",
                "Assumptions: prices from metabench/llm.py PRICES (third-party figures for post-cutoff models; Gemini introductory prices); "
                "latency extrapolated linearly at the runner's per-provider concurrency (anthropic 40, openai 56, google 32, xai 32), "
                "which ignores rate limits and queueing; grading time measured per record on this box (8 cores, load at measurement time in the log). "
                "Parse failures are reported per pool only.", ""]
    try:
        for pool_name in a.pools.split(","):
            llm = LLM(anthropic_concurrency=40, openai_concurrency=56, google_concurrency=32, xai_concurrency=32,
                      log_path=str(work / f"{pool_name}_llm_calls.jsonl"))
            summ, wall = asyncio.run(run_slice(pool_name, a.n, work, llm))
            est = extrapolate(summ, a.n, 1)
            sections.append(render(pool_name, a.n, summ, wall, est))
            print(f"{pool_name}: {summ['n_records']} records in {wall:.0f}s; api errors {summ['api_errors']}, parse failures {summ['parse_failures']}, "
                  f"grader errors {summ['grader_errors']}; est cost ${est['cost_usd']:,.0f}, api wall {est['api_wall_s'] / 3600:.1f} h", flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    Path(a.out).write_text("\n".join(sections))
    print(f"written {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
