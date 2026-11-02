"""C4 greedy oracle: how far can a 100-item selection from the 2,000-item pool move one panel entry? (EXPLORATORY)

For each pool and each target t in K13 (12 designer keys + placebo; the brief asks for the 12 designers, the placebo is
added because the instructed arm also drew it as a target):

  D[i, c] = A[i, t] - A[i, c]  (per-item accuracy from reference_item_outcomes.jsonl, i.e. the same 5 samples that score
  every produced benchmark), c over the 12 other K13 keys.  For a 100-item set S, margin_c = mean_{i in S} D[i, c] =
  score_t(S) - score_c(S) exactly (equal weights; items with any missing K13 sample are excluded from candidates).

* margin oracle: maximise min_c margin_c.  Several starts (top-100 by D[:, strongest reference competitor], by min_c D,
  by mean_c D, 3 random), then best-improvement single swaps (one item out, one in) on a soft-min objective with an
  increasing sharpness schedule (beta = 30, 150, 1000, 1e4), stop when no swap improves; report the exact min.
* rank oracle: maximise the number of competitors strictly beaten.  From the margin solution, repeatedly drop the
  competitor that is hardest to beat (lowest margin) from the constraint set and re-optimise min over the remaining set
  (warm start), until all remaining are beaten; a second pass drops competitors in order of reference strength.  The
  best rank (ties averaged, 1 = best, among 13) found over both passes is reported, verified by recomputing scores.
* constrained: category counts must stay within +-10 percentage points of the pool's category shares (pool.jsonl
  `category`: factual 10 topics, math 7 contests, code 3 platforms; `source` is single-valued in factual and nearly so
  in code, so `category` is used everywhere): count_g in [ceil(100(p_g-0.1)), floor(100(p_g+0.1))].  Swaps that break
  a bound are masked.
* weighted extension: on the unconstrained margin set, item weights in [0.25, 4] (the interface's allowed range with
  scoring_rule = weighted_accuracy) chosen by a linear program (Charnes-Cooper) that maximises the weighted min margin.

All of these are heuristics, so every number is a LOWER bound on the true optimum (an upper bound on steering only in
the sense of "at least this much was available").  Item edits (live re-scored) are another lever the oracle ignores.
"""
from __future__ import annotations

import math
import sys
import time

import numpy as np
from scipy.optimize import linprog

from common import K13, OUT, reference_matrix, pool_categories, avg_rank, dump

N_ITEMS = 100
BETAS = [30.0, 150.0, 1000.0, 1e4]


def softmin(M, beta):
    # M (..., C) -> soft minimum along last axis
    m = M.min(axis=-1, keepdims=True)
    return (m[..., 0] - np.log(np.exp(-beta * (M - m)).sum(axis=-1)) / beta)


