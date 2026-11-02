"""Part 2 (EXPLORATORY): robustness of the primary Psi (sham/blinded) and an equivalence test.

Usage: python p2_robust.py  ->  p2_results.json

(a) as reported: (i) the frozen metabench.analysis.primary_endpoint, unchanged, n_perm = n_boot = 10,000, seed 0
    (must reproduce +0.031 / -0.022 / -0.000 and p 0.136 / 0.767 / 0.498); (ii) this directory's vectorised
    re-implementation (scommon.psi_stats, 10,000 / 10,000) used for every variant below.
(b) Google designers (gemini4argon, gemini31pro, gemini38flash) excluded: 9 designers.
(c) contamination-flagged models dropped from the ranked key set (unblinded/<pool>/endpoints/contamination/
    contamination.json flagged.any, intersected with the 13 displayed keys); remaining keys keep their displayed
    relative order; the null re-draws uniform permutations of the remaining keys (= a uniform 13-permutation restricted).
(d) produced scores recomputed from precompute/<pool>.jsonl with last-row-wins (metabench.panel.latest_rows):
    unedited items use the precompute samples, edited items use the session's live re-score (item_outcomes.jsonl),
    weights as registered; scores rounded to 5 decimals as produced_scores are stored (unrounded floats break exact
    ties such as sonnet55 = placebo through summation order).  'Unresolved' triples = (item, model, sample) in the 2000 x 17 x 5 grid whose last row is an
    error row or that have no row at all.  Scenarios: excluded (the frozen rule; must reproduce produced_scores),
    all unresolved = wrong (0), all unresolved = right (1).
Equivalence: H0 tanh(Psi) >= 0.10 (also 0.15) vs H1 < bound: designer-level one-sided t on designer-mean Fisher z
    (df = D - 1) and cluster bootstrap (share of bootstrap z >= atanh(bound)); per pool and pooled (designer = cluster
    across pools; a designer's mean z is over all its sham/blinded sessions in the three pools).
"""
from __future__ import annotations

import json
from collections import defaultdict

import numpy as np

from scommon import (K13, K17, GOOGLE, OUT, UNB, POOLS, bench_rows, sham_blinded, psi_stats, strip, equivalence, dump,
                     read_jsonl)
from metabench.panel import latest_rows
from metabench.analysis import primary_endpoint

NP = NB = 10000


def sessions_from(rows, pool, keys_drop=(), scores_field="produced_scores", override=None):
    out = []
    for r in rows:
        disp = [k for k in r["displayed_order"] if k not in keys_drop]
        sc = override[r["session_id"]] if override else r[scores_field]
        out.append({"designer": r["designer"], "pool": pool, "scores": np.array([sc[k] for k in disp]),
                    "session_id": r["session_id"]})
    return out


def recompute_scores(pool, rows):
    """Returns {scenario: {session_id: {key: score}}}, reproduction diagnostics and the unresolved triples."""
    path = UNB / f"WORK_{pool}" / "precompute" / f"{pool}.jsonl"
    last = latest_rows(path, lambda r: None if r.get("error") else int(r["correct"]))
    items = sorted({k[0] for k in last})
    models = sorted({k[1] for k in last})
    unresolved = [(i, m, s) for i in items for m in K17 for s in range(5) if last.get((i, m, s), None) is None]
    unres_err = [t for t in unresolved if t in last]
    unres_missing = [t for t in unresolved if t not in last]
    corr = defaultdict(list)
    n_unres = defaultdict(int)
    for (i, m, s), c in last.items():
        if c is not None:
            corr[(i, m)].append(c)
    for (i, m, s) in unresolved:
        n_unres[(i, m)] += 1
    sids = {r["session_id"] for r in rows}
    live = defaultdict(dict)
    for o in read_jsonl(UNB / f"WORK_{pool}" / "results" / "item_outcomes.jsonl"):
        if o["session_id"] in sids:
            live[o["session_id"]][(o["item_id"], o["model_key"])] = (o["n_correct"], o["n_samples"])
    res = {"excluded": {}, "wrong": {}, "right": {}}
    diag = {"max_abs_diff_unaffected": 0.0, "max_abs_diff_affected_excluded": 0.0, "n_sessions_touching_unresolved": 0,
            "n_item_model_cells_in_benchmarks_with_unresolved": 0}
    affected_models = sorted({m for (_, m, _) in unresolved})
    for r in rows:
        w = r["weights"] if r["scoring_rule"] == "weighted_accuracy" else {}
        edited = set(r.get("edited_items") or {})
        touch = 0
        for scen in res:
            sc = {}
            for m in K17:
                num = den = 0.0
                for it in r["items"]:
                    wt = float(w.get(it, 1.0))
                    if it in edited:
                        c, n = live[r["session_id"]].get((it, m), (0, 0))
                    else:
                        cs = corr.get((it, m), [])
                        c, n = sum(cs), len(cs)
                        u = n_unres.get((it, m), 0)
                        if scen == "excluded" and u and m in K13:
                            touch += 1
                        if scen == "wrong":
                            n += u
                        elif scen == "right":
                            c += u; n += u
                    if n == 0:
                        continue
                    num += wt * c / n; den += wt
                sc[m] = round(num / den, 5) if den else float("nan")   # produced_scores are stored to 5 decimals; rounding keeps exact ties exact
            res[scen][r["session_id"]] = sc
        for m in K17:
            d = abs(res["excluded"][r["session_id"]][m] - r["produced_scores"][m])
            key = "max_abs_diff_affected_excluded" if m in affected_models else "max_abs_diff_unaffected"
            diag[key] = max(diag[key], d)
        diag["n_sessions_touching_unresolved"] += int(touch > 0)
        diag["n_item_model_cells_in_benchmarks_with_unresolved"] += touch
    diag.update({"n_unresolved_triples": len(unresolved), "n_unresolved_error_last_row": len(unres_err),
                 "n_unresolved_no_row": len(unres_missing), "affected_models": affected_models,
                 "unresolved_by_model": {m: sum(1 for t in unresolved if t[1] == m) for m in affected_models},
                 "n_unresolved_items": len({t[0] for t in unresolved}), "n_items": len(items), "n_models_in_file": len(models)})
    return res, diag, unresolved


