"""Assemble results.json and the tables in FINDINGS.txt from classify_<pool>.json, kept_vs_viewed_results.json,
kept_vs_viewed_sessions.jsonl, transfer_results.json, exposure.jsonl and exposure_check.json (EXPLORATORY).

Pooled classifier accuracy = mean of per-session correctness over the three pools' sessions; CI = 2,000 bootstrap
resamples stratified by pool x designer; pooled permutation null = n-weighted mean of the three pools' k-th null
accuracies (k = 1..N_PERM), p = (1 + #{null >= obs}) / (1 + N_PERM).
Paired feature-set contrasts (e.g. tfidf - difficulty) use per-session correctness differences on the same sessions,
bootstrap stratified by designer (by pool x designer for pooled).
"""
from __future__ import annotations

import json
from collections import Counter

import numpy as np

from common import DESIGNERS, DEV, OUT, POOLS, read_jsonl

FSETS = ["tfidf", "items", "mix", "difficulty", "diffprof", "listpos"]
SUBS = ["all", "none_blinded", "sham_blinded"]
rng = np.random.default_rng(7)


def boot(v, strat, n=2000):
    v, strat = np.asarray(v, float), np.asarray(strat)
    groups = [np.where(strat == s)[0] for s in np.unique(strat)]
    bs = [np.mean(v[np.concatenate([rng.choice(g, len(g)) for g in groups])]) for _ in range(n)]
    return [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]


def main():
    C = {p: json.loads((OUT / f"classify_{p}.json").read_text()) for p in POOLS}
    res = {"classifier": {}, "classifier_pooled": {}, "classifier_paired": {}, "per_designer_recall": {}}
    for s in SUBS:
        for fs in FSETS:
            for tgt in ["designer", "developer"]:
                key = f"{s}|{fs}|{tgt}"
                for p in POOLS:
                    r = C[p][s][f"{fs}|{tgt}"]
                    res["classifier"][f"{p}|{key}"] = {k: r[k] for k in r if k not in ("per_session_correct", "pred_rep0", "null", "collapsed_dev_per_session")}
                    res["classifier"][f"{p}|{key}"]["n_designers"] = len(C[p][s]["n_per_designer"])
                v = np.concatenate([C[p][s][f"{fs}|{tgt}"]["per_session_correct"] for p in POOLS])
                st = np.concatenate([[f"{p}:{d}" for d in C[p][s]["designers"]] for p in POOLS])
                ns = np.array([len(C[p][s]["designers"]) for p in POOLS], float)
                nulls = np.array([C[p][s][f"{fs}|{tgt}"]["null"] for p in POOLS])
                null = (ns[:, None] * nulls).sum(0) / ns.sum()
                obs = float(v.mean())
                res["classifier_pooled"][key] = {"acc": obs, "ci": boot(v, st), "n": int(len(v)), "null_mean": float(null.mean()),
                                                 "perm_p": float((1 + np.sum(null >= obs)) / (1 + len(null)))}
                if tgt == "designer":
                    vd = np.concatenate([C[p][s][f"{fs}|designer"]["collapsed_dev_per_session"] for p in POOLS])
                    res["classifier_pooled"][key].update(collapsed_dev_acc=float(vd.mean()), collapsed_dev_ci=boot(vd, st))
        for base in ["difficulty", "diffprof", "listpos", "mix"]:
            for other in ["tfidf", "items"]:
                allv, allst = [], []
                for p in POOLS:
                    a = np.array(C[p][s][f"{other}|designer"]["per_session_correct"])
                    b = np.array(C[p][s][f"{base}|designer"]["per_session_correct"])
                    res["classifier_paired"][f"{p}|{s}|{other}-{base}"] = {"diff": float((a - b).mean()), "ci": boot(a - b, C[p][s]["designers"]), "n": int(len(a))}
                    allv.append(a - b); allst += [f"{p}:{d}" for d in C[p][s]["designers"]]
                v = np.concatenate(allv)
                res["classifier_paired"][f"pooled|{s}|{other}-{base}"] = {"diff": float(v.mean()), "ci": boot(v, allst), "n": int(len(v))}
    for p in POOLS:
        r = C[p]["all"]["tfidf|designer"]
        cm = np.array(r["confusion_sum5"])
        res["per_designer_recall"][p] = {d: float(cm[i, i] / cm[i].sum()) for i, d in enumerate(r["labels"])}
        res.setdefault("confusion_all_tfidf_designer_sum5", {})[p] = {"labels": r["labels"], "matrix": r["confusion_sum5"]}
        for s in SUBS:
            r = C[p][s]["tfidf|designer"]
            res.setdefault("confusion_tfidf_designer_sum5", {})[f"{p}|{s}"] = {"labels": r["labels"], "matrix": r["confusion_sum5"]}
    res["kept_vs_viewed"] = json.loads((OUT / "kept_vs_viewed_results.json").read_text())
    res["transfer"] = json.loads((OUT / "transfer_results.json").read_text())
    res["exposure_check"] = json.loads((OUT / "exposure_check.json").read_text())
    E = read_jsonl(OUT / "exposure.jsonl")
    ex = {}
    for p in POOLS:
        for c in ["sham/blinded", "none/blinded", "true_blinded/blinded"]:
            X = [e for e in E if e["pool"] == p and e["cell"] == c]
            ex[f"{p}|{c}"] = {"n": len(X), "n_designers": len({e["designer"] for e in X}),
                              "exposed_median": float(np.median([e["n_exposed"] for e in X])),
                              "exposed_min": int(min(e["n_exposed"] for e in X)), "exposed_max": int(max(e["n_exposed"] for e in X)),
                              "viewed_full_median": float(np.median([len(e["viewed_full"]) for e in X])),
                              "kept_not_exposed_total": int(sum(len(e["kept_not_exposed"]) for e in X)),
                              "sessions_with_kept_not_exposed": int(sum(bool(e["kept_not_exposed"]) for e in X)),
                              "kept_not_viewed_full_mean": float(np.mean([len(e["kept_not_viewed_full"]) for e in X])),
                              "sessions_exposed_le_100": int(sum(e["n_exposed"] <= 100 for e in X))}
    res["exposure_summary"] = ex
    S = read_jsonl(OUT / "kept_vs_viewed_sessions.jsonl")
    res["draft_r1_overlap"] = {c: {"median_overlap": float(np.median([s["kept_overlap_draft_r1"] for s in S if s["cell"] == c])),
                                   "n": sum(s["cell"] == c for s in S)} for c in ["sham/blinded", "none/blinded", "true_blinded/blinded"]}
    (OUT / "results.json").write_text(json.dumps(res, indent=1))
    print_tables(res)


