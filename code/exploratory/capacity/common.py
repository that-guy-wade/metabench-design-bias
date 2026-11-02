"""Shared loaders and statistics for the capacity / noise-floor analysis (EXPLORATORY, post-unblinding).

Run with PYTHONPATH=/path/to/metabench/run so that `metabench` imports. Nothing here writes outside
/path/to/metabench/analysis/capacity/.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

from metabench import panel
panel.set_active("confirmatory")  # confirmatory keys and TIERS (implementation A forgot this; see CONTEXT.md)
from metabench.analysis import kendall_tau_b, fisher_z, ranks_from_scores, order_to_scores, tau_b_vectorised  # noqa: E402
from metabench.arms import draw_displayed_order  # noqa: E402

ROOT = Path("/path/to/metabench")
UNB = ROOT / "unblinded"
OUT = ROOT / "analysis" / "capacity"
POOLS = {"factual": "factual_qa", "math": "math", "code": "code"}

DESIGNERS = list(panel.DISPLAYED_KEYS)             # 12 designer keys
PLACEBO = "placebo_sonnet55"
K13 = DESIGNERS + [PLACEBO]                         # rank set for the oracle and gains (12 designers + placebo)
K12 = DESIGNERS
TIERS = dict(panel.TIERS)                           # confirmatory reputation tiers


def read_jsonl(p):
    with open(p) as f:
        return [json.loads(l) for l in f if l.strip()]


def bench_rows(pool: str, valid_only: bool = True) -> list[dict]:
    rows = read_jsonl(UNB / f"WORK_{pool}" / "results" / "benchmarks.jsonl")
    return [r for r in rows if r.get("valid")] if valid_only else rows


def reference_matrix(pool: str, keys: list[str]):
    """Per-item accuracy matrix A[item, key] = n_correct / n_samples from reference_item_outcomes.jsonl, NaN where
    n_samples == 0.  Returns (item_ids, A, n_samples matrix)."""
    rows = read_jsonl(UNB / f"WORK_{pool}" / "results" / "reference_item_outcomes.jsonl")
    items = sorted({r["item_id"] for r in rows})
    ii = {x: i for i, x in enumerate(items)}
    kk = {k: j for j, k in enumerate(keys)}
    A = np.full((len(items), len(keys)), np.nan)
    N = np.zeros((len(items), len(keys)), dtype=int)
    C = np.zeros((len(items), len(keys)), dtype=int)
    for r in rows:
        if r["model_key"] in kk:
            i, j = ii[r["item_id"]], kk[r["model_key"]]
            N[i, j] = r["n_samples"]
            C[i, j] = r["n_correct"]
            if r["n_samples"] > 0:
                A[i, j] = r["n_correct"] / r["n_samples"]
    return items, A, N, C


def pool_categories(pool: str) -> dict[str, str]:
    rows = read_jsonl(ROOT / "run" / "pools" / POOLS[pool] / "pool.jsonl")
    return {r["id"]: r["category"] for r in rows}


def subset_scores(A: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """Mean accuracy per key over the selected item indices, skipping NaN items per key (as scoring.benchmark_scores)."""
    return np.nanmean(A[idx], axis=0)


def avg_rank(scores: np.ndarray, j: int) -> float:
    """Rank (1 = best, ties averaged) of column j in the score vector."""
    s = scores[j]
    return 1.0 + float(np.sum(scores > s)) + 0.5 * float(np.sum(scores == s) - 1)


def designer_avg(by_d: dict[str, list[float]]) -> float:
    m = [np.nanmean(v) for v in by_d.values() if len(v)]
    m = [x for x in m if not math.isnan(x)]
    return float(np.mean(m)) if m else float("nan")


def cluster_boot(by_d: dict[str, list[float]], n_boot: int = 5000, seed: int = 0, stat=np.mean):
    """Designer-cluster bootstrap (designers with replacement, then benchmarks within designer) of the
    designer-averaged mean; returns [lo, hi] 95% percentile CI."""
    rng = np.random.default_rng(seed)
    ds = [d for d, v in by_d.items() if len(v)]
    arrs = {d: np.asarray(by_d[d], float) for d in ds}
    out = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.choice(ds, size=len(ds), replace=True)
        out[b] = stat(np.array([np.nanmean(arrs[d][rng.integers(0, len(arrs[d]), len(arrs[d]))]) for d in pick]))
    return [float(np.nanpercentile(out, 2.5)), float(np.nanpercentile(out, 97.5))]


def ratio_cluster_boot(num: dict[str, list[float]], den: dict[str, list[float]], n_boot: int = 5000, seed: int = 0):
    """Cluster bootstrap CI of designer_avg(num) / designer_avg(den) with paired resampling of benchmarks."""
    rng = np.random.default_rng(seed)
    ds = [d for d in num if len(num[d])]
    a = {d: np.asarray(num[d], float) for d in ds}
    b_ = {d: np.asarray(den[d], float) for d in ds}
    out = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.choice(ds, size=len(ds), replace=True)
        nn, dd = [], []
        for d in pick:
            ix = rng.integers(0, len(a[d]), len(a[d]))
            nn.append(np.nanmean(a[d][ix])); dd.append(np.nanmean(b_[d][ix]))
        out[b] = np.mean(nn) / np.mean(dd) if np.mean(dd) != 0 else np.nan
    return [float(np.nanpercentile(out, 2.5)), float(np.nanpercentile(out, 97.5))]


def ranks13(scores: dict) -> dict[str, float]:
    return ranks_from_scores(scores, K13)


def dump(obj, path):
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, default=float)
