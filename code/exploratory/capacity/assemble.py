"""Collect the per-task JSON outputs into results.json and print the markdown tables used in REPORT.md."""
from __future__ import annotations

import json

import numpy as np

from common import OUT, K13, dump

POOLS = ["factual", "math", "code"]


def load(name):
    return json.load(open(OUT / name))


def f(x, nd=3):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


def ci(c, nd=3):
    return f"[{f(c[0], nd)}, {f(c[1], nd)}]"


def main():
    R = {"label": "EXPLORATORY post-unblinding analysis (capacity and noise floor); see REPORT.md",
         "oracle": {}, "oracle_holdout": {}, "instructed_vs_oracle": load("instructed_vs_oracle.json"),
         "controls": {}, "named_sham": {}}
    for p in POOLS:
        o = load(f"oracle_{p}.json")
        for t in o["targets"].values():
            for lab in ("unconstrained", "constrained"):
                t[lab].pop("items_rank_solution", None)
        R["oracle"][p] = o
        R["oracle_holdout"][p] = load(f"oracle_holdout_{p}.json")
        R["controls"][p] = load(f"controls_{p}.json")
        R["named_sham"][p] = load(f"named_sham_{p}.json")
    dump(R, OUT / "results.json")

    print("\n## C4 oracle per target (unconstrained / constrained margin; weighted; holdout)\n")
    print("| target | " + " | ".join(f"{p} ref rank | {p} margin U / C / W | {p} heldout margin" for p in POOLS) + " |")
    for t in K13:
        cells = []
        for p in POOLS:
            x = R["oracle"][p]["targets"][t]; h = R["oracle_holdout"][p]["targets"][t]
            cells.append(f"{x['reference_rank']:.0f} | {f(x['unconstrained']['margin'])} / {f(x['constrained']['margin'])} / "
                         f"{f(x['unconstrained']['weighted_margin'])} | {f(h['margin_heldout_samples'])} (rank {h['rank_heldout_samples']:.0f})")
        print(f"| {t} | " + " | ".join(cells) + " |")
    for p in POOLS:
        o = R["oracle"][p]["targets"]
        dz = [o[t] for t in K13 if t != "placebo_sonnet55"]
        print(p, "n first U", sum(x["unconstrained"]["can_be_first"] for x in dz), "C", sum(x["constrained"]["can_be_first"] for x in dz),
              "mean gain U", np.mean([x["unconstrained"]["rank_gain_vs_reference"] for x in dz]),
              "min margin U", min(x["unconstrained"]["margin"] for x in dz), "min margin C", min(x["constrained"]["margin"] for x in dz),
              "median margin", np.median([x["unconstrained"]["margin"] for x in dz]),
              "holdout min", min(R["oracle_holdout"][p]["targets"][t]["margin_heldout_samples"] for t in K13 if t != "placebo_sonnet55"),
              "holdout first", sum(R["oracle_holdout"][p]["targets"][t]["rank_heldout_samples"] == 1.0 for t in K13 if t != "placebo_sonnet55"),
              "ref spread top-bottom", max(R["oracle"][p]["reference_scores"].values()) - min(R["oracle"][p]["reference_scores"].values()))
        print("  categories", R["oracle"][p]["categories"])

    print("\n## Instructed vs oracle\n")
    I = R["instructed_vs_oracle"]
    for p in POOLS + ["pooled"]:
        x = I[p]
        if p == "pooled":
            print(p, x)
            continue
        print(f"| {p} | {x['n']} / {x['n_designers']} | {f(x['gain_designer_avg'],2)} {ci(x['gain_ci95_cluster'],2)} | "
              f"{f(x['headroom_unconstrained_designer_avg'],2)} | {f(x['fraction_of_oracle_unconstrained'],3)} {ci(x['fraction_ci95_cluster'],3)} | "
              f"{x['n_target_first']}/{x['n']} ({f(x['share_target_first_designer_avg'],2)} {ci(x['share_first_ci95_cluster'],2)}) | "
              f"{f(x['none_baseline_share_first_designer_avg'],3)} | {f(x['A_implementation_gain_reproduced'],3)} |")
    for p in POOLS:
        print(p, "per target", {t: (v["n"], round(v["mean_gain"], 2), round(v["mean_headroom"], 2), v["n_first"],
                                    round(v["mean_produced_margin"], 3), round(v["oracle_margin"], 3)) for t, v in I[p]["per_target"].items()})

    print("\n## C3\n")
    for p in POOLS:
        c = R["controls"][p]["C3_psi"]; tr = R["controls"][p]["C3_tau_to_reference"]
        print(p, c["n_sessions"], c["n_designers"], "same", {k: round(v, 4) for k, v in c["same_subset_all_sessions"].items()},
              "indep", {k: round(v, 4) for k, v in c["independent_subset_per_session"].items()},
              "ref", round(c["reference_ranking_psi"], 4), "llm", round(c["llm_psi_recomputed"], 4), "pct", c["llm_psi_percentile_in_independent_null"])
        print("  random tau-ref", {k: round(v, 3) for k, v in tr["random_subsets"].items()})
        for arm, v in tr["llm_by_arm"].items():
            print(f"  | {arm} | {v['n']} / {v['n_designers']} | {f(v['mean_tau'])} {ci(v['ci95_cluster'])} | {f(v['minus_random_mean'])} | "
                  f"{f(v['share_below_random_q05'],2)} | {f(v['share_above_random_q95'],2)} |")

    print("\n## C5\n")
    for p in POOLS:
        c = R["controls"][p]["C5"]
        print(f"| {p} | {c['n_benchmarks']} / {c['n_designers']} / {c['n_pairs']} | {f(c['overall_mean_of_designer_means'])} {ci(c['ci95_designer_bootstrap'])} | "
              f"{f(c['between_designer_none_pairs']['mean'])} | {f(c['random_subset_pairs']['mean'])} (sd {f(c['random_subset_pairs']['sd'])}) | {c['prereg_fail_if_below_0.5']} |")
        print("   ", {d: (v["n_benchmarks"], round(v["mean_tau"], 3)) for d, v in c["per_designer"].items()})

    print("\n## C2\n")
    for p in POOLS:
        c = R["controls"][p]["C2"]
        print(p, "N1", {k: round(v, 4) for k, v in c["noise_N1_sim_pool"].items()}, "N3", {k: round(v, 4) for k, v in c["noise_N3_empirical_pool"].items()},
              "ref", round(c["reference_abs_delta_full_pool"], 4), "rand adj", c["random_subset_share_adjacent"])
        for arm in ["none", "true_blinded", "true_named", "sham", "inverted", "narrative", "instructed"]:
            v = c["by_arm"][arm]
            print(f"  | {arm} | {v['n']} | {f(v['mean_abs_delta'],4)} {ci(v['mean_abs_delta_ci95_cluster'],4)} | {f(v['share_exceed_N1_q95'],3)} {ci(v['share_exceed_N1_ci95'],2)} | "
                  f"{f(v['share_exceed_N2_q95'],3)} {ci(v['share_exceed_N2_ci95'],2)} | {f(v['share_exceed_N3_q95'],3)} | {f(v['share_adjacent_or_tied'],2)} {ci(v['share_adjacent_ci95'],2)} | {f(v['mean_n_models_between'],2)} |")

    print("\n## Named sham\n")
    for p in POOLS:
        for ident in ("true", "false", "blinded"):
            x = R["named_sham"][p][f"sham_{ident}"]
            print(f"| {p} | sham/{ident} | {x['n']} / {x['n_designers']} | {f(x['tau_displayed_vs_reference']['mean_designer_avg'])} {ci(x['tau_displayed_vs_reference']['ci95_cluster'])} | "
                  f"{f(x['psi'])} | {f(x['null_mean_tau'])} (sd_z {f(x['null_sd_z'])}) | {f(x['excess_z_designer_avg'])} {ci(x['excess_z_ci95_cluster'])} | {f(x['p_one_sided'],4)} | "
                  f"{f(x['tau_produced_vs_reference_designer_avg'])} | {x['c7_violations'] if ident != 'blinded' else '-'} |")


if __name__ == "__main__":
    main()
