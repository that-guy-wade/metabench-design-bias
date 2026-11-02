"""Exploratory analysis of the cross-model edit audit. Uses the frozen analyze_audit.analyze() (copied unchanged into
scripts/analyze_audit.py) for the pre-registered quantities, and adds: rater-pair alpha with unit-bootstrap CIs,
designer-cluster bootstrap CIs, per-pool tables, the sham-vs-none test, score-arm validity, the instructed-arm
calibration against analysis/controls/q1_sessions.jsonl, and supplementary q6 (named favoured label) checks."""
import csv, json, math, sys
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
from scipy import stats

O = Path("/path/to/metabench/analysis/edit_audit")
sys.path.insert(0, str(O / "scripts"))
from analyze_audit import analyze, krippendorff_alpha, load_ratings, norm_dir, adjudicate, wilson, DIRECTIONS

RNG = np.random.default_rng(20261031)
B = 4000
ARMS = ["none", "sham", "true_blinded", "true_named", "inverted", "narrative", "instructed"]
SCORE_ARMS = ["sham", "true_blinded", "true_named", "inverted"]
key = {json.loads(l)["audit_id"]: json.loads(l) for l in open(O / "KEY_do_not_share_with_raters.jsonl")}
r1, r2 = load_ratings(O / "r1.csv"), load_ratings(O / "r2.csv")
r3 = load_ratings(O / "r3_adj.csv") if (O / "r3_adj.csv").exists() else {}
ids = sorted(key)


def load_mon(name):
    return {json.loads(l)["audit_id"]: json.loads(l) for l in open(O / name)}


# ---- frozen analysis (exact pre-registered quantities)
frozen = {}
for mname in ["monitor_flags.jsonl", "monitor_flags_session_trace.jsonl", "monitor_flags_session_artifact.jsonl"]:
    frozen[mname] = analyze(key, [r1, r2, r3], load_mon(mname))
frozen_pair = analyze(key, [r1, r2])  # alpha between the two independent raters only
res = {"n_units": len(ids), "n_r1": len(r1), "n_r2": len(r2), "n_adjudicated_by_r3": len(r3),
       "alpha_direction_nominal": frozen_pair["alpha_direction_nominal"],
       "alpha_validity_interval": frozen_pair["alpha_validity_interval"],
       "by_arm_frozen": frozen["monitor_flags.jsonl"]["by_arm"],
       "monitor_vs_rater_label": {k: v["monitor_vs_human"] for k, v in frozen.items()}}


# ---- per-unit labels
def d(r, i):
    return norm_dir(r[i]["q3_direction"]) if i in r else None


def val(r, i):
    try:
        return float(r[i]["q4_validity_1to5"])
    except (KeyError, ValueError, TypeError):
        return None


def yes(r, i, f):
    return i in r and str(r[i].get(f, "")).strip().lower() in ("y", "yes", "1", "true")


U = []
for i in ids:
    dirs = [x for x in (d(r1, i), d(r2, i), d(r3, i)) if x]
    adj = adjudicate(dirs) if dirs else None
    vs = [v for v in (val(r1, i), val(r2, i)) if v is not None]
    k = key[i]
    U.append({"id": i, "arm": k["info_arm"], "designer": k["designer"], "pool": k["pool"], "session": k["session_id"],
              "d1": d(r1, i), "d2": d(r2, i), "d3": d(r3, i), "adj": adj,
              "fav": adj == "favours_leader", "dis": adj == "disfavours_leader",
              "ref": yes(r1, i, "q2_rationale_references_scores_or_labels") or yes(r2, i, "q2_rationale_references_scores_or_labels"),
              "ref1": yes(r1, i, "q2_rationale_references_scores_or_labels"), "ref2": yes(r2, i, "q2_rationale_references_scores_or_labels"),
              "val": np.mean(vs) if vs else np.nan, "v1": val(r1, i), "v2": val(r2, i),
              "q6_1": (r1.get(i, {}).get("q6_favoured_label") or "").strip(), "q6_2": (r2.get(i, {}).get("q6_favoured_label") or "").strip(),
              "leader_ps": k.get("leader_pseudonym"), "target_ps": k.get("target_pseudonym"),
              "q1_1": (r1.get(i, {}).get("q1_changes_relative_difficulty") or ""), "q1_2": (r2.get(i, {}).get("q1_changes_relative_difficulty") or "")})


# ---- fast alpha (coincidence-matrix form; checked against the frozen O(N^2) implementation)
def alpha_nominal(pairs):
    cats = sorted({x for p in pairs for x in p})
    ix = {c: j for j, c in enumerate(cats)}
    o = np.zeros((len(cats), len(cats)))
    for a, b in pairs:
        o[ix[a], ix[b]] += 1; o[ix[b], ix[a]] += 1
    n = o.sum(); nc = o.sum(1)
    Do = (n - np.trace(o)) / n
    De = (n * n - (nc ** 2).sum()) / (n * (n - 1))
    return 1 - Do / De if De else 1.0


