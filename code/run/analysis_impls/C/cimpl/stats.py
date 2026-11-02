"""Rank statistics, Kendall tau-b, RBO, Fisher z, Holm, bootstrap helpers (DECISIONS D3, D4, D9, D11, D12, D26)."""
from __future__ import annotations

from itertools import combinations

import numpy as np
from scipy.stats import kendalltau, rankdata, t as student_t

TAU_CLIP = 0.999999


def ranks(scores: dict[str, float], keys: list[str]) -> dict[str, float]:
    """Average ranks, 1 = best, over `keys` (D3)."""
    r = rankdata([-scores[k] for k in keys], method="average")
    return {k: float(v) for k, v in zip(keys, r)}


def tau_b(scores: dict[str, float], order: list[str]) -> float:
    """Kendall tau-b between produced scores and a displayed order (best first) over the keys of `order` (D4)."""
    x = [scores[k] for k in order]
    y = [-i for i in range(len(order))]
    t = kendalltau(x, y, variant="b").statistic
    return float(t) if np.isfinite(t) else 0.0


def fisher_z(tau: float) -> float:
    return float(np.arctanh(np.clip(tau, -TAU_CLIP, TAU_CLIP)))


def pair_signs(values: np.ndarray) -> np.ndarray:
    """Sign of pairwise differences over all unordered pairs (i<j), for vectorised tau-b."""
    i, j = np.array(list(combinations(range(len(values)), 2))).T
    return np.sign(values[i] - values[j])


def tau_b_vectorised(x: np.ndarray, orders_pos: np.ndarray) -> np.ndarray:
    """tau-b between a fixed score vector x (n,) and P position vectors (P, n) with no ties among positions.
    Agrees with scipy's tau-b; used for randomisation re-draws (D8)."""
    n = len(x)
    i, j = np.array(list(combinations(range(n), 2))).T
    sx = np.sign(x[i] - x[j])
    sy = np.sign(orders_pos[:, j] - orders_pos[:, i])         # position smaller = better, so sign flipped
    n0 = n * (n - 1) / 2
    n1 = float(np.sum(sx == 0))
    denom = np.sqrt((n0 - n1) * n0)
    return (sy @ sx) / denom if denom > 0 else np.zeros(orders_pos.shape[0])


def rbo_ext(s: list[str], t: list[str], p: float = 0.8) -> float:
    """Rank-biased overlap, extrapolated, for two complete rankings of the same set (Webber et al. 2010, eq. 32) (D26)."""
    k = len(s)
    assert len(t) == k and set(s) == set(t)
    seen_s: set[str] = set()
    seen_t: set[str] = set()
    total = 0.0
    x_d = 0
    for d in range(1, k + 1):
        a, b = s[d - 1], t[d - 1]
        if a == b:
            x_d += 1
        else:
            x_d += int(a in seen_t) + int(b in seen_s)
        seen_s.add(a)
        seen_t.add(b)
        total += (x_d / d) * p ** d
    return float((1 - p) / p * total + (x_d / k) * p ** k)


def ranking_from_scores(scores: dict[str, float], keys: list[str]) -> list[str]:
    """Best-first ranking; ties broken by key name (D26)."""
    return sorted(keys, key=lambda k: (-scores[k], k))


def holm(pvals: dict[str, float], alpha: float = 0.05) -> dict[str, dict]:
    """Holm step-down; returns adjusted p and rejection per name (D11)."""
    names = sorted(pvals, key=lambda n: pvals[n])
    m = len(names)
    out: dict[str, dict] = {}
    running = 0.0
    for rank, n in enumerate(names):
        adj = min(1.0, (m - rank) * pvals[n])
        running = max(running, adj)
        out[n] = {"p_one_sided": pvals[n], "p_holm": running, "reject_at_0.05": bool(running < alpha)}
    return out


def bh_reject(pvals: np.ndarray, q: float = 0.05) -> np.ndarray:
    """Benjamini-Hochberg rejections."""
    p = np.asarray(pvals, float)
    m = len(p)
    if m == 0:
        return np.zeros(0, bool)
    order = np.argsort(p)
    thresh = q * (np.arange(1, m + 1) / m)
    below = p[order] <= thresh
    k = np.max(np.nonzero(below)[0]) + 1 if below.any() else 0
    rej = np.zeros(m, bool)
    rej[order[:k]] = True
    return rej


def percentile_ci(samples: np.ndarray, level: float = 0.95) -> list[float]:
    s = np.asarray(samples, float)
    s = s[np.isfinite(s)]
    if s.size == 0:
        return [float("nan"), float("nan")]
    lo, hi = np.percentile(s, [100 * (1 - level) / 2, 100 * (1 + level) / 2])
    return [float(lo), float(hi)]


def designer_t_one_sided(per_designer: np.ndarray) -> dict:
    """One-sided one-sample t on per-designer means (the heterogeneity-respecting test of section 7)."""
    v = np.asarray(per_designer, float)
    d = len(v)
    if d < 2:
        return {"t": float("nan"), "p_one_sided": float("nan"), "df": d - 1}
    se = v.std(ddof=1) / np.sqrt(d)
    tval = v.mean() / se if se > 0 else float("inf")
    return {"t": float(tval), "p_one_sided": float(student_t.sf(tval, d - 1)), "df": d - 1,
            "ci95": [float(v.mean() - student_t.ppf(0.975, d - 1) * se), float(v.mean() + student_t.ppf(0.975, d - 1) * se)]}


class ClusterBootstrap:
    """Designer-cluster bootstrap: designers with replacement, then benchmarks within (designer, cell) (D9, D12).
    `cells` is a list of (designer, cell) per row. Each replicate yields (row_idx, cluster_id) arrays."""

    def __init__(self, designers: list[str], cells: list[str], rng: np.random.Generator):
        self.rng = rng
        self.designer_list = sorted(set(designers))
        self.groups: dict[str, list[np.ndarray]] = {}
        d_arr = np.asarray(designers)
        c_arr = np.asarray(cells)
        for d in self.designer_list:
            rows = np.nonzero(d_arr == d)[0]
            self.groups[d] = [rows[c_arr[rows] == c] for c in sorted(set(c_arr[rows]))]

    def replicate(self) -> tuple[np.ndarray, np.ndarray]:
        nd = len(self.designer_list)
        draw = self.rng.integers(0, nd, size=nd)
        idx_parts, cl_parts = [], []
        for cl, di in enumerate(draw):
            for rows in self.groups[self.designer_list[di]]:
                pick = rows[self.rng.integers(0, len(rows), size=len(rows))]
                idx_parts.append(pick)
                cl_parts.append(np.full(len(pick), cl))
        return np.concatenate(idx_parts), np.concatenate(cl_parts)


def cluster_mean(values: np.ndarray, clusters: np.ndarray, mask: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Per-cluster means of values[mask]; returns (means over clusters that have rows, their cluster ids)."""
    if mask is not None:
        values, clusters = values[mask], clusters[mask]
    if len(values) == 0:
        return np.zeros(0), np.zeros(0, int)
    n_cl = int(clusters.max()) + 1
    s = np.bincount(clusters, weights=values, minlength=n_cl)
    c = np.bincount(clusters, minlength=n_cl)
    have = c > 0
    return s[have] / c[have], np.nonzero(have)[0]
