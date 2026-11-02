"""Shared loaders and Psi statistics for the sensitivity analyses (EXPLORATORY, post-unblinding).

Run from anywhere with PYTHONPATH=/path/to/metabench/run (for `metabench`).
Writes nothing by itself; callers write only into /path/to/metabench/analysis/sensitivity/.

Psi conventions (identical to metabench.analysis.primary_endpoint):
  per benchmark: tau-b(produced scores, display order) over the 13 displayed keys (12 designers + placebo, in
  displayed_order), Fisher z = atanh(clip(tau, -0.999, 0.999)); designer mean of z; mean over designers; report tanh.
  Randomisation null: every benchmark's display re-drawn as an independent uniform permutation (blinded generator).
  Cluster bootstrap: designers with replacement, then benchmarks within designer with replacement (pooled-across-pools:
  within designer x pool strata), percentile CI on z, reported as tanh.
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from pathlib import Path

import numpy as np

from metabench import panel
panel.set_active("confirmatory")
from metabench.analysis import fisher_z, tau_b_vectorised  # noqa: E402

ROOT = Path("/path/to/metabench")
UNB = ROOT / "unblinded"
OUT = ROOT / "analysis" / "sensitivity"
POOLS = ["factual", "math", "code"]
DESIGNERS = list(panel.DISPLAYED_KEYS)
PLACEBO = "placebo_sonnet55"
K13 = DESIGNERS + [PLACEBO]
HELDOUT = ["heldout_sonnet46", "heldout_gpt54", "heldout_gemini35flash", "heldout_grok420"]
K17 = K13 + HELDOUT
GOOGLE = ["gemini4argon", "gemini31pro", "gemini38flash"]
DEVELOPER = {"fable51": "anthropic", "opus5": "anthropic", "sonnet55": "anthropic", "gpt61sol": "openai",
             "gpt6luna": "openai", "gpt55": "openai", "gemini4argon": "google", "gemini31pro": "google",
             "gemini38flash": "google", "grok47": "xai", "grok45": "xai", "grok43": "xai"}
ZC = 0.999


def read_jsonl(p):
    with open(p) as f:
        return [json.loads(l) for l in f if l.strip()]


def bench_rows(pool, valid_only=True):
    rows = read_jsonl(UNB / f"WORK_{pool}" / "results" / "benchmarks.jsonl")
    return [r for r in rows if r.get("valid")] if valid_only else rows


def sham_blinded(rows):
    return [r for r in rows if r["info_arm"] == "sham" and r["identity_arm"] == "blinded" and r.get("displayed_order")]


def dump(obj, path):
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, default=float)


def fz(t):
    return np.arctanh(np.clip(np.asarray(t, float), -ZC, ZC))


def tau_display(scores: np.ndarray) -> float:
    """tau-b between scores (aligned with a best-first display order) and that display order."""
    n = len(scores)
    disp = -np.arange(n, dtype=float)
    return float(tau_b_vectorised(np.asarray(scores, float), disp[None, :])[0])


def _designer_mean(z, des):
    byd = defaultdict(list)
    for zz, d in zip(z, des):
        byd[d].append(zz)
    return float(np.mean([np.mean(v) for v in byd.values()]))


def psi_stats(sessions, n_perm=2000, n_boot=2000, seed=0, null=True, boot=True):
    """sessions: list of dicts with 'designer', 'pool', 'scores' (np array aligned with the display order, best first).
    Returns Psi (tanh), z, one-sided randomisation p, cluster CI (tau), n, n_designers, per-designer z means."""
    rng = np.random.default_rng(seed)
    des = [s["designer"] for s in sessions]
    taus = np.array([tau_display(s["scores"]) for s in sessions])
    z = fz(taus)
    psi_z = _designer_mean(z, des)
    out = {"psi": float(np.tanh(psi_z)), "z": psi_z, "n": len(sessions), "n_designers": len(set(des))}
    dl = sorted(set(des))
    di = {d: i for i, d in enumerate(dl)}
    dvec = np.array([di[d] for d in des])
    cnt = np.bincount(dvec, minlength=len(dl))
    if null:
        Z = np.empty((n_perm, len(sessions)))
        for j, s in enumerate(sessions):
            n = len(s["scores"])
            perm_scores = -np.argsort(rng.random((n_perm, n)), axis=1).astype(float)  # uniform random display
            Z[:, j] = fz(tau_b_vectorised(np.asarray(s["scores"], float), perm_scores))
        # designer means per replicate
        M = np.zeros((n_perm, len(dl)))
        np.add.at(M.T, dvec, Z.T)
        M /= cnt[None, :]
        nullz = M.mean(1)
        out["p_one_sided"] = float((1 + np.sum(nullz >= psi_z)) / (1 + n_perm))
        out["null_mean_z"] = float(nullz.mean())
        out["null_sd_z"] = float(nullz.std())
        out["n_perm"] = n_perm
    if boot:
        strata = defaultdict(list)   # designer -> pool -> indices
        for j, s in enumerate(sessions):
            strata[s["designer"]].append(j)
        byd = {d: defaultdict(list) for d in dl}
        for j, s in enumerate(sessions):
            byd[s["designer"]][s.get("pool", "x")].append(j)
        bz = np.empty(n_boot)
        for b in range(n_boot):
            pick = rng.choice(dl, size=len(dl), replace=True)
            ms = []
            for d in pick:
                vals = []
                for idx in byd[d].values():
                    idx = np.asarray(idx)
                    vals.append(z[idx[rng.integers(0, len(idx), len(idx))]])
                ms.append(np.mean(np.concatenate(vals)))
            bz[b] = np.mean(ms)
        out["ci95_cluster_z"] = [float(np.percentile(bz, 2.5)), float(np.percentile(bz, 97.5))]
        out["ci95_cluster_tau"] = [float(np.tanh(x)) for x in out["ci95_cluster_z"]]
        out["boot_z_upper95_one_sided_tau"] = float(np.tanh(np.percentile(bz, 95)))
        out["_boot_z"] = bz
        out["n_boot"] = n_boot
    out["designer_mean_z"] = {d: float(np.mean(z[dvec == di[d]])) for d in dl}
    out["_z"] = z
    return out


def strip(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def equivalence(st, bound=0.10):
    """One-sided equivalence (non-superiority) test of H0: tanh(Psi) >= bound vs H1: tanh(Psi) < bound.
    (i) designer-level t on designer-mean Fisher z, df = D-1; (ii) cluster bootstrap: p = share of bootstrap z >= atanh(bound)."""
    from scipy import stats
    c = math.atanh(bound)
    dm = np.array(list(st["designer_mean_z"].values()))
    D = len(dm)
    se = dm.std(ddof=1) / math.sqrt(D)
    t = (dm.mean() - c) / se
    tq = stats.t.ppf(0.95, D - 1)
    bz = st["_boot_z"]
    return {"bound_tau": bound, "D": D, "designer_mean_z": float(dm.mean()), "se_z": float(se), "t": float(t),
            "p_t_one_sided": float(stats.t.cdf(t, D - 1)),
            "upper95_t_tau": float(math.tanh(dm.mean() + tq * se)),
            "p_boot_one_sided": float((1 + np.sum(bz >= c)) / (1 + len(bz))),
            "upper95_boot_tau": float(np.tanh(np.percentile(bz, 95))),
            "equivalent_at_5pct_t": bool(stats.t.cdf(t, D - 1) < 0.05),
            "equivalent_at_5pct_boot": bool(np.percentile(bz, 95) < c)}


def avg_rank(vec, j):
    s = vec[j]
    return 1.0 + float(np.sum(vec > s)) + 0.5 * float(np.sum(vec == s) - 1)


def cluster_boot_mean(by_d, n_boot=2000, seed=0):
    """Designer-cluster bootstrap of the designer-averaged mean; by_d: designer -> list of values (or list of
    (pool, value) handled by caller). Returns est, [lo, hi], n, D."""
    rng = np.random.default_rng(seed)
    ds = [d for d, v in by_d.items() if len(v)]
    arr = {d: np.asarray(by_d[d], float) for d in ds}
    est = float(np.mean([arr[d].mean() for d in ds]))
    bs = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.choice(ds, size=len(ds), replace=True)
        bs[b] = np.mean([arr[d][rng.integers(0, len(arr[d]), len(arr[d]))].mean() for d in pick])
    return {"est": est, "ci95": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
            "n": int(sum(len(arr[d]) for d in ds)), "D": len(ds)}


def set_threads():
    for v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(v, "2")
