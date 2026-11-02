"""Q4 summaries from mechanism_sessions_<pool>.json. EXPLORATORY. Writes ../mechanism_summary.json"""
import json
from collections import defaultdict
import numpy as np
from common import *

NB = 4000
CELLS = ["none/blinded", "narrative/blinded", "sham/blinded", "sham/true", "sham/false", "true_blinded/blinded",
         "true_named/true", "inverted/blinded", "instructed/blinded"]
GROUPS = {"score_arms_excl_instructed": ["sham/blinded", "sham/true", "sham/false", "true_blinded/blinded", "true_named/true", "inverted/blinded"],
          "sham_all": ["sham/blinded", "sham/true", "sham/false"], "true_both": ["true_blinded/blinded", "true_named/true"]}


def cell(s):
    return f'{s["info_arm"]}/{s["identity_arm"]}'


def byd(S, f, cells):
    out = defaultdict(list)
    for s in S:
        if cell(s) in cells:
            v = f(s)
            if v is not None and np.isfinite(v):
                out[s["designer"]].append(v)
    return out


def est(d, seed=0):
    e, ci, nd = cluster_boot_mean(d, NB, seed)
    return {"mean": e, "ci95_cluster": ci, "n_designers": nd, "n": int(sum(len(v) for v in d.values()))}


def diff(a, b, seed=0):
    e, ci, nd = cluster_boot_diff(a, b, NB, seed)
    return {"diff": e, "ci95_cluster": ci, "n_designers": nd, "n_a": int(sum(len(v) for v in a.values())), "n_b": int(sum(len(v) for v in b.values()))}


res = {}
pooled_diff = defaultdict(dict)
for p in POOLS:
    S = json.load(open(f"{OUT}/mechanism_sessions_{p}.json"))
    R = {}
    allcells = {c: [c] for c in CELLS} | GROUPS
    # ---- difficulty (mean reference accuracy of the 100 chosen items over the 12 designer models)
    for metric in ["mean_ref_acc", "wmean_ref_acc"]:
        R[metric] = {}
        none = byd(S, lambda s: s[metric], ["none/blinded"])
        for name, cs in allcells.items():
            d = byd(S, lambda s: s[metric], cs)
            R[metric][name] = est(d) | ({"minus_none": diff(d, none)} if name != "none/blinded" else {})
    # per designer: score arms (excl instructed) minus none
    R["per_designer_score_minus_none"] = {}
    for dsg in sorted({s["designer"] for s in S}):
        a = [s["mean_ref_acc"] for s in S if s["designer"] == dsg and cell(s) in GROUPS["score_arms_excl_instructed"]]
        b = [s["mean_ref_acc"] for s in S if s["designer"] == dsg and cell(s) == "none/blinded"]
        rng = np.random.default_rng(1)
        bs = [np.mean(rng.choice(a, len(a))) - np.mean(rng.choice(b, len(b))) for _ in range(NB)]
        R["per_designer_score_minus_none"][dsg] = {"diff": float(np.mean(a) - np.mean(b)), "ci95_bench_boot": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
                                                   "n_score": len(a), "n_none": len(b)}
    # ---- difficulty of items added before vs after the first scores view (score arms) and round 1 vs later (all)
    R["added_items"] = {}
    for name, cs in allcells.items():
        r1 = byd(S, lambda s: s["acc_added_round1"], cs); rl = byd(S, lambda s: s["acc_added_later"], cs)
        pre = byd(S, lambda s: s["acc_added_pre_first_view"], cs); post = byd(S, lambda s: s["acc_added_post_first_view"], cs)
        R["added_items"][name] = {"round1": est(r1), "later": est(rl), "later_minus_round1": diff(rl, r1),
                                  "pre_first_view": est(pre) if pre else None, "post_first_view": est(post) if post else None,
                                  "post_minus_pre": diff(post, pre) if pre and post else None,
                                  "n_added_pre_mean": float(np.mean([s["n_added_pre"] for s in S if cell(s) in cs])),
                                  "n_added_post_mean": float(np.mean([s["n_added_post"] for s in S if cell(s) in cs]))}
    # ---- activity: views, edits per round
    R["activity"] = {}
    for name, cs in allcells.items():
        rows = [s for s in S if cell(s) in cs]
        act = {"n_views_per_session": est(byd(S, lambda s: s["n_views"], cs)),
               "share_sessions_with_view": float(np.mean([s["n_views"] > 0 for s in rows]))}
        for r in [1, 2, 3, 4]:
            g = lambda s, k: s["per_round"].get(str(r), s["per_round"].get(r, {})).get(k, 0)
            act[f"round{r}"] = {k: float(np.mean([g(s, k) for s in rows])) for k in
                                ["request_panel_scores", "add_items_n", "remove_items_n", "edit_item", "set_weights"]}
        act["sessions_with_nonunit_weights"] = float(np.mean([s["nonunit_weights"] > 0 for s in rows]))
        act["n_edited_items_mean"] = float(np.mean([s["n_edited"] for s in rows]))
        R["activity"][name] = act
    # ---- category mix
    cats = sorted(S[0]["cat_share"])
    R["category_share"] = {}
    none_c = {c: byd(S, lambda s, c=c: s["cat_share"][c], ["none/blinded"]) for c in cats}
    for name, cs in allcells.items():
        R["category_share"][name] = {}
        for c in cats:
            d = byd(S, lambda s, c=c: s["cat_share"][c], cs)
            R["category_share"][name][c] = est(d) | ({"minus_none": diff(d, none_c[c])} if name != "none/blinded" else {})
        R["category_share"][name]["_tv_distance_from_none"] = 0.5 * sum(abs(R["category_share"][name][c]["mean"] - np.mean([np.mean(v) for v in none_c[c].values()])) for c in cats)
    # ---- trajectories vs displayed order (sham all identities, inverted, true arms)
    R["trajectory"] = {}
    for name, cs in {"sham_blinded": ["sham/blinded"], "sham_named": ["sham/true", "sham/false"], "sham_all": GROUPS["sham_all"],
                     "inverted": ["inverted/blinded"], "true_both(first-view order)": GROUPS["true_both"]}.items():
        rows = [s for s in S if cell(s) in cs and s.get("tau_disp_traj") and len(s["tau_disp_traj"]) >= 2]
        f_first_final = byd(rows, lambda s: s["tau_disp_traj"][-1] - s["tau_disp_traj"][0], cs)
        steps = defaultdict(list)
        for s in rows:
            t = s["tau_disp_traj"]
            steps[s["designer"]].append(float(np.nanmean(np.diff(t))))
        lead = byd(rows, lambda s: s["leader_rank_traj"][-1] - s["leader_rank_traj"][0], cs)
        lag = byd(rows, lambda s: s["laggard_rank_traj"][-1] - s["laggard_rank_traj"][0], cs)
        ref = byd(rows, lambda s: s["tau_ref_traj"][-1] - s["tau_ref_traj"][0], cs)
        first = byd(rows, lambda s: s["tau_disp_traj"][0], cs)
        R["trajectory"][name] = {"n_sessions": len(rows), "tau_disp_first_view": est(first),
                                 "tau_disp_final_minus_first_view": est(f_first_final),
                                 "mean_step_change_per_view": est(steps),
                                 "leader_rank_change_final_minus_first(neg=moved up)": est(lead),
                                 "laggard_rank_change_final_minus_first(pos=moved down)": est(lag),
                                 "tau_ref_final_minus_first_view": est(ref)}
    res[p] = R
    print(p, "done", flush=True)
dump(res, f"{OUT}/mechanism_summary.json")
