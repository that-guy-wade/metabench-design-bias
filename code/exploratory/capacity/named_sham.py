"""Task 6: sham-arm Psi under real names with a CORRECT within-tier randomisation null (EXPLORATORY).

Implementation A computed the named-arm null with the pilot TIERS (it never calls panel.set_active("confirmatory")),
so its named-arm p-values are invalid.  Here:

(a) tau-b(displayed_order, reference ranking) per valid sham session, over the session's displayed keys (12 under names,
    13 with the placebo under pseudonyms): how informative is the displayed order about the truth?
(b) Psi = tanh(designer-average of within-designer mean Fisher-z tau-b(produced_scores, displayed_order)) for sham/true
    and sham/false; null: 10,000 re-draws of every session's displayed order with metabench.arms.draw_displayed_order
    (named=True, confirmatory TIERS: shuffles within reputation tiers, tier blocks best-first), recomputing Psi*.
    p_one = (1 + #{Psi*_z >= Psi_z}) / (1 + 10,000).  Excess = per-session z minus that session's own null-mean z,
    designer-averaged, with a designer-cluster bootstrap CI (5,000).
(c) the same for sham/blinded with named=False (uniform permutations of the 13 keys) -> must reproduce the frozen
    primary (+0.031 / -0.022 / -0.000).
Also: C7 check (no displayed named order puts a tier-3 model above a tier-1 model) and tau(produced, reference).
"""
from __future__ import annotations

import sys
from collections import defaultdict

import numpy as np

from common import (OUT, TIERS, bench_rows, kendall_tau_b, fisher_z, order_to_scores, designer_avg, cluster_boot,
                    draw_displayed_order, dump)

N_PERM = 10000


def analyse(rows, named, seed):
    rng = np.random.default_rng(seed)
    S = len(rows)
    keys_l = [[k for k in r["displayed_order"] if k in r["produced_scores"]] for r in rows]
    des = [r["designer"] for r in rows]
    obs_t = np.array([kendall_tau_b(r["produced_scores"], order_to_scores(r["displayed_order"]), ks)
                      for r, ks in zip(rows, keys_l)])
    obs_z = np.array([fisher_z(float(t)) for t in obs_t])
    disp_ref = np.array([kendall_tau_b(order_to_scores(r["displayed_order"]), r["reference_scores"], ks)
                         for r, ks in zip(rows, keys_l)])
    prod_ref = np.array([kendall_tau_b(r["produced_scores"], r["reference_scores"], ks) for r, ks in zip(rows, keys_l)])
    # null: per session, N_PERM orders; vectorised tau-b against produced scores
    null_z = np.empty((S, N_PERM))
    for s, (r, ks) in enumerate(zip(rows, keys_l)):
        sc = np.array([r["produced_scores"][k] for k in ks])
        iu, ju = np.triu_indices(len(ks), 1)
        ss = np.sign(sc[iu] - sc[ju])
        n0 = len(iu); n1 = np.sum(ss == 0)
        pos = np.empty((N_PERM, len(ks)))
        kidx = {k: i for i, k in enumerate(ks)}
        for b in range(N_PERM):
            order = draw_displayed_order(rng, r["displayed_order"], named, TIERS)
            for p_, k in enumerate(order):
                if k in kidx:
                    pos[b, kidx[k]] = -p_
        rs = np.sign(pos[:, iu] - pos[:, ju])
        t = (rs @ ss) / np.sqrt((n0 - n1) * n0)
        null_z[s] = np.arctanh(np.clip(t, -0.999, 0.999))
    # designer-average per draw
    ud = sorted(set(des))
    W = np.zeros((len(ud), S))
    for s, d in enumerate(des):
        W[ud.index(d), s] = 1.0
    W /= W.sum(1, keepdims=True)
    null_psi_z = (W @ null_z).mean(0)
    psi_z = float((W @ obs_z).mean())
    p_one = float((1 + np.sum(null_psi_z >= psi_z - 1e-12)) / (1 + N_PERM))
    excess = obs_z - null_z.mean(1)
    byd_ex, byd_z, byd_dr, byd_pr = (defaultdict(list) for _ in range(4))
    for s, d in enumerate(des):
        byd_ex[d].append(excess[s]); byd_z[d].append(obs_z[s]); byd_dr[d].append(disp_ref[s]); byd_pr[d].append(prod_ref[s])
    ex = designer_avg(byd_ex)
    # C7: tier-3 above tier-1?
    c7 = 0
    for r in rows:
        tiers = [TIERS.get(k, 99) for k in r["displayed_order"]]
        if any(tiers[i] == 3 and any(t == 1 for t in tiers[i + 1:]) for i in range(len(tiers))):
            c7 += 1
    return {"n": S, "n_designers": len(ud), "named_null": named,
            "tau_displayed_vs_reference": {"mean_designer_avg": designer_avg(byd_dr), "ci95_cluster": cluster_boot(byd_dr, 4000, seed),
                                           "min": float(disp_ref.min()), "max": float(disp_ref.max())},
            "tau_produced_vs_reference_designer_avg": designer_avg(byd_pr),
            "psi": float(np.tanh(psi_z)), "psi_z": psi_z, "psi_ci95_cluster_z": cluster_boot(byd_z, 4000, seed + 1),
            "null_mean_z": float(null_psi_z.mean()), "null_sd_z": float(null_psi_z.std()),
            "null_mean_tau": float(np.tanh(null_psi_z.mean())),
            "null_q95_z": float(np.percentile(null_psi_z, 95)),
            "p_one_sided": p_one,
            "excess_z_designer_avg": ex, "excess_z_ci95_cluster": cluster_boot(byd_ex, 4000, seed + 2),
            "excess_tau_approx": float(np.tanh(psi_z) - np.tanh(null_psi_z.mean())),
            "per_designer_excess_z": {d: float(np.mean(v)) for d, v in byd_ex.items()},
            "c7_violations": c7}


def main(pool):
    rows = [r for r in bench_rows(pool) if r["info_arm"] == "sham" and r.get("displayed_order")]
    res = {"pool": pool}
    for i, ident in enumerate(["true", "false", "blinded"]):
        rr = [r for r in rows if r["identity_arm"] == ident]
        res[f"sham_{ident}"] = analyse(rr, named=(ident != "blinded"), seed=100 + i)
        x = res[f"sham_{ident}"]
        print(pool, ident, "n", x["n"], "psi %.3f" % x["psi"], "null_mean_tau %.3f" % x["null_mean_tau"], "p", x["p_one_sided"],
              "excess_z %.3f" % x["excess_z_designer_avg"], x["excess_z_ci95_cluster"],
              "disp~ref %.3f" % x["tau_displayed_vs_reference"]["mean_designer_avg"], flush=True)
    dump(res, OUT / f"named_sham_{pool}.json")


if __name__ == "__main__":
    main(sys.argv[1])