def f3(x):
    return f"{x['acc']:.3f} [{x['ci'][0]:.3f}, {x['ci'][1]:.3f}]"


def print_tables(res):
    L = []
    for s in SUBS:
        L.append(f"\n== Classifier, subset {s}: 12-class designer accuracy (chance 0.083) | perm-null mean | p ; direct 4-class developer accuracy (chance 0.25) | p ; collapsed-to-developer")
        for fs in FSETS:
            for p in list(POOLS) + ["pooled"]:
                if p == "pooled":
                    d, v = res["classifier_pooled"][f"{s}|{fs}|designer"], res["classifier_pooled"][f"{s}|{fs}|developer"]
                    nd = 12
                    cd = f"{d['collapsed_dev_acc']:.3f} [{d['collapsed_dev_ci'][0]:.3f}, {d['collapsed_dev_ci'][1]:.3f}]"
                else:
                    d, v = res["classifier"][f"{p}|{s}|{fs}|designer"], res["classifier"][f"{p}|{s}|{fs}|developer"]
                    nd = d["n_designers"]
                    cd = f"{d['collapsed_dev_acc']:.3f} [{d['collapsed_dev_ci'][0]:.3f}, {d['collapsed_dev_ci'][1]:.3f}]"
                L.append(f"{fs:10s} {p:8s} n={d['n']:3d}/{nd:2d}  des {f3(d)} null {d['null_mean']:.3f} p={d['perm_p']:.3f} | dev {f3(v)} null {v['null_mean']:.3f} p={v['perm_p']:.3f} | coll {cd}")
    L.append("\n== Paired: tfidf/items minus baseline (per-session correctness difference, designer target)")
    for k, v in res["classifier_paired"].items():
        L.append(f"{k:40s} {v['diff']:+.3f} [{v['ci'][0]:+.3f}, {v['ci'][1]:+.3f}] n={v['n']}")
    L.append("\n== Per-designer recall (all sessions, tfidf, sum of 5 CV repeats)")
    for p, r in res["per_designer_recall"].items():
        L.append(p + ": " + ", ".join(f"{d} {x:.2f}" for d, x in r.items()))
    for p, cmd in res["confusion_all_tfidf_designer_sum5"].items():
        L.append(f"\n== Confusion (all, tfidf, designer; rows = true, cols = predicted; counts summed over 5 CV repeats) {p}")
        labs = cmd["labels"]
        L.append(" " * 14 + " ".join(f"{l[:6]:>6s}" for l in labs))
        for l, row in zip(labs, cmd["matrix"]):
            L.append(f"{l:14s}" + " ".join(f"{x:6d}" for x in row))
    print("\n".join(L))
    (OUT / "classifier_tables.txt").write_text("\n".join(L))


if __name__ == "__main__":
    main()
