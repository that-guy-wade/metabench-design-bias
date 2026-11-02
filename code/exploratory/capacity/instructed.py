"""Task 2: instructed-arm target rank gains as a fraction of the C4 oracle bound (EXPLORATORY).

Per valid instructed benchmark with target t (drawn uniformly from the 13 displayed keys, incl. the placebo and the
designer itself; the brief told the designer the final benchmark "must place <label of t> first"):
  produced rank r_t: rank of t among K13 (12 designers + placebo) by produced_scores, 1 = best, ties averaged;
  baseline b_t: mean rank of t among K13 in the same designer's valid none-arm benchmarks;
  gain = b_t - r_t; oracle headroom = b_t - oracle best rank of t (oracle_<pool>.json, unconstrained and constrained);
  fraction = designer-averaged gain / designer-averaged headroom (ratio of means; designer-cluster bootstrap CI with
  paired resampling).  Also the reference-rank baseline (full-pool rank), the share of benchmarks with t at rank 1,
  the margin achieved (score_t - best other K13 score) vs the oracle margin, and a reproduction of implementation A's
  gain (metabench.analysis.leader_rank_gain, which ranks the instructed row on its 13 displayed_order keys against a
  12-key none baseline).
"""
from __future__ import annotations

import json
from collections import defaultdict

import numpy as np

from common import K13, OUT, bench_rows, ranks13, designer_avg, cluster_boot, ratio_cluster_boot, dump
from metabench import analysis as A_impl


