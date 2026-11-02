"""Part 2 supplement (EXPLORATORY): pooled-across-pools randomisation p with the display shared across pools.

Usage: python p2_pooled_shared_null.py  ->  p2_pooled_shared_null.json

The registered sham display of a (designer, replicate) cell is identical in the three pools (the session seed does not
include the pool; checked: all 60 cells that occur in more than one pool have the same displayed_order in each).  The
pooled randomisation test in p2_robust.py redraws each session's display independently; this one redraws ONE uniform
order per cell and applies it to every pool's session of that cell (replacement sessions, `_rep1`, have their own
seed and get their own draw).  10,000 draws, primary Psi definition (13 displayed keys).
"""
from collections import defaultdict

import numpy as np

from scommon import K13, OUT, POOLS, bench_rows, sham_blinded, fz, tau_display, dump
from metabench.analysis import tau_b_vectorised

NP = 10000


def main():
    rng = np.random.default_rng(11)
    S = []
    for p in POOLS:
        for r in sham_blinded(bench_rows(p)):
            cell = r["session_id"].replace(f"T1_{p}_", "")
            disp = r["displayed_order"]
            S.append({"designer": r["designer"], "cell": cell,
                      "z": float(fz(tau_display(np.array([r["produced_scores"][k] for k in disp])))),
                      "sk": np.array([r["produced_scores"][k] for k in K13])})
    des = sorted({s["designer"] for s in S})
    di = {d: i for i, d in enumerate(des)}
    cnt = np.bincount([di[s["designer"]] for s in S], minlength=len(des))

    def dmean(z):
        m = np.zeros(z.shape[:-1] + (len(des),))
        for j, s in enumerate(S):
            m[..., di[s["designer"]]] += z[..., j]
        return (m / cnt).mean(-1)

    obs = float(dmean(np.array([s["z"] for s in S])))
    cells = defaultdict(list)
    for j, s in enumerate(S):
        cells[s["cell"]].append(j)
    Z = np.empty((NP, len(S)))
    for c, idx in cells.items():
        pos = np.argsort(rng.random((NP, 13)), axis=1)          # random best-first order over K13 (key indices)
        ranks = np.empty_like(pos)
        np.put_along_axis(ranks, pos, np.arange(13)[None, :].repeat(NP, 0), axis=1)
        for j in idx:
            Z[:, j] = fz(tau_b_vectorised(S[j]["sk"], -ranks.astype(float)))
    null = dmean(Z)
    out = {"n": len(S), "n_designers": len(des), "n_cells": len(cells),
           "n_cells_multi_pool": sum(len(v) > 1 for v in cells.values()),
           "psi": float(np.tanh(obs)), "p_one_sided_shared_display": float((1 + np.sum(null >= obs)) / (1 + NP)),
           "null_sd_z_shared": float(null.std()), "n_perm": NP}
    dump(out, OUT / "p2_pooled_shared_null.json")
    print(out)


if __name__ == "__main__":
    main()
