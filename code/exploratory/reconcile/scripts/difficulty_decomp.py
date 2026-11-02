"""Q4 follow-up: is the score-arm difficulty shift between categories (source mix) or within categories?
predicted = mean over chosen items of their category's pool-mean reference accuracy; within = actual - predicted.
Contrast score arms (sham, true_named, true_blinded, inverted) minus none, designer-cluster bootstrap. EXPLORATORY."""
import json
import numpy as np, pandas as pd
from common import *
POOLDIR = {"factual": "factual_qa", "math": "math", "code": "code"}
out = {}
for p in POOLS:
    ref = pd.read_json(f"{UNB}/WORK_{p}/results/reference_item_outcomes.jsonl", lines=True)
    ref = ref[(ref.n_samples > 0) & ref.model_key.isin(DKEYS)]
    acc = (ref.n_correct / ref.n_samples).groupby(ref.item_id).mean()
    cat = pd.Series({r["id"]: r["category"] for r in read_jsonl(f"{ROOT}/run/pools/{POOLDIR[p]}/pool.jsonl")})
    cmean = acc.groupby(cat.reindex(acc.index)).mean()
    pred = {i: cmean[cat[i]] for i in acc.index}
    rows = []
    for b in bench(p):
        a = np.mean([acc[i] for i in b["items"]]); pr = np.mean([pred[i] for i in b["items"]])
        rows.append((b["designer"], b["info_arm"], a, pr, a - pr))
    res = {"pool_category_mean_acc": cmean.to_dict()}
    for j, nm in [(2, "actual"), (3, "category_predicted"), (4, "within_category")]:
        sc = by = None
        a_, b_ = {}, {}
        for d, arm, *v in rows:
            val = [None, None, *v][j]
            if arm in ("sham", "true_named", "true_blinded", "inverted"):
                a_.setdefault(d, []).append(val)
            elif arm == "none":
                b_.setdefault(d, []).append(val)
        e, ci, nd = cluster_boot_diff(a_, b_, 4000, 7)
        res[nm] = {"score_minus_none": e, "ci95_cluster": ci, "n_designers": nd, "n_score": sum(map(len, a_.values())), "n_none": sum(map(len, b_.values()))}
    out[p] = res
    print(p, {k: round(v["score_minus_none"], 4) for k, v in res.items() if k != "pool_category_mean_acc"})
dump(out, f"{OUT}/difficulty_decomp.json")
