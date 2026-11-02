"""C3 random-subset control, C5 consistency ceiling, C2 placebo noise (EXPLORATORY, post-unblinding).

Usage: python controls.py <pool>   ->  controls_<pool>.json

C3  200 uniform random 100-item subsets of the 2,000-item pool (equal weights, scoring as scoring.benchmark_scores:
    per-key mean of per-item accuracy, NaN items skipped per key).
    (i)  same-subset Psi: each subset's ranking is compared with every valid sham/blinded session's displayed_order
         (13 keys incl. placebo, exactly the primary's key set); tau-b -> Fisher z (clipped at |tau| 0.999 as in A) ->
         mean within designer -> mean across designers -> tanh.  One Psi per subset (200 values).
    (ii) independent-subset Psi: 2,000 replicates in which every session gets its own fresh random subset.
    Also the Psi of the full-pool reference ranking against the registered displays, and the LLM Psi recomputed.
    tau to reference: tau-b(subset scores, reference scores) over the 12 designer keys; LLM benchmarks: tau-b(produced,
    reference) over the same 12 keys, by arm (designer-averaged raw tau, designer-cluster bootstrap CI).
C5  per designer, tau-b over the 12 designer keys between produced_scores of every pair of that designer's valid
    none/blinded benchmarks; designer mean of pair taus; overall = mean of designer means; CI = bootstrap over designers
    (pairs within a designer share benchmarks, so only designers are resampled).  Companions: between-designer none
    pairs, and pairs of independent random subsets (the ceiling a non-designing random selector would show).
C2  |produced(sonnet55) - produced(placebo_sonnet55)| per valid benchmark, by arm.  Replicate noise, three definitions:
    N1 (pool, simulated): 200 random 100-item subsets x 200 draws; per item the true rate is the pooled reference rate
       of the two copies (10 samples); each copy's score = mean over items of Binomial(5, p_i)/5; noise = |difference|.
    N2 (benchmark-specific, simulated): as N1 but on that benchmark's own item ids (unweighted; edited items use the
       unedited item's rate), 2,000 draws per benchmark; the criterion is |delta| <= that benchmark's own q95.
    N3 (pool, empirical): |sonnet55 - placebo| on 10,000 random 100-item subsets of the actual reference samples.
    Adjacent/tied: no other K13 key has a produced score strictly between the two copies.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from itertools import combinations

import numpy as np

from common import (K12, K13, PLACEBO, OUT, bench_rows, reference_matrix, subset_scores, kendall_tau_b, fisher_z,
                    order_to_scores, designer_avg, cluster_boot, tau_b_vectorised, dump)

ARMS = ["none", "true_named", "true_blinded", "sham", "inverted", "narrative", "instructed"]


def summarise(v):
    v = np.asarray(v, float)
    return {"n": int(len(v)), "mean": float(np.mean(v)), "sd": float(np.std(v, ddof=1)) if len(v) > 1 else float("nan"),
            "q025": float(np.percentile(v, 2.5)), "q05": float(np.percentile(v, 5)), "median": float(np.median(v)),
            "q95": float(np.percentile(v, 95)), "q975": float(np.percentile(v, 97.5))}


def psi_from(taus_by_session, designers):
    byd = defaultdict(list)
    for t, d in zip(taus_by_session, designers):
        byd[d].append(fisher_z(float(t)))
    return float(np.tanh(designer_avg(byd)))


def main(pool):
    rng = np.random.default_rng({"factual": 11, "math": 22, "code": 33}[pool])
    allkeys = K13 + ["heldout_sonnet46", "heldout_gpt54", "heldout_gemini35flash", "heldout_grok420"]
    items, A, N, C = reference_matrix(pool, allkeys)
    col = {k: j for j, k in enumerate(allkeys)}
    nI = len(items)
    ref = np.nanmean(A, 0)
    rows = bench_rows(pool)
    out = {"pool": pool}

    # ---------------- C3 ----------------
    subs = [rng.choice(nI, 100, replace=False) for _ in range(200)]
    sub_scores = np.array([subset_scores(A, s) for s in subs])           # (200, 17)
    sham = [r for r in rows if r["info_arm"] == "sham" and r["identity_arm"] == "blinded" and r.get("displayed_order")]
    keys_l = [list(r["displayed_order"]) for r in sham]
    disp_l = [np.array([-float(i) for i in range(len(k))]) for k in keys_l]
    des = [r["designer"] for r in sham]
    # (i) same subset for all sessions
    taus = np.array([[tau_b_vectorised(sub_scores[b, [col[k] for k in ks]], d[None, :])[0]
                      for ks, d in zip(keys_l, disp_l)] for b in range(200)])
    psi_i = [psi_from(taus[b], des) for b in range(200)]
    # (ii) independent subset per session
    psi_ii = []
    for b in range(2000):
        tt = []
        for ks, d in zip(keys_l, disp_l):
            sc = subset_scores(A, rng.choice(nI, 100, replace=False))[[col[k] for k in ks]]
            tt.append(tau_b_vectorised(sc, d[None, :])[0])
        psi_ii.append(psi_from(tt, des))
    psi_ref = psi_from([tau_b_vectorised(ref[[col[k] for k in ks]], d[None, :])[0] for ks, d in zip(keys_l, disp_l)], des)
    llm_t = [kendall_tau_b(r["produced_scores"], order_to_scores(r["displayed_order"]), ks) for r, ks in zip(sham, keys_l)]
    psi_llm = psi_from(llm_t, des)
    out["C3_psi"] = {"n_sessions": len(sham), "n_designers": len(set(des)),
                     "same_subset_all_sessions": summarise(psi_i), "independent_subset_per_session": summarise(psi_ii),
                     "reference_ranking_psi": psi_ref, "llm_psi_recomputed": psi_llm,
                     "llm_psi_percentile_in_independent_null": float(np.mean(np.array(psi_ii) < psi_llm))}
    # tau to reference over K12
    refd = {k: ref[col[k]] for k in K12}
    sub_tau_ref = [kendall_tau_b({k: sub_scores[b, col[k]] for k in K12}, refd, K12) for b in range(200)]
    rs = summarise(sub_tau_ref)
    by_arm = {}
    for arm in ARMS:
        byd = defaultdict(list)
        for r in rows:
            if r["info_arm"] == arm:
                byd[r["designer"]].append(kendall_tau_b(r["produced_scores"], r["reference_scores"], K12))
        allv = [x for v in byd.values() for x in v]
        m = designer_avg(byd)
        by_arm[arm] = {"n": len(allv), "n_designers": len(byd), "mean_tau": m, "ci95_cluster": cluster_boot(byd, 4000, 1),
                       "minus_random_mean": m - rs["mean"],
                       "share_below_random_q05": float(np.mean(np.array(allv) < rs["q05"])),
                       "share_above_random_q95": float(np.mean(np.array(allv) > rs["q95"]))}
    out["C3_tau_to_reference"] = {"random_subsets": rs, "llm_by_arm": by_arm}

    # ---------------- C5 ----------------
    none = [r for r in rows if r["info_arm"] == "none"]
    byd_none = defaultdict(list)
    for r in none:
        byd_none[r["designer"]].append(r)
    within = {}
    for d, rr in byd_none.items():
        within[d] = [kendall_tau_b(a["produced_scores"], b["produced_scores"], K12) for a, b in combinations(rr, 2)]
    dmeans = {d: float(np.mean(v)) for d, v in within.items() if v}
    boot = []
    ds = list(dmeans)
    for _ in range(5000):
        boot.append(np.mean([dmeans[d] for d in rng.choice(ds, len(ds))]))
    between = [kendall_tau_b(a["produced_scores"], b["produced_scores"], K12)
               for a, b in combinations(none, 2) if a["designer"] != b["designer"]]
    rand_pairs = []
    for _ in range(2000):
        s1 = subset_scores(A, rng.choice(nI, 100, replace=False)); s2 = subset_scores(A, rng.choice(nI, 100, replace=False))
        rand_pairs.append(kendall_tau_b({k: s1[col[k]] for k in K12}, {k: s2[col[k]] for k in K12}, K12))
    overall = float(np.mean(list(dmeans.values())))
    out["C5"] = {"per_designer": {d: {"n_benchmarks": len(byd_none[d]), "n_pairs": len(within[d]), "mean_tau": dmeans[d],
                                      "min_tau": float(np.min(within[d])), "max_tau": float(np.max(within[d]))} for d in dmeans},
                 "overall_mean_of_designer_means": overall,
                 "ci95_designer_bootstrap": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
                 "n_benchmarks": len(none), "n_designers": len(dmeans),
                 "n_pairs": int(sum(len(v) for v in within.values())),
                 "prereg_fail_if_below_0.5": bool(overall < 0.5),
                 "between_designer_none_pairs": summarise(between),
                 "random_subset_pairs": summarise(rand_pairs)}

    # ---------------- C2 ----------------
    a, b = col["sonnet55"], col[PLACEBO]
    ii = {x: i for i, x in enumerate(items)}
    pc = (C[:, a] + C[:, b]) / np.maximum(N[:, a] + N[:, b], 1)          # pooled rate over the 10 samples
    pc_ok = (N[:, a] + N[:, b]) > 0

    def sim_noise(idx, n_draw):
        idx = idx[pc_ok[idx]]
        p = pc[idx]
        x1 = rng.binomial(5, p, size=(n_draw, len(p))).mean(1) / 5
        x2 = rng.binomial(5, p, size=(n_draw, len(p))).mean(1) / 5
        return np.abs(x1 - x2)
    n1 = np.concatenate([sim_noise(s, 200) for s in subs])
    n3 = []
    for _ in range(10000):
        s = rng.choice(nI, 100, replace=False)
        sc = subset_scores(A, s)
        n3.append(abs(sc[a] - sc[b]))
    n3 = np.array(n3)
    # adjacency on random subsets (empirical baseline)
    adj_rand = []
    for s in subs:
        sc = subset_scores(A, s)
        lo_, hi_ = sorted([sc[a], sc[b]])
        adj_rand.append(int(sum(1 for k in K13 if k not in ("sonnet55", PLACEBO) and lo_ < sc[col[k]] < hi_) == 0))
    q95_n1, q95_n3 = float(np.percentile(n1, 95)), float(np.percentile(n3, 95))
    per_arm = defaultdict(lambda: defaultdict(list))
    for r in rows:
        ps = r["produced_scores"]
        dlt = abs(ps["sonnet55"] - ps[PLACEBO])
        idx = np.array([ii[x] for x in r["items"]])
        q95_n2 = float(np.percentile(sim_noise(idx, 2000), 95))
        lo_, hi_ = sorted([ps["sonnet55"], ps[PLACEBO]])
        between_n = sum(1 for k in K13 if k not in ("sonnet55", PLACEBO) and lo_ < ps[k] < hi_)
        g = per_arm[r["info_arm"]]
        g["delta"].append(dlt); g["designer"].append(r["designer"])
        g["exceed_n1"].append(dlt > q95_n1); g["exceed_n2"].append(dlt > q95_n2); g["exceed_n3"].append(dlt > q95_n3)
        g["adjacent"].append(between_n == 0); g["n_between"].append(between_n)
        g["weighted_or_edited"].append(bool(r["edited_items"]) or r["scoring_rule"] != "accuracy")
    c2 = {}
    for arm, g in per_arm.items():
        byd = defaultdict(list)
        for d, x in zip(g["designer"], g["delta"]):
            byd[d].append(x)
        n = len(g["delta"])

        def wilson(k, n):
            from statsmodels.stats.proportion import proportion_confint
            lo, hi = proportion_confint(k, n, method="wilson")
            return [float(lo), float(hi)]
        c2[arm] = {"n": n, "n_designers": len(byd), "mean_abs_delta": float(np.mean(g["delta"])),
                   "mean_abs_delta_ci95_cluster": cluster_boot(byd, 4000, 2),
                   "median_abs_delta": float(np.median(g["delta"])), "max_abs_delta": float(np.max(g["delta"])),
                   "share_exceed_N1_q95": float(np.mean(g["exceed_n1"])), "share_exceed_N1_ci95": wilson(sum(g["exceed_n1"]), n),
                   "share_exceed_N2_q95": float(np.mean(g["exceed_n2"])), "share_exceed_N2_ci95": wilson(sum(g["exceed_n2"]), n),
                   "share_exceed_N3_q95": float(np.mean(g["exceed_n3"])), "share_exceed_N3_ci95": wilson(sum(g["exceed_n3"]), n),
                   "share_adjacent_or_tied": float(np.mean(g["adjacent"])), "share_adjacent_ci95": wilson(sum(g["adjacent"]), n),
                   "mean_n_models_between": float(np.mean(g["n_between"])),
                   "n_weighted_or_edited": int(sum(g["weighted_or_edited"]))}
    out["C2"] = {"noise_N1_sim_pool": summarise(n1), "noise_N3_empirical_pool": summarise(n3),
                 "reference_abs_delta_full_pool": float(abs(ref[a] - ref[b])),
                 "random_subset_share_adjacent": float(np.mean(adj_rand)), "by_arm": c2}
    dump(out, OUT / f"controls_{pool}.json")
    print(pool, "done")


if __name__ == "__main__":
    main(sys.argv[1])