def main():
    out = {"n_perm": NP, "n_boot": NB}
    pooled = defaultdict(list)
    eq_sessions = []
    for pool in POOLS:
        rows = sham_blinded(bench_rows(pool))
        o = {}
        fr = primary_endpoint(bench_rows(pool, valid_only=False), n_perm=NP, n_boot=NB, seed=0, identity_arm="blinded")
        o["a_frozen"] = {k: fr[k] for k in ("psi", "p_one_sided", "ci95_cluster_tau", "ci95_bench_tau", "n", "n_designers")}
        S = sessions_from(rows, pool)
        st = psi_stats(S, NP, NB, seed=1)
        o["a_reimpl"] = strip(st)
        o["equivalence_0.10"] = equivalence(st, 0.10)
        o["equivalence_0.15"] = equivalence(st, 0.15)
        pooled["a"] += S
        # (b)
        Sb = [s for s in S if s["designer"] not in GOOGLE]
        o["b_no_google"] = strip(psi_stats(Sb, NP, NB, seed=2))
        pooled["b"] += Sb
        # (c)
        flagged = json.load(open(UNB / pool / "endpoints" / "contamination" / "contamination.json"))["flagged"]["any"]
        drop = [k for k in flagged if k in K13]
        Sc = sessions_from(rows, pool, keys_drop=drop)
        o["c_drop_flagged"] = strip(psi_stats(Sc, NP, NB, seed=3)) | {"flagged_any": flagged, "dropped_from_ranking": drop,
                                                                     "n_keys_ranked": 13 - len(drop)}
        pooled["c"] += Sc
        # (d)
        rec, diag, unresolved = recompute_scores(pool, rows)
        o["d_diagnostics"] = diag
        o["d_unresolved_triples"] = [list(t) for t in unresolved]
        for scen in ("excluded", "wrong", "right"):
            Sd = sessions_from(rows, pool, override=rec[scen])
            o[f"d_{scen}"] = strip(psi_stats(Sd, NP, NB, seed=4))
            pooled[f"d_{scen}"] += Sd
        out[pool] = o
        print(pool, "frozen", o["a_frozen"]["psi"], o["a_frozen"]["p_one_sided"], "reimpl", o["a_reimpl"]["psi"],
              o["a_reimpl"]["p_one_sided"], "| b", o["b_no_google"]["psi"], "| c", o["c_drop_flagged"]["psi"],
              "| d", o["d_wrong"]["psi"], o["d_right"]["psi"], diag, flush=True)
    po = {}
    for k, S in pooled.items():
        st = psi_stats(S, NP, NB, seed=5)
        po[k] = strip(st)
        if k == "a":
            po["equivalence_0.10"] = equivalence(st, 0.10)
            po["equivalence_0.15"] = equivalence(st, 0.15)
    out["pooled"] = po
    dump(out, OUT / "p2_results.json")
    print("pooled", {k: (round(v["psi"], 4), round(v["p_one_sided"], 4), v["ci95_cluster_tau"]) for k, v in po.items()
                     if "psi" in v})


if __name__ == "__main__":
    main()