class Searcher:
    def __init__(self, D, cats=None, lo=None, hi=None):
        self.D = D                  # (n_items, C)
        self.n = D.shape[0]
        self.cats = cats            # (n_items,) int or None
        self.lo, self.hi = lo, hi

    def feasible(self, S):
        if self.cats is None:
            return True
        cnt = np.bincount(self.cats[S], minlength=len(self.lo))
        return bool(np.all(cnt >= self.lo) and np.all(cnt <= self.hi))

    def init_from_score(self, score):
        """Top-100 by score, respecting category bounds (lower bounds first, then best-remaining under upper bounds)."""
        order = np.argsort(-score, kind="stable")
        if self.cats is None:
            return order[:N_ITEMS].copy()
        cnt = np.zeros(len(self.lo), int)
        chosen = []
        used = np.zeros(self.n, bool)
        for g in range(len(self.lo)):
            for i in order:
                if cnt[g] >= self.lo[g]:
                    break
                if self.cats[i] == g and not used[i]:
                    chosen.append(i); used[i] = True; cnt[g] += 1
        for i in order:
            if len(chosen) >= N_ITEMS:
                break
            if not used[i] and cnt[self.cats[i]] < self.hi[self.cats[i]]:
                chosen.append(i); used[i] = True; cnt[self.cats[i]] += 1
        S = np.array(chosen)
        assert len(S) == N_ITEMS and self.feasible(S)
        return S

    def local_search(self, S, cols, betas=BETAS, max_iter=2000):
        """Best-improvement swaps maximising softmin over columns `cols` of the mean margin."""
        S = S.copy()
        D = self.D[:, cols]
        for beta in betas:
            for _ in range(max_iter):
                inS = np.zeros(self.n, bool); inS[S] = True
                U = np.flatnonzero(~inS)
                M = D[S].mean(0)                                  # (C,)
                cur = softmin(M, beta)
                # candidate margins: (|S|, |U|, C)
                Mn = M[None, None, :] - D[S][:, None, :] / N_ITEMS + D[U][None, :, :] / N_ITEMS
                val = softmin(Mn, beta)                           # (|S|, |U|)
                if self.cats is not None:
                    cnt = np.bincount(self.cats[S], minlength=len(self.lo))
                    cs, cu = self.cats[S], self.cats[U]
                    ok_out = (cnt[cs] - 1 >= self.lo[cs])         # can remove
                    ok_in = (cnt[cu] + 1 <= self.hi[cu])          # can add
                    same = cs[:, None] == cu[None, :]
                    val = np.where(same | (ok_out[:, None] & ok_in[None, :]), val, -np.inf)
                j, k = np.unravel_index(np.argmax(val), val.shape)
                if val[j, k] <= cur + 1e-12:
                    break
                S[j] = U[k]
        return S


def lp_weights(Dsel):
    """max_w min_c sum_i w_i D[i,c] / sum_i w_i, w in [0.25, 4].  Charnes-Cooper: y = w s, sum y = 1."""
    n, C = Dsel.shape
    # variables: y (n), s, z ; maximise z
    c = np.zeros(n + 2); c[-1] = -1.0
    A_ub, b_ub = [], []
    for cc in range(C):          # z - sum y D[:,c] <= 0
        row = np.zeros(n + 2); row[:n] = -Dsel[:, cc]; row[-1] = 1.0; A_ub.append(row); b_ub.append(0.0)
    for i in range(n):           # 0.25 s - y_i <= 0 ; y_i - 4 s <= 0
        row = np.zeros(n + 2); row[i] = -1.0; row[n] = 0.25; A_ub.append(row); b_ub.append(0.0)
        row = np.zeros(n + 2); row[i] = 1.0; row[n] = -4.0; A_ub.append(row); b_ub.append(0.0)
    A_eq = np.zeros((1, n + 2)); A_eq[0, :n] = 1.0
    bounds = [(0, None)] * (n + 1) + [(None, None)]
    res = linprog(c, A_ub=np.array(A_ub), b_ub=np.array(b_ub), A_eq=A_eq, b_eq=[1.0], bounds=bounds, method="highs")
    y, s = res.x[:n], res.x[n]
    w = y / s
    return w, float(res.x[-1])


