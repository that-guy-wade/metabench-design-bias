"""Assemble results.json and markdown tables (tables.md) from the component outputs; add pooled (3-pool) estimates for
the reconciliation rows. EXPLORATORY."""
import json, os
from collections import defaultdict
import numpy as np
from common import *
from grid_secondaries import keyset, self_rank, by_designer

J = lambda f: json.load(open(f"{OUT}/{f}")) if os.path.exists(f"{OUT}/{f}") else None
grid = J("grid_secondaries.json"); s1 = J("s1_keyset.json"); mech = J("mechanism_summary.json"); cat = J("dif_category_check.json")
dif = {p: J(f"dif_{p}.json") for p in POOLS}
audit = {p: J(f"a_tier_audit_{p}.json") for p in POOLS}

# ---------------- pooled reconciliation rows
B = {p: bench(p) for p in POOLS}
REF = {p: B[p][0]["reference_scores"] for p in POOLS}
def tr(scale):
    return (lambda t: t) if scale == "raw" else (lambda t: fz(t, 0.999))
pooled = {}
def S2(rows_t, rows_b, km):
    return {p: (by_designer([r for r in B[p] if rows_b(r)], lambda r: self_rank(r, km)),
                by_designer([r for r in B[p] if rows_t(r)], lambda r: self_rank(r, km))) for p in POOLS}
for rn, ft, fb in [("A_all_info_arms_pooled", lambda r: r["identity_arm"] == "true", lambda r: r["identity_arm"] == "blinded"),
                   ("BC_sham_only", lambda r: r["info_arm"] == "sham" and r["identity_arm"] == "true", lambda r: r["info_arm"] == "sham" and r["identity_arm"] == "blinded")]:
    for km in ["A_mixed", "fixed12", "fixed13"]:
        pooled[f"S2|{rn}|{km}"] = pooled_boot_diff(S2(ft, fb, km), 2000, 11)
for name, (ki, kn) in {"A: inv13 vs none12": (K13, DKEYS), "B/C: inv13 vs none13": (K13, K13), "inv12 vs none12": (DKEYS, DKEYS)}.items():
    for scale in ["raw", "z0.999"]:
        t = tr(scale)
        def per(p):
            rev13 = sorted(K13, key=lambda k: (-REF[p][k], k))[::-1]
            a = by_designer([r for r in B[p] if r["info_arm"] == "inverted"], lambda r: t(tau_order(r["produced_scores"], [k for k in r["displayed_order"] if k in ki])))
            b = by_designer([r for r in B[p] if r["info_arm"] == "none"], lambda r: t(tau_order(r["produced_scores"], [k for k in rev13 if k in kn])))
            return a, b
        pooled[f"S3|{name}|{scale}"] = pooled_boot_diff({p: per(p) for p in POOLS}, 2000, 31)
for km in ["A_mixed", "fixed12", "session_displayed"]:
    for scale in ["raw", "z0.999"]:
        t = tr(scale)
        f = lambda p: (lambda r: t(tau_scores(r["produced_scores"], REF[p], keyset(r, km))))
        pooled[f"S4|{km}|{scale}"] = pooled_boot_diff({p: (by_designer([r for r in B[p] if r["info_arm"] in ("true_named", "true_blinded")], f(p)),
                                                            by_designer([r for r in B[p] if r["info_arm"] == "none"], f(p))) for p in POOLS}, 2000, 41)
# difficulty: score arms (excl. instructed) minus none, pooled
M = {p: json.load(open(f"{OUT}/mechanism_sessions_{p}.json")) for p in POOLS}
SC = ["sham", "true_named", "true_blinded", "inverted"]
for nm, arms in [("score_arms_excl_instructed", SC), ("sham_all", ["sham"]), ("true_both", ["true_named", "true_blinded"]), ("narrative", ["narrative"]), ("instructed", ["instructed"])]:
    pooled[f"difficulty|{nm}_minus_none"] = pooled_boot_diff({p: (by_designer([s for s in M[p] if s["info_arm"] in arms], lambda s: s["mean_ref_acc"]),
                                                                  by_designer([s for s in M[p] if s["info_arm"] == "none"], lambda s: s["mean_ref_acc"])) for p in POOLS}, 2000, 51)
print("pooled done", flush=True)

# ---------------- DIF per-session descriptive: top model's session residual vs benchmark easiness
difdesc = {}
for p in POOLS:
    ps = dif[p]["per_session"]
    x = np.array([s["bench_beta"] for s in ps]); y = np.array([s["top_resid_minus_mean"] for s in ps])
    arm = defaultdict(list)
    for s in ps:
        arm[s["arm"]].append(s["top_resid_minus_mean"])
    difdesc[p] = {"corr_top_resid_vs_bench_easiness": float(np.corrcoef(x, y)[0, 1]), "n_sessions": len(ps),
                  "top_resid_by_arm": {a: {"mean": float(np.mean(v)), "n": len(v)} for a, v in arm.items()}}

DIFKEYS = ["A_repro_all_rows", "A_valid", "A_valid_noFE", "A_valid_2pl_offset", "A_valid_binned_offset", "A_valid_plus_TxBenchDifficulty",
           "A_valid_modelFE", "A_valid_modelFE_x_benchdifficulty", "BC_fallback", "BC_fallback_plus_sessionFE",
           "pseudo_top_A_valid", "pseudo_top_A_valid_binned", "A_valid_sham_by_identity", "A_valid_sham_by_identity_binned",
           "A_valid_sham_by_identity_modelFE"]
results = {"label": "EXPLORATORY post-unblinding reconciliation (analysis/reconcile)", "grid_secondaries": grid, "pooled_reconciliation": pooled,
           "s1_keyset": s1, "a_tier_audit": audit,
           "dif": {p: {k: dif[p][k] for k in DIFKEYS} | {"top_model": dif[p]["top_model"], "anchor_2pl_slopes": dif[p]["anchor_2pl_slopes"]} for p in POOLS},
           "dif_per_session_descriptive": difdesc, "dif_category_check": cat, "mechanism": mech,
           "c1_keyset": J("c1_keyset.json"), "difficulty_decomposition": J("difficulty_decomp.json")}
dump(results, f"{OUT}/results.json")
print("wrote results.json")
