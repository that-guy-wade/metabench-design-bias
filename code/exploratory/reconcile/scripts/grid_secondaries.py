"""Q1: recompute S2, S3, S4 under every definitional choice that differs between implementations A, B, C.
EXPLORATORY. Designer-cluster bootstrap CIs (4000), within-designer label-permutation p (4000)."""
import sys
from collections import defaultdict
import numpy as np
from common import *

NB = int(sys.argv[1]) if len(sys.argv) > 1 else 4000


def a_panel_keys(r):
    """A's panel_keys(): displayed_order if present (sham/inverted: 13 incl. placebo under pseudonyms, 12 named),
    else displayed_keys minus placebo/heldout (12)."""
    base = r.get("displayed_order") or [k for k in r["displayed_keys"] if not k.startswith(("placebo_", "heldout_"))]
    return [k for k in base if k in r["produced_scores"]]


def keyset(r, mode):
    if mode == "A_mixed":
        return a_panel_keys(r)
    if mode == "fixed12":
        return list(DKEYS)
    if mode == "fixed13":
        return list(K13)
    if mode == "session_displayed":
        return list(r["displayed_keys"])
    raise ValueError(mode)


def by_designer(rows, f):
    out = defaultdict(list)
    for r in rows:
        v = f(r)
        if v is not None and np.isfinite(v):
            out[r["designer"]].append(v)
    return out


def contrast(a, b, side, seed):
    est, ci, nd = cluster_boot_diff(a, b, NB, seed)
    p = perm_diff_p(a, b, NB, seed + 1, side)
    return {"estimate": est, "ci95_cluster": ci, "n_designers": nd,
            "n_a": int(sum(len(v) for d, v in a.items() if d in b)), "n_b": int(sum(len(v) for d, v in b.items() if d in a)),
            "p_perm": p, "side": side}


def self_rank(r, mode):
    ks = keyset(r, mode)
    if r["designer"] not in ks:
        ks = ks + [r["designer"]]
    return ranks(r["produced_scores"], ks)[r["designer"]]


def s2_grid(B):
    out = {}
    row_defs = {
        "A_all_info_arms_pooled": (lambda r: r["identity_arm"] == "true", lambda r: r["identity_arm"] == "blinded"),
        "BC_sham_only": (lambda r: r["info_arm"] == "sham" and r["identity_arm"] == "true",
                         lambda r: r["info_arm"] == "sham" and r["identity_arm"] == "blinded"),
        "true_named_vs_true_blinded": (lambda r: r["info_arm"] == "true_named", lambda r: r["info_arm"] == "true_blinded"),
        "A_pool_minus_instructed": (lambda r: r["identity_arm"] == "true",
                                    lambda r: r["identity_arm"] == "blinded" and r["info_arm"] != "instructed"),
        "A_pool_score_arms_only": (lambda r: r["identity_arm"] == "true",
                                   lambda r: r["identity_arm"] == "blinded" and r["info_arm"] in ("sham", "true_blinded", "inverted")),
    }
    for rn, (ft, fb) in row_defs.items():
        for km in ["A_mixed", "fixed12", "fixed13"]:
            T = by_designer([r for r in B if ft(r)], lambda r: self_rank(r, km))
            Bl = by_designer([r for r in B if fb(r)], lambda r: self_rank(r, km))
            out[f"{rn}|{km}"] = contrast(Bl, T, "greater", 11)   # gain = rank(blinded) - rank(true)
    # decomposition of A's blinded pool: mean self rank by info arm (A_mixed vs fixed12)
    dec = {}
    for arm in ["none", "sham", "true_blinded", "inverted", "narrative", "instructed", "true_named"]:
        for ident in ["blinded", "true"]:
            rows = [r for r in B if r["info_arm"] == arm and r["identity_arm"] == ident]
            if not rows:
                continue
            for km in ["A_mixed", "fixed12"]:
                e, ci, nd = cluster_boot_mean(by_designer(rows, lambda r: self_rank(r, km)), 2000, 5)
                dec[f"{arm}/{ident}|{km}"] = {"mean_self_rank": e, "ci95_cluster": ci, "n_designers": nd, "n": len(rows)}
    out["_self_rank_by_cell"] = dec
    return out