def alpha_interval(pairs):
    a = np.array(pairs, float)
    v = a.ravel(); n = len(v)
    Do = np.mean((a[:, 0] - a[:, 1]) ** 2)
    De = 2 * n * v.var() / (n - 1)   # mean squared difference over all ordered pairs of distinct values
    return 1 - Do / De if De else 1.0


dir_pairs = [(u["d1"], u["d2"]) for u in U if u["d1"] and u["d2"]]
val_pairs = [(u["v1"], u["v2"]) for u in U if u["v1"] is not None and u["v2"] is not None]
assert abs(alpha_nominal(dir_pairs) - res["alpha_direction_nominal"]) < 1e-9
assert abs(alpha_interval(val_pairs) - res["alpha_validity_interval"]) < 1e-9


def boot_alpha(pairs, f):
    pairs = list(pairs); n = len(pairs); out = []
    for _ in range(B):
        s = RNG.integers(0, n, n)
        try:
            out.append(f([pairs[j] for j in s]))
        except ZeroDivisionError:
            pass
    return [float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))]


res["alpha_direction_ci"] = boot_alpha(dir_pairs, alpha_nominal)
res["alpha_validity_ci"] = boot_alpha(val_pairs, alpha_interval)
res["n_direction_pairs"], res["n_validity_pairs"] = len(dir_pairs), len(val_pairs)
res["raw_agreement_direction"] = float(np.mean([a == b for a, b in dir_pairs]))
res["confusion_r1_rows_r2_cols"] = {a: {b: sum(1 for x, y in dir_pairs if x == a and y == b) for b in DIRECTIONS} for a in DIRECTIONS}
res["marginals"] = {"r1": dict(Counter(u["d1"] for u in U)), "r2": dict(Counter(u["d2"] for u in U)), "adjudicated": dict(Counter(u["adj"] for u in U))}
# alpha by arm (descriptive)
res["alpha_direction_by_arm"] = {}
for a in ARMS:
    pp = [(u["d1"], u["d2"]) for u in U if u["arm"] == a and u["d1"] and u["d2"]]
    try:
        res["alpha_direction_by_arm"][a] = {"n": len(pp), "alpha": alpha_nominal(pp), "raw_agreement": float(np.mean([x == y for x, y in pp]))}
    except ZeroDivisionError:
        res["alpha_direction_by_arm"][a] = {"n": len(pp), "alpha": None}


# ---- designer-cluster bootstrap
def cluster_boot(units, stat):
    by = defaultdict(list)
    for u in units:
        by[u["designer"]].append(u)
    ds = sorted(by); out = []
    for _ in range(B):
        samp = [u for dd in RNG.choice(ds, len(ds)) for u in by[dd]]
        v = stat(samp)
        if v is not None and not (isinstance(v, float) and math.isnan(v)):
            out.append(v)
    return [float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))] if out else [None, None]


def prop(f):
    return lambda us: float(np.mean([f(u) for u in us])) if us else None


def summarise(units):
    n = len(units)
    out = {"n": n, "n_designers": len({u["designer"] for u in units}), "n_sessions": len({u["session"] for u in units})}
    for name, f in [("favours_leader", lambda u: u["fav"]), ("disfavours_leader", lambda u: u["dis"]),
                    ("references_scores_or_labels", lambda u: u["ref"]), ("cannot_tell", lambda u: u["adj"] == "cannot_tell"),
                    ("neutral", lambda u: u["adj"] == "neutral")]:
        k = sum(f(u) for u in units)
        p, lo, hi = wilson(k, n)
        out[name] = {"k": k, "p": p, "wilson": [lo, hi], "cluster_boot": cluster_boot(units, prop(f))}
    vv = [u["val"] for u in units if not np.isnan(u["val"])]
    out["mean_validity"] = {"n": len(vv), "mean": float(np.mean(vv)) if vv else None,
                            "cluster_boot": cluster_boot(units, lambda us: float(np.nanmean([u["val"] for u in us])) if us else None)}
    return out


res["by_arm_pooled"] = {a: summarise([u for u in U if u["arm"] == a]) for a in ARMS}
res["by_arm_pool"] = {p: {a: summarise([u for u in U if u["arm"] == a and u["pool"] == p]) for a in ARMS} for p in ["factual", "math", "code"]}


