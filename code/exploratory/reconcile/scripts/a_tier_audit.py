"""Q2: audit implementation A for the set_active("confirmatory") bug. EXPLORATORY.
Imports the frozen metabench.analysis unchanged; runs the tier-dependent A functions twice with A's own seeds:
(i) default panel state (pilot globals; reproduces the frozen run) and (ii) after panel.set_active("confirmatory") with
tiers passed explicitly. Writes a_tier_audit_<pool>.json."""
import json, sys
sys.path.insert(0, "/path/to/metabench/run")
from metabench import panel, analysis as A
from common import UNB, OUT, dump

pool = sys.argv[1]
rows = A.read_jsonl(__import__("pathlib").Path(f"{UNB}/WORK_{pool}/results/benchmarks.jsonl"))
adir = "A_metabench_analysis_linux" if pool == "factual" else "A_metabench_analysis"
frozen = json.load(open(f"{UNB}/{pool}/endpoints/{adir}/endpoints.json"))


def run(label):
    tiers = dict(panel.TIERS)
    out = {"panel_active": panel.ACTIVE["name"], "tiers_used": tiers,
           "A_module_TIERS_is_panel_TIERS": A.TIERS is panel.TIERS,
           "displayed_keys_global": list(A.DISPLAYED_KEYS), "heldout_keys_global": list(A.HELDOUT_KEYS)}
    out["primary_by_identity"] = {}
    for ident in ["blinded", "true", "false", "pooled"]:
        r = A.primary_endpoint(rows, n_perm=10000, n_boot=10000, seed=0, tiers=tiers,
                               identity_arm=None if ident == "pooled" else ident)
        out["primary_by_identity"][ident] = {k: r.get(k) for k in ["n", "n_designers", "psi", "z", "p_one_sided", "p_two_sided",
                                                                   "null_mean_z", "null_sd_z", "ci95_cluster_tau", "ci95_bench_tau"]}
        print(label, ident, out["primary_by_identity"][ident]["psi"], out["primary_by_identity"][ident]["p_one_sided"],
              out["primary_by_identity"][ident]["null_mean_z"], flush=True)
    out["leader_rank_gain"] = {}
    for i, arm in enumerate(A.LEADER_ARMS):
        r = A.leader_rank_gain(rows, arm, 5000, 5000, 10 + i, tiers)
        out["leader_rank_gain"][arm] = {k: r.get(k) for k in ["n", "gain", "p_perm_one_sided", "ci95_cluster", "null_mean", "null_sd"]}
    # named sham only (identity true / false), which is where the tier null matters
    for ident in ["true", "false"]:
        r = A.leader_rank_gain(rows, "sham", 5000, 5000, 10, tiers, identity_arm=ident)
        out["leader_rank_gain"][f"sham|{ident}"] = {k: r.get(k) for k in ["n", "gain", "p_perm_one_sided", "ci95_cluster", "null_mean", "null_sd"]}
    return out


res = {"pool": pool, "frozen": {
    "primary_by_identity": {k: {x: v.get(x) for x in ["psi", "p_one_sided", "null_mean_z", "null_sd_z", "ci95_cluster_tau"]}
                            for k, v in frozen["primary_by_identity_arm"].items()},
    "leader_rank_gain": {k: {x: v.get(x) for x in ["gain", "p_perm_one_sided", "ci95_cluster", "null_mean"]}
                         for k, v in frozen["secondary"]["leader_rank_gain"].items()},
    "holm": frozen["secondary"]["holm"]}}
res["rerun_pilot_globals"] = run("pilot")
panel.set_active("confirmatory")
res["rerun_confirmatory_globals"] = run("confirmatory")
# Holm with the corrected S1 p (other three p unchanged: they do not use tiers)
h = frozen["secondary"]["holm"]
ps = [res["rerun_confirmatory_globals"]["leader_rank_gain"]["sham"]["p_perm_one_sided"],
      h["self_rank_true_vs_blinded"][0], h["inverted_tau_minus_none"][0], h["true_minus_none_tau"][0]]
res["holm_with_confirmatory_tiers"] = dict(zip(list(h), zip(ps, A.holm(ps))))
dump(res, f"{OUT}/a_tier_audit_{pool}.json")
print("done", pool)
