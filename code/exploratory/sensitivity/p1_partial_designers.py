"""Part 1 supplement (EXPLORATORY): only m of the 12 designers follow the display.

Usage: python p1_partial_designers.py  ->  p1_partial_designers.json

For m in {1, 2, 3, 4, 6, 9, 12} follower designers and k in {2, 5, 10, 20, 30}: the m designers' sham/blinded sessions
take their k-swap state (greedy or naive path from p1_paths_<pool>.npz), every other designer's sessions stay at k = 0
(the real benchmarks).  20 random follower subsets per (m, k) (the same subsets for every k and path; m = 12 has one);
for each: Psi, randomisation p (1,000 uniform re-draws) and designer-cluster bootstrap CI (1,000).  Reported: mean Psi
over subsets and the share of subsets that meet detection (cluster CI lower bound > 0 and p < 0.05).  Per pool and pooled
(designer = cluster across pools; a follower designer follows in every pool).
"""
from __future__ import annotations

import numpy as np

from scommon import OUT, POOLS, DESIGNERS, psi_stats, dump

MS = [1, 2, 3, 4, 6, 9, 12]
KS = [2, 5, 10, 20, 30]
NSUB = 20


def main():
    data = {p: dict(np.load(OUT / f"p1_paths_{p}.npz")) for p in POOLS}
    rng = np.random.default_rng(7)
    subsets = {m: ([list(DESIGNERS)] if m == 12 else [list(rng.choice(DESIGNERS, m, replace=False)) for _ in range(NSUB)])
               for m in MS}
    res = {"m": MS, "k": KS, "n_subsets": NSUB, "n_perm": 1000, "n_boot": 1000}
    for scope in POOLS + ["pooled"]:
        pools = POOLS if scope == "pooled" else [scope]
        o = {}
        for meth in ("greedy", "naive"):
            om = {}
            for m in MS:
                for k in KS:
                    psis, det = [], []
                    for si, sub in enumerate(subsets[m]):
                        S = []
                        for p in pools:
                            D = data[p]
                            for i in range(D[meth].shape[0]):
                                des = str(D["designer"][i])
                                S.append({"designer": des, "pool": p, "scores": np.round(D[meth][i, k if des in sub else 0], 5)})
                        st = psi_stats(S, 1000, 1000, seed=si * 100 + k)
                        psis.append(st["psi"])
                        det.append(st["ci95_cluster_tau"][0] > 0 and st["p_one_sided"] < 0.05)
                    om[f"m{m}_k{k}"] = {"m": m, "k": k, "psi_mean": float(np.mean(psis)), "share_detect": float(np.mean(det)),
                                        "n_subsets": len(psis)}
            o[meth] = om
            print(scope, meth, {kk: (round(v["psi_mean"], 3), v["share_detect"]) for kk, v in om.items()}, flush=True)
        res[scope] = o
    dump(res, OUT / "p1_partial_designers.json")


if __name__ == "__main__":
    main()