# ---- can-it-fail: sham vs none favouring
def two_prop(a_units, b_units, f):
    ka, na = sum(f(u) for u in a_units), len(a_units)
    kb, nb = sum(f(u) for u in b_units), len(b_units)
    pa, la, ha = wilson(ka, na); pb, lb, hb = wilson(kb, nb)
    diff = pa - pb
    newc = [diff - math.sqrt((pa - la) ** 2 + (hb - pb) ** 2), diff + math.sqrt((ha - pa) ** 2 + (pb - lb) ** 2)]   # Newcombe hybrid score
    fisher_p = stats.fisher_exact([[ka, na - ka], [kb, nb - kb]], alternative="greater")[1]
    both = a_units + b_units
    cb = cluster_boot(both, lambda us: (np.mean([f(u) for u in us if u["arm"] == a_units[0]["arm"]] or [np.nan])
                                         - np.mean([f(u) for u in us if u["arm"] == b_units[0]["arm"]] or [np.nan])))
    overlap = not (la > hb or lb > ha)
    return {"a": {"k": ka, "n": na, "p": pa, "wilson": [la, ha]}, "b": {"k": kb, "n": nb, "p": pb, "wilson": [lb, hb]},
            "diff": diff, "newcombe_ci": newc, "cluster_boot_ci": cb, "fisher_one_sided_p": fisher_p,
            "prereg_fail_condition_met(CIs overlap and |diff|<=0.05)": bool(overlap and abs(diff) <= 0.05), "wilson_cis_overlap": overlap}


sham = [u for u in U if u["arm"] == "sham"]; none = [u for u in U if u["arm"] == "none"]
res["can_it_fail_sham_vs_none_favours"] = two_prop(sham, none, lambda u: u["fav"])
res["sham_vs_none_favours_by_pool"] = {p: two_prop([u for u in sham if u["pool"] == p], [u for u in none if u["pool"] == p], lambda u: u["fav"]) for p in ["factual", "math", "code"]}
res["sham_vs_none_references"] = two_prop(sham, none, lambda u: u["ref"])
res["sham_vs_none_fav_or_dis"] = two_prop(sham, none, lambda u: u["fav"] or u["dis"])
for a in ["true_blinded", "true_named", "inverted", "narrative", "instructed"]:
    res[f"{a}_vs_none_favours"] = two_prop([u for u in U if u["arm"] == a], none, lambda u: u["fav"])

# ---- validity in score arms vs none
sc = [u for u in U if u["arm"] in SCORE_ARMS]
def vdiff(us):
    a = [u["val"] for u in us if u["arm"] in SCORE_ARMS and not np.isnan(u["val"])]
    b = [u["val"] for u in us if u["arm"] == "none" and not np.isnan(u["val"])]
    return float(np.mean(a) - np.mean(b)) if a and b else None
va = [u["val"] for u in sc if not np.isnan(u["val"])]; vb = [u["val"] for u in none if not np.isnan(u["val"])]
res["validity_score_arms_minus_none"] = {"score_arms": SCORE_ARMS, "n_score": len(va), "mean_score": float(np.mean(va)),
                                         "n_none": len(vb), "mean_none": float(np.mean(vb)), "diff": vdiff(sc + none),
                                         "cluster_boot_ci": cluster_boot(sc + none, vdiff),
                                         "mannwhitney_p_two_sided": float(stats.mannwhitneyu(va, vb).pvalue)}
res["validity_by_arm_minus_none"] = {}
for a in ARMS[1:]:
    au = [u for u in U if u["arm"] == a]
    f = lambda us, a=a: (float(np.nanmean([u["val"] for u in us if u["arm"] == a]) - np.nanmean([u["val"] for u in us if u["arm"] == "none"])))
    res["validity_by_arm_minus_none"][a] = {"diff": f(au + none), "cluster_boot_ci": cluster_boot(au + none, f)}

# ---- instructed calibration
q1 = {json.loads(l)["session_id"]: json.loads(l) for l in open("/path/to/metabench/analysis/controls/q1_sessions.jsonl")}
cal = {}
inst = [u for u in U if u["arm"] == "instructed"]
for u in inst:
    u["comp"] = q1.get(u["session"], {}).get("judge_corrected")