def main():
    res = {}
    pooled = {k: defaultdict(list) for k in ("gain", "head_u", "head_c", "first", "gain_ref", "head_ref", "bfirst")}
    for pool in ("factual", "math", "code"):
        orc = json.load(open(OUT / f"oracle_{pool}.json"))["targets"]
        rows = bench_rows(pool)
        base = defaultdict(lambda: defaultdict(list))
        for r in rows:
            if r["info_arm"] == "none":
                for k, v in ranks13(r["produced_scores"]).items():
                    base[r["designer"]][k].append(v)
        ins = [r for r in rows if r["info_arm"] == "instructed"]
        per = []
        g = {k: defaultdict(list) for k in pooled}
        by_target = defaultdict(lambda: defaultdict(list))
        for r in ins:
            t, d = r["target_model"], r["designer"]
            rk = ranks13(r["produced_scores"])[t]
            b = float(np.mean(base[d][t]))
            ref_rank = orc[t]["reference_rank"]
            ou, oc = orc[t]["unconstrained"]["best_rank"], orc[t]["constrained"]["best_rank"]
            ps = r["produced_scores"]
            margin = ps[t] - max(ps[k] for k in K13 if k != t)
            b_first = float(np.mean([v == 1.0 for v in base[d][t]]))
            row = {"none_baseline_share_first": b_first, "session_id": r["session_id"], "designer": d, "target": t, "self_target": t == d,
                   "produced_rank": rk, "none_baseline_rank": b, "reference_rank": ref_rank, "gain": b - rk,
                   "oracle_rank_unconstrained": ou, "oracle_rank_constrained": oc,
                   "headroom_unconstrained": b - ou, "headroom_constrained": b - oc,
                   "produced_margin": margin, "oracle_margin_unconstrained": orc[t]["unconstrained"]["margin"],
                   "n_score_requests": r["n_score_requests"], "n_edits": r["n_edits"], "scoring_rule": r["scoring_rule"]}
            per.append(row)
            for key, val in (("gain", b - rk), ("head_u", b - ou), ("head_c", b - oc), ("first", float(rk == 1.0)),
                             ("gain_ref", ref_rank - rk), ("head_ref", ref_rank - ou), ("bfirst", b_first)):
                g[key][d].append(val); pooled[key][d].append(val)
            for key, val in (("gain", b - rk), ("head_u", b - ou), ("first", float(rk == 1.0)), ("margin", margin),
                             ("oracle_margin", orc[t]["unconstrained"]["margin"])):
                by_target[t][key].append(val)
        a_gain = A_impl.leader_rank_gain(rows, "instructed", n_perm=10, n_boot=10)["gain"]
        n_first = sum(1 for p in per if p["produced_rank"] == 1.0)
        res[pool] = {
            "n": len(per), "n_designers": len(g["gain"]),
            "gain_designer_avg": designer_avg(g["gain"]), "gain_ci95_cluster": cluster_boot(g["gain"], 5000, 1),
            "headroom_unconstrained_designer_avg": designer_avg(g["head_u"]),
            "headroom_constrained_designer_avg": designer_avg(g["head_c"]),
            "fraction_of_oracle_unconstrained": designer_avg(g["gain"]) / designer_avg(g["head_u"]),
            "fraction_ci95_cluster": ratio_cluster_boot(g["gain"], g["head_u"], 5000, 2),
            "fraction_of_oracle_constrained": designer_avg(g["gain"]) / designer_avg(g["head_c"]),
            "gain_vs_reference_rank_designer_avg": designer_avg(g["gain_ref"]),
            "fraction_vs_reference_baseline": designer_avg(g["gain_ref"]) / designer_avg(g["head_ref"]),
            "share_target_first": n_first / len(per), "n_target_first": n_first,
            "share_target_first_designer_avg": designer_avg(g["first"]),
            "share_first_ci95_cluster": cluster_boot(g["first"], 5000, 3),
            "none_baseline_share_first_designer_avg": designer_avg(g["bfirst"]),
            "share_oracle_can_make_first": float(np.mean([orc[p["target"]]["unconstrained"]["can_be_first"] for p in per])),
            "A_implementation_gain_reproduced": a_gain,
            "per_designer": {d: {"n": len(v), "mean_gain": float(np.mean(v)), "mean_headroom": float(np.mean(g["head_u"][d])),
                                 "n_target_first": int(sum(g["first"][d])),
                                 "fraction_of_oracle": float(np.mean(v) / np.mean(g["head_u"][d]))} for d, v in g["gain"].items()},
            "per_target": {t: {"n": len(v["gain"]), "mean_gain": float(np.mean(v["gain"])),
                               "mean_headroom": float(np.mean(v["head_u"])), "n_first": int(sum(v["first"])),
                               "mean_produced_margin": float(np.mean(v["margin"])),
                               "oracle_margin": float(v["oracle_margin"][0])} for t, v in sorted(by_target.items())},
            "per_benchmark": per,
        }
        print(pool, {k: res[pool][k] for k in ("n", "gain_designer_avg", "gain_ci95_cluster", "headroom_unconstrained_designer_avg",
                                               "fraction_of_oracle_unconstrained", "fraction_ci95_cluster", "n_target_first",
                                               "A_implementation_gain_reproduced")})
    # pooled across pools: designer is the cluster (each designer contributes its rows from all three pools)
    res["pooled"] = {"cluster_unit": "designer (12 clusters, rows from all pools)",
                     "n": sum(len(v) for v in pooled["gain"].values()),
                     "gain": designer_avg(pooled["gain"]), "gain_ci95_cluster": cluster_boot(pooled["gain"], 5000, 4),
                     "headroom_unconstrained": designer_avg(pooled["head_u"]),
                     "fraction_of_oracle_unconstrained": designer_avg(pooled["gain"]) / designer_avg(pooled["head_u"]),
                     "fraction_ci95_cluster": ratio_cluster_boot(pooled["gain"], pooled["head_u"], 5000, 5),
                     "share_target_first": float(np.mean([x for v in pooled["first"].values() for x in v])),
                     "share_first_ci95_cluster": cluster_boot(pooled["first"], 5000, 6),
                     "none_baseline_share_first": designer_avg(pooled["bfirst"])}
    print("pooled", {k: v for k, v in res["pooled"].items()})
    dump(res, OUT / "instructed_vs_oracle.json")


if __name__ == "__main__":
    main()