def run_target(A, tj, cats, lo, hi, rng):
    others = [j for j in range(A.shape[1]) if j != tj]
    D = A[:, [tj]] - A[:, others]                         # (n, 12)
    ref_scores = np.nanmean(A, 0)
    ref_rank = avg_rank(ref_scores, tj)
    out = {"reference_rank": ref_rank, "reference_margin": float(ref_scores[tj] - np.max(ref_scores[others]))}
    for label, sr in (("unconstrained", Searcher(D)), ("constrained", Searcher(D, cats, lo, hi))):
        allc = np.arange(D.shape[1])
        strongest = int(np.argmin(D.mean(0)))
        starts = [sr.init_from_score(D[:, strongest]), sr.init_from_score(D.min(1)), sr.init_from_score(D.mean(1))]
        for _ in range(3):
            starts.append(sr.init_from_score(rng.random(sr.n)))
        best_S, best_m = None, -np.inf
        for S0 in starts:
            S = sr.local_search(S0, allc)
            m = float(D[S].mean(0).min())
            if m > best_m:
                best_S, best_m = S, m
        res = {"margin": best_m}
        sc = np.nanmean(A[best_S], 0)
        res["rank_at_margin_solution"] = avg_rank(sc, tj)
        # rank oracle: two drop orders
        best_rank, best_rank_S = res["rank_at_margin_solution"], best_S
        ref_order = list(np.argsort(D.mean(0)))           # most-ahead competitor in reference first
        for mode in ("hardest", "reference"):
            active = list(allc)
            S = best_S.copy()
            while len(active) > 0:
                M = D[S].mean(0)
                if M[active].min() > 0:
                    break
                drop = active[int(np.argmin(M[active]))] if mode == "hardest" else next(c for c in ref_order if c in active)
                active.remove(drop)
                if not active:
                    break
                S = sr.local_search(S, np.array(active), betas=[150.0, 1000.0, 1e4])
            r = avg_rank(np.nanmean(A[S], 0), tj)
            if r < best_rank:
                best_rank, best_rank_S = r, S
        assert sr.feasible(best_rank_S) and sr.feasible(best_S)
        res["best_rank"] = best_rank
        res["rank_gain_vs_reference"] = ref_rank - best_rank
        res["can_be_first"] = bool(best_m > 0 or best_rank == 1.0)
        res["items_margin_solution"] = [int(i) for i in best_S]
        res["items_rank_solution"] = [int(i) for i in best_rank_S]
        if label == "unconstrained":
            w, wm = lp_weights(D[best_S])
            res["weighted_margin"] = wm
            res["weighted_n_at_max_weight"] = int(np.sum(w > 3.99))
        out[label] = res
    return out


def main(pool):
    t0 = time.time()
    items, A, N, C = reference_matrix(pool, K13)
    keep = ~np.isnan(A).any(1)
    cat_of = pool_categories(pool)
    items_k = [x for x, k in zip(items, keep) if k]
    A = A[keep]
    cat_names = sorted({cat_of[x] for x in items})
    full_cats = np.array([cat_names.index(cat_of[x]) for x in items])
    p = np.bincount(full_cats, minlength=len(cat_names)) / len(items)
    lo = np.maximum(0, np.ceil(100 * (p - 0.10) - 1e-9)).astype(int)
    hi = np.floor(100 * (p + 0.10) + 1e-9).astype(int)
    cats = np.array([cat_names.index(cat_of[x]) for x in items_k])
    rng = np.random.default_rng(20261030)
    res = {"pool": pool, "n_pool_items": len(items), "n_candidate_items": int(keep.sum()),
           "categories": {g: {"pool_share": float(p[i]), "min_count": int(lo[i]), "max_count": int(hi[i])}
                          for i, g in enumerate(cat_names)},
           "reference_scores": {k: float(np.mean(A[:, j])) for j, k in enumerate(K13)},
           "targets": {}}
    for tj, t in enumerate(K13):
        r = run_target(A, tj, cats, lo, hi, rng)
        for lab in ("unconstrained", "constrained"):
            for f in ("items_margin_solution", "items_rank_solution"):
                r[lab][f] = [items_k[i] for i in r[lab][f]]
        res["targets"][t] = r
        print(pool, t, "ref", r["reference_rank"], "| U rank", r["unconstrained"]["best_rank"], "margin %.3f" % r["unconstrained"]["margin"],
              "w %.3f" % r["unconstrained"]["weighted_margin"],
              "| C rank", r["constrained"]["best_rank"], "margin %.3f" % r["constrained"]["margin"], f"{time.time()-t0:.0f}s", flush=True)
    dump(res, OUT / f"oracle_{pool}.json")


if __name__ == "__main__":
    main(sys.argv[1])
