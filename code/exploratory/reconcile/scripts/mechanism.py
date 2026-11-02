"""Q4: what designers did with the scores (sham mechanism) and 'score access makes benchmarks harder'. EXPLORATORY.
Per-session features from sessions/<id>/actions.jsonl and scores_views.jsonl; item difficulty = mean reference accuracy
over the 12 displayed designer models (reference_item_outcomes, full pool). Writes ../mechanism_sessions_<pool>.json"""
import json, os, sys
from collections import defaultdict
import numpy as np, pandas as pd
from common import *

POOLDIR = {"factual": "factual_qa", "math": "math", "code": "code"}


def run(pool):
    ref = pd.read_json(f"{UNB}/WORK_{pool}/results/reference_item_outcomes.jsonl", lines=True)
    ref = ref[(ref.n_samples > 0) & ref.model_key.isin(DKEYS)]
    acc = (ref.n_correct / ref.n_samples).groupby(ref.item_id).mean().to_dict()
    cat = {r["id"]: r["category"] for r in read_jsonl(f"{ROOT}/run/pools/{POOLDIR[pool]}/pool.jsonl")}
    cats = sorted(set(cat.values()))
    pool_acc = float(np.mean(list(acc.values())))
    out = []
    for b in bench(pool):
        sid = b["session_id"]; sd = f"{UNB}/WORK_{pool}/sessions/{sid}"
        acts = read_jsonl(f"{sd}/actions.jsonl") if os.path.exists(f"{sd}/actions.jsonl") else []
        views = read_jsonl(f"{sd}/scores_views.jsonl") if os.path.exists(f"{sd}/scores_views.jsonl") else []
        items = b["items"]; w = b.get("weights") or {}
        a = [acc.get(i, np.nan) for i in items]
        wt = np.array([w.get(i, 1.0) for i in items], float)
        rec = {"session_id": sid, "designer": b["designer"], "info_arm": b["info_arm"], "identity_arm": b["identity_arm"],
               "mean_ref_acc": float(np.nanmean(a)), "wmean_ref_acc": float(np.nansum(np.array(a) * wt) / wt.sum()),
               "nonunit_weights": int(np.sum(np.abs(wt - 1) > 1e-9)), "n_edited": len(b.get("edited_items") or {}),
               "cat_share": {c: float(np.mean([cat.get(i) == c for i in items])) for c in cats},
               "n_views": sum(1 for v in views if "order" in v), "n_views_all": len(views)}
        # per-round counts
        per_round = defaultdict(lambda: defaultdict(int))
        for x in acts:
            r = x.get("round", 0); t = x["tool"]
            per_round[r][t] += 1
            if t in ("add_items", "remove_items"):
                per_round[r][t + "_n"] += len(x["args"].get("ids", []))
        rec["per_round"] = {int(r): dict(v) for r, v in per_round.items()}
        # items added before vs after the first scores view; round 1 vs later
        seen_view = False; added_pre, added_post, added_r1, added_rlater = [], [], [], []
        for x in acts:
            if x["tool"] == "request_panel_scores":
                seen_view = True
            if x["tool"] == "add_items":
                ids = [i for i in x["args"].get("ids", []) if i in acc]
                (added_post if seen_view else added_pre).extend(ids)
                (added_r1 if x.get("round", 1) == 1 else added_rlater).extend(ids)
        fin = set(items)
        f = lambda L: float(np.mean([acc[i] for i in L])) if L else None
        rec.update({"acc_added_pre_first_view": f(added_pre), "acc_added_post_first_view": f(added_post),
                    "n_added_pre": len(added_pre), "n_added_post": len(added_post),
                    "acc_added_round1": f(added_r1), "acc_added_later": f(added_rlater),
                    "acc_final_kept_from_round1": f([i for i in set(added_r1) if i in fin]),
                    "acc_final_added_later": f([i for i in set(added_rlater) - set(added_r1) if i in fin])})
        # tau trajectory vs the displayed order (sham/inverted: sigma; true arms: first-view order) and vs reference
        disp = b.get("displayed_order")
        nviews = [v for v in views if "order" in v and "true" in v]
        if disp and nviews:
            keys = [k for k in disp]
            rs = b["reference_scores"]
            traj, trajref, lead, lag, nitems = [], [], [], [], []
            for v in nviews:
                tv = v.get("true_all") or v["true"]
                if not all(k in tv for k in keys):
                    continue
                traj.append(tau_order(tv, keys)); trajref.append(tau_scores(tv, rs, keys)); nitems.append(v.get("n_items"))
                rk = ranks(tv, keys); lead.append(rk[keys[0]]); lag.append(rk[keys[-1]])
            ps = b["produced_scores"]
            traj.append(tau_order(ps, keys)); trajref.append(tau_scores(ps, rs, keys))
            rk = ranks(ps, keys); lead.append(rk[keys[0]]); lag.append(rk[keys[-1]]); nitems.append(len(items))
            rec.update({"tau_disp_traj": traj, "tau_ref_traj": trajref, "leader_rank_traj": lead, "laggard_rank_traj": lag,
                        "n_items_traj": nitems})
        out.append(rec)
    dump(out, f"{OUT}/mechanism_sessions_{pool}.json")
    print(pool, len(out))


for p in (sys.argv[1:] or POOLS):
    run(p)
