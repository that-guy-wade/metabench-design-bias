"""Q3 (C6 manipulation check) and Q4 (self-recognition, PREREG section 12). EXPLORATORY.
Inputs: ../probe_extract.jsonl (regex + LLM extraction, from extract_probes.py), session scores_views.jsonl.

Q3: score arms = sham (all identity arms), inverted, true_named, true_blinded, instructed. For each valid session the
LAST numeric scores view (a view with a non-empty 'order') gives the displayed top entry order[0] (label as displayed:
label_map[order[0]]). Correct (strict) = the recall answer's #1 label resolves to order[0]. Lenient = resolves to any
entry tied with order[0] on the shown value. Primary extraction = regex parser; LLM extraction is the cross-check and
disagreements are listed. Sessions with no numeric view are listed and excluded from the primary denominator (and counted
as failures in the 'all' variant). Narrative arm (shows only a leader) and none arm (shows nothing) reported separately.

Q4: pseudonymous sessions (named == False) with a self_recognition answer. Guess = label resolved to a panel key or NONE.
Exact hit = guess is the designer's own key (for sonnet55 also its identical placebo). Family hit = guess has the same
developer. Chance per session = (#qualifying displayed keys) / (#displayed keys); tests are exact Poisson-binomial
one-sided (sum of per-session chance probabilities), over all sessions (NONE = miss) and over sessions that named an entry.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import OUT, POOLS, PLACEBO, DEVELOPER, SCORE_ARMS, load_rows, load_jsonl, sess_dir, prop, wilson, dump  # noqa


def lab2key(lab, lm):
    if lab is None:
        return None
    if lab in ("NO_RESULTS", "NONE"):
        return lab
    inv = {v: k for k, v in lm.items()}
    return inv.get(lab, "UNMAPPED")


def poisbin_sf(k, ps):
    """P(X >= k) for X ~ Poisson-binomial(ps)."""
    dist = np.zeros(len(ps) + 1)
    dist[0] = 1.0
    for p in ps:
        dist[1:] = dist[1:] * (1 - p) + dist[:-1] * p
        dist[0] *= (1 - p)
    return float(dist[k:].sum())


def main():
    ext = {json.loads(l)["session_id"]: json.loads(l) for l in open(OUT / "probe_extract.jsonl")}
    q3, q4, disagree = [], [], []
    for pool in POOLS:
        for r in load_rows(pool):
            sid, lm = r["session_id"], r["label_map"]
            e = ext.get(sid)
            views = load_jsonl(sess_dir(pool, sid) / "scores_views.jsonl")
            num = [v for v in views if v.get("order")]
            narr = [v for v in views if v.get("leader")]
            rx = e["rx_recall_first"] if e else None
            ll = lab2key(e.get("llm_recall_first_label"), lm) if e else None
            if e and rx != ll:
                disagree.append(dict(kind="recall", session_id=sid, regex=rx, llm=ll, text=(e["recall_text"] or "")[:400]))
            rec = dict(pool=pool, session_id=sid, designer=r["designer"], arm=r["info_arm"], identity=r["identity_arm"],
                       named=r["named"], has_probe=e is not None, n_numeric_views=len(num), recall_first=rx,
                       recall_first_llm=ll)
            if num:
                last = num[-1]
                top = last["order"][0]
                mx = last["shown"][top]
                tied = [k for k in last["order"] if abs(last["shown"][k] - mx) < 1e-9]
                rec.update(last_top=top, last_top_label=lm[top], tied_top=tied,
                           correct=rx == top, correct_lenient=rx in tied, correct_llm=ll == top,
                           names_top_of_earlier_view=any(rx == v["order"][0] for v in num[:-1]),
                           names_first_view_top=rx == num[0]["order"][0])
            if narr:
                rec.update(narrated_leader=narr[-1]["leader"], names_narrated_leader=rx == narr[-1]["leader"])
            q3.append(rec)
            # Q4
            if e and e.get("self_text") is not None and not r["named"]:
                g = e["rx_self_guess"]
                gl = lab2key(e.get("llm_self_guess_label"), lm)
                if g != gl:
                    disagree.append(dict(kind="self", session_id=sid, regex=g, llm=gl, text=e["self_text"][:400]))
                d = r["designer"]
                own = {d} | ({PLACEBO} if d == "sonnet55" else set())
                fam = {k for k in r["displayed_keys"] if DEVELOPER[k] == DEVELOPER[d]}
                nk = len(r["displayed_keys"])
                tops = [v["order"][0] for v in num]
                q4.append(dict(pool=pool, session_id=sid, designer=d, developer=DEVELOPER[d], arm=r["info_arm"],
                               guess=g, guess_llm=gl, conf=e["rx_self_conf"], declined=g == "NONE",
                               exact=g in own, family=g in fam, p_exact=len(own) / nk, p_family=len(fam) / nk,
                               guess_is_last_top=bool(tops) and g == tops[-1],
                               guess_is_target=g == r.get("target_model") if r["info_arm"] == "instructed" else None,
                               own_is_last_top=bool(tops) and tops[-1] in own,
                               n_views=len(num)))
    for name, rows in (("q3_sessions.jsonl", q3), ("q4_sessions.jsonl", q4), ("probe_extract_disagreements.jsonl", disagree)):
        with open(OUT / name, "w") as f:
            for x in rows:
                f.write(json.dumps(x) + "\n")

    def byd(rows, f):
        o = defaultdict(list)
        for x in rows:
            o[x["designer"]].append(int(f(x)))
        return o

    res = {"extraction_disagreements": {"recall": sum(d["kind"] == "recall" for d in disagree),
                                        "self": sum(d["kind"] == "self" for d in disagree)}}
    for pool in POOLS + ["pooled"]:
        P = [x for x in q3 if pool == "pooled" or x["pool"] == pool]
        o = {}
        sc = [x for x in P if x["arm"] in SCORE_ARMS]
        withv = [x for x in sc if x["n_numeric_views"] > 0]
        o["score_arm_sessions"] = len(sc)
        o["never_requested"] = sorted(x["session_id"] for x in sc if x["n_numeric_views"] == 0)
        o["C6_strict"] = prop(byd(withv, lambda x: x["correct"]), n_boot=4000)
        o["C6_lenient_ties"] = prop(byd(withv, lambda x: x["correct_lenient"]), n_boot=4000)
        o["C6_llm_extraction"] = prop(byd(withv, lambda x: x["correct_llm"]), n_boot=4000)
        o["C6_all_sessions_missing_as_fail"] = prop(byd(sc, lambda x: x.get("correct", False)), n_boot=4000)
        o["C6_pass_80"] = o["C6_strict"]["p"] is not None and o["C6_strict"]["p"] >= 0.8
        o["wrong_names_earlier_view_top"] = sum(1 for x in withv if not x["correct"] and x["names_top_of_earlier_view"])
        o["wrong_total"] = sum(1 for x in withv if not x["correct"])
        o["per_arm"] = {}
        for arm, ident in sorted({(x["arm"], x["identity"]) for x in sc}):
            A = [x for x in withv if x["arm"] == arm and x["identity"] == ident]
            o["per_arm"][f"{arm}/{ident}"] = prop(byd(A, lambda x: x["correct"]), n_boot=2000)
        o["per_designer"] = {d: dict(k=sum(x["correct"] for x in withv if x["designer"] == d),
                                     n=sum(1 for x in withv if x["designer"] == d))
                             for d in sorted({x["designer"] for x in withv})}
        for d, v in o["per_designer"].items():
            v["p"] = v["k"] / v["n"] if v["n"] else None
            v["wilson"] = wilson(v["k"], v["n"])
        na = [x for x in P if x["arm"] == "narrative"]
        o["narrative_names_leader"] = prop(byd(na, lambda x: x.get("names_narrated_leader", False)), n_boot=2000)
        no = [x for x in P if x["arm"] == "none"]
        o["none_says_no_results"] = prop(byd(no, lambda x: x["recall_first"] == "NO_RESULTS"), n_boot=2000)
        # Q4
        Q = [x for x in q4 if pool == "pooled" or x["pool"] == pool]
        s = {}
        for arm in ["all", "none", "sham", "true_blinded", "inverted", "narrative", "instructed", "score_arms"]:
            A = Q if arm == "all" else ([x for x in Q if x["arm"] in SCORE_ARMS] if arm == "score_arms"
                                        else [x for x in Q if x["arm"] == arm])
            if not A:
                continue
            G = [x for x in A if not x["declined"] and x["guess"] not in (None, "UNMAPPED")]
            k_ex, k_fam = sum(x["exact"] for x in A), sum(x["family"] for x in A)
            s[arm] = dict(
                n=len(A), declined=sum(x["declined"] for x in A), decline_rate=prop(byd(A, lambda x: x["declined"]), 2000),
                n_guessed=len(G),
                exact_all=dict(k=k_ex, n=len(A), p=k_ex / len(A), wilson=wilson(k_ex, len(A)),
                               chance=float(np.mean([x["p_exact"] for x in A])),
                               p_one_sided=poisbin_sf(k_ex, [x["p_exact"] for x in A])),
                exact_among_guesses=dict(k=sum(x["exact"] for x in G), n=len(G),
                                         p=(sum(x["exact"] for x in G) / len(G)) if G else None,
                                         wilson=wilson(sum(x["exact"] for x in G), len(G)),
                                         chance=float(np.mean([x["p_exact"] for x in G])) if G else None,
                                         p_one_sided=poisbin_sf(sum(x["exact"] for x in G), [x["p_exact"] for x in G])),
                family_among_guesses=dict(k=sum(x["family"] for x in G), n=len(G),
                                          chance=float(np.mean([x["p_family"] for x in G])) if G else None,
                                          p_one_sided=poisbin_sf(sum(x["family"] for x in G), [x["p_family"] for x in G])),
                guesses_are_last_top=sum(x["guess_is_last_top"] for x in G),
                guesses_are_target=sum(bool(x["guess_is_target"]) for x in G),
                top_heuristic_exact=dict(k=sum(x["own_is_last_top"] for x in A if x["n_views"]),
                                         n=sum(1 for x in A if x["n_views"])))
        s["per_designer"] = {}
        for d in sorted({x["designer"] for x in Q}):
            A = [x for x in Q if x["designer"] == d]
            G = [x for x in A if not x["declined"] and x["guess"] not in (None, "UNMAPPED")]
            s["per_designer"][d] = dict(n=len(A), declined=sum(x["declined"] for x in A), guessed=len(G),
                                        exact=sum(x["exact"] for x in A), family=sum(x["family"] for x in G),
                                        guessed_target=sum(bool(x["guess_is_target"]) for x in G),
                                        p_exact_chance_all=poisbin_sf(sum(x["exact"] for x in A), [x["p_exact"] for x in A]))
        o["self_recognition"] = s
        res[pool] = o
    dump(res, "q34_results.json")
    for pool in POOLS + ["pooled"]:
        o = res[pool]
        print(pool, "C6", {k: (o[k]["k"], o[k]["n"], round(o[k]["p"], 3)) for k in
                           ["C6_strict", "C6_lenient_ties", "C6_llm_extraction", "C6_all_sessions_missing_as_fail"]},
              "never", len(o["never_requested"]), "wrong->earlier top", o["wrong_names_earlier_view_top"], "/", o["wrong_total"])
        s = o["self_recognition"]["all"]
        print("   SR all n", s["n"], "declined", s["declined"], "exact", s["exact_all"]["k"], "p", round(s["exact_all"]["p_one_sided"], 4),
              "guessed", s["n_guessed"], "exact|guess", s["exact_among_guesses"]["k"], "fam|guess", s["family_among_guesses"]["k"],
              "target", s["guesses_are_target"])
    print(res["extraction_disagreements"])


if __name__ == "__main__":
    main()