for lab in ["COMPLIED", "REFUSED", "PARTIAL_AMBIGUOUS"]:
    us = [u for u in inst if u["comp"] == lab]
    if not us:
        continue
    row = {"n_units": len(us), "n_sessions": len({u["session"] for u in us}), "n_designers": len({u["designer"] for u in us})}
    for name, f in [("adj_favours_leader", lambda u: u["fav"]), ("r1_favours_leader", lambda u: u["d1"] == "favours_leader"),
                    ("r2_favours_leader", lambda u: u["d2"] == "favours_leader"), ("adj_fav_or_dis", lambda u: u["fav"] or u["dis"]),
                    ("references_scores_or_labels", lambda u: u["ref"])]:
        k = sum(f(u) for u in us); p, lo, hi = wilson(k, len(us))
        row[name] = {"k": k, "p": p, "wilson": [lo, hi]}
    tu = [u for u in us if u["target_ps"]]
    row["n_units_target_named_in_rationale"] = len(tu)
    for name, f in [("r1_q6_is_target", lambda u: u["q6_1"] == u["target_ps"]), ("r2_q6_is_target", lambda u: u["q6_2"] == u["target_ps"]),
                    ("either_q6_is_target", lambda u: u["q6_1"] == u["target_ps"] or u["q6_2"] == u["target_ps"]),
                    ("adj_favours_leader", lambda u: u["fav"])]:
        k = sum(f(u) for u in tu); p, lo, hi = wilson(k, len(tu))
        row[f"target_named__{name}"] = {"k": k, "n": len(tu), "p": p, "wilson": [lo, hi]}
    vv = [u["val"] for u in us if not np.isnan(u["val"])]
    row["mean_validity"] = float(np.mean(vv)) if vv else None
    cal[lab] = row
cu = [u for u in inst if u["comp"] == "COMPLIED"]; ru = [u for u in inst if u["comp"] == "REFUSED"]
for name, f in [("adj_favours_leader", lambda u: u["fav"]), ("either_q6_is_target_among_all", lambda u: bool(u["target_ps"]) and (u["q6_1"] == u["target_ps"] or u["q6_2"] == u["target_ps"]))]:
    k1, k2 = sum(map(f, cu)), sum(map(f, ru))
    cal[f"complied_vs_refused__{name}"] = {"complied": [k1, len(cu)], "refused": [k2, len(ru)],
                                           "fisher_two_sided_p": stats.fisher_exact([[k1, len(cu) - k1], [k2, len(ru) - k2]])[1]}
res["instructed_calibration"] = cal

# ---- supplementary: q6 named label vs displayed leader; leader named in rationale
res["supp_leader_named_in_rationale_by_arm"] = {a: {"k": sum(1 for u in U if u["arm"] == a and u["leader_ps"]), "n": sum(1 for u in U if u["arm"] == a)} for a in ARMS}
res["supp_q6_is_displayed_leader_by_arm"] = {}
for a in ARMS:
    us = [u for u in U if u["arm"] == a]
    k = sum(1 for u in us if u["leader_ps"] and (u["q6_1"] == u["leader_ps"] or u["q6_2"] == u["leader_ps"]))
    k_any = sum(1 for u in us if (u["q6_1"] not in ("", "none") or u["q6_2"] not in ("", "none")))
    res["supp_q6_is_displayed_leader_by_arm"][a] = {"either_rater_q6_is_displayed_leader": k, "either_rater_names_any_label": k_any, "n": len(us)}
res["q1_changes_relative_difficulty_yes_by_arm"] = {a: {"r1": float(np.mean([u["q1_1"] == "yes" for u in U if u["arm"] == a])), "r2": float(np.mean([u["q1_2"] == "yes" for u in U if u["arm"] == a]))} for a in ARMS}
res["references_by_rater_by_arm"] = {a: {"r1": float(np.mean([u["ref1"] for u in U if u["arm"] == a])), "r2": float(np.mean([u["ref2"] for u in U if u["arm"] == a]))} for a in ARMS}
# monitor P/R by arm (per-action flags) and the frozen totals
for mname in ["monitor_flags.jsonl", "monitor_flags_session_trace.jsonl", "monitor_flags_session_artifact.jsonl"]:
    mon = load_mon(mname)
    t = [(u["fav"] or u["dis"], mon[u["id"]]["flag"]) for u in U if u["adj"]]
    res["monitor_vs_rater_label"][mname]["n"] = len(t)
    res["monitor_vs_rater_label"][mname]["n_truth_positive"] = sum(a for a, _ in t)
    res["monitor_vs_rater_label"][mname]["n_flagged"] = sum(b for _, b in t)

json.dump(res, open(O / "results.json", "w"), indent=1, default=float)
with open(O / "units_labelled.csv", "w", newline="") as f:
    cols = ["id", "pool", "arm", "designer", "session", "d1", "d2", "d3", "adj", "ref1", "ref2", "v1", "v2", "q6_1", "q6_2", "leader_ps", "target_ps"]
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); [w.writerow(u) for u in U]
print(json.dumps({k: res[k] for k in ["n_units", "n_r1", "n_r2", "n_adjudicated_by_r3", "alpha_direction_nominal", "alpha_direction_ci",
                                      "alpha_validity_interval", "alpha_validity_ci", "raw_agreement_direction", "marginals"]}, indent=1, default=float))
