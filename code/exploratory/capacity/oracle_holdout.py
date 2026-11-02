"""Supplement to C4: how much of the oracle margin is item signal rather than exploitation of the 5 scoring samples?
(EXPLORATORY)

Per pool and target (K13): per-sample correctness from precompute/<pool>.jsonl via metabench.panel.load_correctness
(last row per (item, model, sample) wins; error rows dropped).  Samples 0-2 = selection set, samples 3-4 = held-out set
(by sample index).  The margin oracle (oracle.Searcher, unconstrained, starts: top-100 by D[:, strongest], by min D,
by mean D) is run on the selection-sample accuracies; the chosen 100 items are then scored on the held-out samples and
on all 5 samples.  Items lacking any of the 5 samples for any K13 key are excluded.
"""
from __future__ import annotations

import sys

import numpy as np

from common import K13, OUT, UNB, avg_rank, dump
from metabench.panel import load_correctness, latest_rows
from oracle import Searcher


def main(pool):
    rows = latest_rows(UNB / f"WORK_{pool}" / "precompute" / f"{pool}.jsonl",
                       lambda r: None if r.get("error") else int(r["correct"]))
    items = sorted({k[0] for k in rows})
    ii = {x: i for i, x in enumerate(items)}
    kk = {k: j for j, k in enumerate(K13)}
    X = np.full((len(items), len(K13), 5), np.nan)
    for (it, m, s), c in rows.items():
        if m in kk and c is not None and 0 <= s < 5:
            X[ii[it], kk[m], s] = c
    keep = ~np.isnan(X).any((1, 2))
    X = X[keep]
    sel, hold, full = X[:, :, :3].mean(2), X[:, :, 3:].mean(2), X.mean(2)
    out = {"pool": pool, "n_items": int(keep.sum()), "targets": {}}
    for tj, t in enumerate(K13):
        others = [j for j in range(len(K13)) if j != tj]
        D = sel[:, [tj]] - sel[:, others]
        sr = Searcher(D)
        allc = np.arange(len(others))
        best_S, best_m = None, -np.inf
        for sc in (D[:, int(np.argmin(D.mean(0)))], D.min(1), D.mean(1)):
            S = sr.local_search(sr.init_from_score(sc), allc)
            m = float(D[S].mean(0).min())
            if m > best_m:
                best_S, best_m = S, m
        res = {"margin_selection_samples": best_m}
        for lab, M in (("heldout_samples", hold), ("all5_samples", full)):
            s = M[best_S].mean(0)
            res[f"margin_{lab}"] = float(s[tj] - s[others].max())
            res[f"rank_{lab}"] = avg_rank(s, tj)
        out["targets"][t] = res
        print(pool, t, {k: round(v, 3) for k, v in res.items()}, flush=True)
    dump(out, OUT / f"oracle_holdout_{pool}.json")


if __name__ == "__main__":
    main(sys.argv[1])
