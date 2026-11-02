"""Part 1 statistics (EXPLORATORY): Psi dose-response over k swaps for the simulated followers.

Usage: python p1_stats.py  ->  p1_results.json   (reads p1_paths_<pool>.npz from p1_simulate.py)

For each pool and pooled (designer = cluster across pools; bootstrap strata designer x pool), each path type
(greedy, naive, random replicate 0) and each k in 0..KMAX: Psi exactly as the primary (13 displayed keys, Fisher z
clipped at 0.999, designer average, tanh), one-sided randomisation p from 2,000 uniform re-draws of every display, and a
designer-cluster bootstrap 95% CI (2,000 draws).  Random paths: mean and SD of the Psi point estimate over the 20
replicate paths too.

Leader rank gain at k: displayed leader (display position 0) rank among the 13 displayed keys at k = 0 minus at k
(positive = leader moved up); also among 12 keys (placebo dropped, or its twin sonnet55 dropped when the leader is the
placebo -- the rank set of analysis/controls q1, whose complier gain is +1.44); and 'S1-style': the designer's mean
none-arm 12-key rank of that model minus its 12-key rank at k (the +1.44 baseline definition).  Designer-cluster
bootstrap CI (2,000).

Scores are rounded to 5 decimals (the precision of produced_scores) before ranking, so k = 0 reproduces the
primary exactly (unrounded sums break exact ties such as sonnet55 = placebo).

Thresholds: smallest k with (cluster CI lower bound > 0 and p < 0.05) = the 'detection' part of the pre-registered
claim; smallest k with that AND Psi > 0.15 = the full claim; k where Psi first reaches 0.10 and 0.15 (linear
interpolation between integer k).
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from scommon import OUT, POOLS, K13, PLACEBO, bench_rows, psi_stats, strip, cluster_boot_mean, avg_rank, dump

NP = NB = 2000
GRID = [0, 2, 5, 10, 20, 30, 40, 50]


def load(pool):
    d = np.load(OUT / f"p1_paths_{pool}.npz")
    return {k: d[k] for k in d.files}


def none_baseline(pool):
    """designer -> model -> mean 12-key rank (q1 rule) in valid none-arm benchmarks."""
    acc = defaultdict(lambda: defaultdict(list))
    for r in bench_rows(pool):
        if r["info_arm"] != "none":
            continue
        for t in K13:
            keys = [k for k in K13 if k != (PLACEBO if t != PLACEBO else "sonnet55")]
            v = np.array([r["produced_scores"][k] for k in keys])
            acc[r["designer"]][t].append(avg_rank(v, keys.index(t)))
    return {d: {t: float(np.mean(v)) for t, v in m.items()} for d, m in acc.items()}


def leader_ranks(traj, disp):
    """traj (K+1, 13) in display order -> (rank13, rank12) of display position 0 at each k."""
    leader = disp[0]
    drop = disp.index(PLACEBO if leader != PLACEBO else "sonnet55")
    keep = [i for i in range(13) if i != drop]
    r13 = np.array([avg_rank(s, 0) for s in traj])
    r12 = np.array([avg_rank(s[keep], keep.index(0)) for s in traj])
    return r13, r12


def crossing(ks, ys, level):
    for i in range(1, len(ks)):
        if ys[i - 1] < level <= ys[i]:
            return float(ks[i - 1] + (level - ys[i - 1]) / (ys[i] - ys[i - 1]) * (ks[i] - ks[i - 1]))
    return None


def main():
    data = {p: load(p) for p in POOLS}
    base = {p: none_baseline(p) for p in POOLS}
    K = data["factual"]["greedy"].shape[1] - 1
    res = {"n_perm": NP, "n_boot": NB, "kmax": int(K), "grid": GRID}
    for scope in POOLS + ["pooled"]:
        pools = POOLS if scope == "pooled" else [scope]
        o = {}
        for meth in ("greedy", "naive", "random"):
            rows_k = []
            for k in range(K + 1):
                S, g13, g12, s1 = [], defaultdict(list), defaultdict(list), defaultdict(list)
                for p in pools:
                    D = data[p]
                    arr = D[meth] if meth != "random" else D["random"][:, 0]
                    for i in range(arr.shape[0]):
                        disp = str(D["display"][i]).split("|")
                        des = str(D["designer"][i])
                        S.append({"designer": des, "pool": p, "scores": np.round(arr[i, k], 5)})
                        r13, r12 = leader_ranks(np.round(arr[i, [0, k]], 5), disp)
                        g13[des].append(r13[0] - r13[1]); g12[des].append(r12[0] - r12[1])
                        s1[des].append(base[p][des][disp[0]] - r12[1])
                full = k in GRID or meth != "random"
                st = psi_stats(S, NP, NB, seed=1000 + k, null=full, boot=full)
                row = {"k": k} | {kk: st[kk] for kk in ("psi", "n", "n_designers")}
                if full:
                    row |= {"p_one_sided": st["p_one_sided"], "ci95_cluster_tau": st["ci95_cluster_tau"]}
                    row["detect"] = bool(st["ci95_cluster_tau"][0] > 0 and st["p_one_sided"] < 0.05)
                    row["claim"] = bool(row["detect"] and st["psi"] > 0.15)
                if k in GRID:
                    row["leader_gain13_vs_k0"] = cluster_boot_mean(g13, NB, seed=k)
                    row["leader_gain12_vs_k0"] = cluster_boot_mean(g12, NB, seed=k)
                    row["leader_gain12_vs_none_S1style"] = cluster_boot_mean(s1, NB, seed=k)
                if meth == "random":
                    reps = []
                    for rep in range(data[pools[0]]["random"].shape[1]):
                        Sr = []
                        for p in pools:
                            D = data[p]
                            for i in range(D["random"].shape[0]):
                                Sr.append({"designer": str(D["designer"][i]), "pool": p, "scores": np.round(D["random"][i, rep, k], 5)})
                        reps.append(psi_stats(Sr, null=False, boot=False)["psi"])
                    row["psi_over_replicates"] = {"mean": float(np.mean(reps)), "sd": float(np.std(reps, ddof=1)),
                                                  "min": float(np.min(reps)), "max": float(np.max(reps)), "n_rep": len(reps)}
                rows_k.append(row)
            ks = [r["k"] for r in rows_k]
            ps = [r["psi"] for r in rows_k]
            summ = {"k_at_psi_0.10": crossing(ks, ps, 0.10), "k_at_psi_0.15": crossing(ks, ps, 0.15)}
            if meth != "random":
                det = [r["k"] for r in rows_k if r["detect"]]
                clm = [r["k"] for r in rows_k if r["claim"]]
                summ["smallest_k_detect"] = det[0] if det else None
                summ["detect_holds_for_all_larger_k"] = bool(det and det == list(range(det[0], K + 1)))
                summ["smallest_k_full_claim"] = clm[0] if clm else None
                # greedy stall: sessions whose path stopped improving before k
                if meth == "greedy":
                    st_by_k = {}
                    for k in GRID[1:]:
                        n_st = 0
                        for p in pools:
                            arr = data[p]["greedy"]
                            n_st += int(np.sum(np.all(arr[:, k] == arr[:, k - 1], axis=1)))
                        st_by_k[k] = n_st
                    summ["n_sessions_no_swap_at_step_k"] = st_by_k
            o[meth] = {"by_k": rows_k, "summary": summ}
            print(scope, meth, summ, [(r["k"], round(r["psi"], 3), r.get("p_one_sided"), r.get("ci95_cluster_tau"))
                                      for r in rows_k if r["k"] in GRID], flush=True)
        res[scope] = o
    res["k0_reproduction_max_abs_error"] = {p: float(data[p]["repro_max_abs"].max()) for p in POOLS}
    dump(res, OUT / "p1_results.json")


if __name__ == "__main__":
    main()