def s3_grid(B):
    out = {}
    inv = [r for r in B if r["info_arm"] == "inverted"]
    non = [r for r in B if r["info_arm"] == "none"]
    ref = B[0]["reference_scores"]
    rev13 = sorted(K13, key=lambda k: (-ref[k], k))[::-1]
    rev12 = [k for k in rev13 if k != PLACEBO]
    def t_inv(r, ks):  # tau to displayed (inverted) order restricted to ks
        return tau_order(r["produced_scores"], [k for k in r["displayed_order"] if k in ks])
    def t_non(r, ks):
        return tau_order(r["produced_scores"], [k for k in rev13 if k in ks])
    combos = {"A: inv13 vs none12": (K13, DKEYS), "B/C: inv13 vs none13": (K13, K13),
              "inv12 vs none12": (DKEYS, DKEYS), "inv12 vs none13": (DKEYS, K13)}
    for name, (ki, kn) in combos.items():
        for scale in ["raw", "z0.999", "z0.9999", "z0.999999"]:
            tr = (lambda t: t) if scale == "raw" else (lambda t, c=float(scale[1:]): fz(t, c))
            a = by_designer(inv, lambda r: tr(t_inv(r, ki)))
            b = by_designer(non, lambda r: tr(t_non(r, kn)))
            out[f"{name}|{scale}"] = contrast(a, b, "greater", 31)
    # descriptive: mean tau per arm and key set; count |tau| = 1
    desc = {}
    for nm, rows, f in [("inverted", inv, t_inv), ("none_vs_reverse_ref", non, t_non)]:
        for ks_name, ks in [("13", K13), ("12", DKEYS)]:
            v = [f(r, ks) for r in rows]
            desc[f"{nm}|{ks_name}"] = {"mean_tau": float(np.mean(v)), "n": len(v), "n_abs_tau_eq_1": int(sum(abs(x) > 0.99999 for x in v)),
                                      "min_abs": float(np.min(np.abs(v))), "max_abs": float(np.max(np.abs(v)))}
    # placebo vs sonnet55 near-tie: produced order disagreement rate (adds discordant pairs in the 13-key tau)
    for nm, rows in [("inverted", inv), ("none", non)]:
        desc[f"{nm}|P(placebo above sonnet55)"] = float(np.mean([r["produced_scores"][PLACEBO] > r["produced_scores"]["sonnet55"] for r in rows]))
    desc["reference_sonnet55_minus_placebo"] = ref["sonnet55"] - ref[PLACEBO]
    # direction check: tau to reference in inverted, true_blinded and none (12 keys)
    for arm in ["none", "inverted", "true_blinded", "true_named", "sham"]:
        e, ci, nd = cluster_boot_mean(by_designer([r for r in B if r["info_arm"] == arm],
                                                  lambda r: tau_scores(r["produced_scores"], ref, DKEYS)), 2000, 6)
        desc[f"tau_to_reference_12keys|{arm}"] = {"mean": e, "ci95_cluster": ci, "n_designers": nd,
                                                 "n": sum(r["info_arm"] == arm for r in B)}
    out["_descriptive"] = desc
    return out


def s4_grid(B):
    out = {}
    ref = B[0]["reference_scores"]
    tru = [r for r in B if r["info_arm"] in ("true_named", "true_blinded")]
    non = [r for r in B if r["info_arm"] == "none"]
    for km in ["A_mixed", "fixed12", "fixed13", "session_displayed"]:
        for scale in ["raw", "z0.999"]:
            tr = (lambda t: t) if scale == "raw" else (lambda t: fz(t, 0.999))
            f = lambda r: tr(tau_scores(r["produced_scores"], ref, keyset(r, km)))
            for arms_name, rows in [("true_named+true_blinded", tru), ("true_named", [r for r in tru if r["info_arm"] == "true_named"]),
                                    ("true_blinded", [r for r in tru if r["info_arm"] == "true_blinded"])]:
                out[f"{arms_name}|{km}|{scale}"] = contrast(by_designer(rows, f), by_designer(non, f), "two-sided", 41)
    return out


if __name__ == "__main__":
    res = {}
    for p in POOLS:
        B = bench(p)
        res[p] = {"S2": s2_grid(B), "S3": s3_grid(B), "S4": s4_grid(B)}
        print(p, "done", flush=True)
    dump(res, f"{OUT}/grid_secondaries.json")
