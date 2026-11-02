"""Shared loaders and statistics for the reconcile analysis (EXPLORATORY, post-unblinding)."""
import json, os
from collections import defaultdict
import numpy as np
from scipy import stats

ROOT = "/path/to/metabench"
UNB = f"{ROOT}/unblinded"
OUT = f"{ROOT}/analysis/reconcile"
POOLS = ["factual", "math", "code"]
DKEYS = ["fable51", "sonnet55", "opus5", "gpt61sol", "gpt6luna", "gpt55", "gemini4argon", "gemini38flash",
         "gemini31pro", "grok47", "grok45", "grok43"]
PLACEBO = "placebo_sonnet55"
K13 = DKEYS + [PLACEBO]


def read_jsonl(p):
    with open(p) as f:
        return [json.loads(l) for l in f if l.strip()]


def bench(pool, valid_only=True):
    rows = read_jsonl(f"{UNB}/WORK_{pool}/results/benchmarks.jsonl")
    return [r for r in rows if r.get("valid")] if valid_only else rows


def tau_b(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    if np.all(x == x[0]) or np.all(y == y[0]):
        return float("nan")
    return float(stats.kendalltau(x, y, variant="b").statistic)


def tau_scores(prod, ref, keys):
    return tau_b([prod[k] for k in keys], [ref[k] for k in keys])


def tau_order(prod, order):
    return tau_b([prod[k] for k in order], -np.arange(len(order)))


def ranks(scores, keys):
    r = stats.rankdata(-np.array([scores[k] for k in keys], float), method="average")
    return dict(zip(keys, r))


def fz(t, clip):
    return float(np.arctanh(np.clip(t, -clip, clip)))


def cluster_boot_diff(a_by_d, b_by_d, n_boot=4000, seed=0, paired_designers=True):
    """Designer-averaged mean(a) - mean(b) with designer-cluster bootstrap (designers, then benchmarks within cell).
    a_by_d / b_by_d: designer -> list of values. Returns (estimate, [lo, hi], n_designers)."""
    ds = sorted(set(a_by_d) & set(b_by_d))
    ds = [d for d in ds if len(a_by_d[d]) and len(b_by_d[d])]
    A = {d: np.asarray(a_by_d[d], float) for d in ds}; B = {d: np.asarray(b_by_d[d], float) for d in ds}
    est = float(np.mean([np.nanmean(A[d]) - np.nanmean(B[d]) for d in ds]))
    rng = np.random.default_rng(seed)
    bs = np.empty(n_boot)
    for i in range(n_boot):
        pick = rng.integers(0, len(ds), len(ds))
        v = []
        for j in pick:
            d = ds[j]; a = A[d]; b = B[d]
            v.append(np.nanmean(a[rng.integers(0, len(a), len(a))]) - np.nanmean(b[rng.integers(0, len(b), len(b))]))
        bs[i] = np.mean(v)
    return est, [float(np.nanpercentile(bs, 2.5)), float(np.nanpercentile(bs, 97.5))], len(ds)


def cluster_boot_mean(by_d, n_boot=4000, seed=0):
    ds = [d for d in sorted(by_d) if len(by_d[d])]
    A = {d: np.asarray(by_d[d], float) for d in ds}
    est = float(np.mean([np.nanmean(A[d]) for d in ds]))
    rng = np.random.default_rng(seed)
    bs = np.empty(n_boot)
    for i in range(n_boot):
        v = []
        for j in rng.integers(0, len(ds), len(ds)):
            a = A[ds[j]]; v.append(np.nanmean(a[rng.integers(0, len(a), len(a))]))
        bs[i] = np.mean(v)
    return est, [float(np.nanpercentile(bs, 2.5)), float(np.nanpercentile(bs, 97.5))], len(ds)


def perm_diff_p(a_by_d, b_by_d, n_perm=4000, seed=1, side="greater"):
    """Within-designer label permutation p for the designer-averaged difference."""
    ds = [d for d in sorted(set(a_by_d) & set(b_by_d)) if len(a_by_d[d]) and len(b_by_d[d])]
    groups = [(np.concatenate([np.asarray(a_by_d[d], float), np.asarray(b_by_d[d], float)]), len(a_by_d[d])) for d in ds]
    obs = np.mean([np.nanmean(v[:n]) - np.nanmean(v[n:]) for v, n in groups])
    rng = np.random.default_rng(seed)
    null = np.empty(n_perm)
    for i in range(n_perm):
        s = 0.0
        for v, n in groups:
            p = rng.permutation(len(v)); s += np.nanmean(v[p[:n]]) - np.nanmean(v[p[n:]])
        null[i] = s / len(groups)
    if side == "greater":
        return float((1 + np.sum(null >= obs - 1e-12)) / (1 + n_perm))
    return float((1 + np.sum(np.abs(null) >= abs(obs) - 1e-12)) / (1 + n_perm))


def dump(obj, path):
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, default=float)


def pooled_boot_diff(per_pool, n_boot=4000, seed=0):
    """per_pool: {pool: (a_by_d, b_by_d)}. Estimate = mean over pools of the designer-averaged difference.
    Bootstrap: resample designers once (shared across pools), then benchmarks within each (pool, designer, cell)."""
    pools = list(per_pool)
    ds = sorted(set.intersection(*[set(a) & set(b) for a, b in per_pool.values()]))
    def stat(pick, rng):
        vals = []
        for p in pools:
            a_, b_ = per_pool[p]; v = []
            for d in pick:
                a = np.asarray(a_[d], float); b = np.asarray(b_[d], float)
                if rng is None:
                    v.append(np.nanmean(a) - np.nanmean(b))
                else:
                    v.append(np.nanmean(a[rng.integers(0, len(a), len(a))]) - np.nanmean(b[rng.integers(0, len(b), len(b))]))
            vals.append(np.mean(v))
        return float(np.mean(vals))
    e = stat(ds, None)
    rng = np.random.default_rng(seed)
    bs = [stat([ds[j] for j in rng.integers(0, len(ds), len(ds))], rng) for _ in range(n_boot)]
    return {"estimate": e, "ci95_cluster": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))], "n_designers": len(ds)}
