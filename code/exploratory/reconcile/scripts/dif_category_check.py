"""Q3 follow-up: is the reference-top model's pool-wide Rasch residual structured by item category / difficulty?
Anchor rows only (designer-free). Rasch fitted as in dif.py (stage 1). Writes ../dif_category_check.json"""
import numpy as np, pandas as pd, scipy.sparse as sp, json
from common import *
import importlib.util

out = {}
POOLDIR = {"factual": "factual_qa", "math": "math", "code": "code"}
for pool in POOLS:
    ref = pd.read_json(f"{UNB}/WORK_{pool}/results/reference_item_outcomes.jsonl", lines=True)
    ref = ref[ref.n_samples > 0].reset_index(drop=True)
    models = sorted(ref.model_key.unique()); items = sorted(ref.item_id.unique())
    mi = {m: i for i, m in enumerate(models)}; ii = {k: i for i, k in enumerate(items)}
    rm = ref.model_key.map(mi).values; ri = ref.item_id.map(ii).values; N = len(ref)
    X = sp.hstack([sp.csr_matrix((np.ones(N), (np.arange(N), rm)), shape=(N, len(models))),
                   sp.csr_matrix((np.ones(N), (np.arange(N), ri)), shape=(N, len(items)))[:, 1:]]).tocsr()
    y = ref.n_correct.values.astype(float); n = ref.n_samples.values.astype(float)
    b = np.zeros(X.shape[1]); R = 1e-4
    for _ in range(60):
        mu = 1 / (1 + np.exp(-(X @ b)))
        g = X.T @ (y - n * mu) - R * b
        H = (X.T @ sp.diags(n * mu * (1 - mu)) @ X).toarray() + R * np.eye(X.shape[1])
        st = np.linalg.solve(H, g); b += st
        if np.max(np.abs(st)) < 1e-7: break
    p = 1 / (1 + np.exp(-(X @ b)))
    ref["resid"] = y / n - p
    cat = {r["id"]: r["category"] for r in read_jsonl(f"{ROOT}/run/pools/{POOLDIR[pool]}/pool.jsonl")}
    ref["cat"] = ref.item_id.map(cat)
    r0 = bench(pool)[0]["reference_scores"]; top = max(DKEYS, key=lambda k: r0[k])
    t = ref[ref.model_key == top]
    # how often each item is selected (valid benchmarks, none arm and all arms)
    B = bench(pool)
    sel_none = pd.Series([i for b_ in B if b_["info_arm"] == "none" for i in b_["items"]]).value_counts()
    sel_all = pd.Series([i for b_ in B for i in b_["items"]]).value_counts()
    t = t.assign(sel_none=t.item_id.map(sel_none).fillna(0), sel_all=t.item_id.map(sel_all).fillna(0))
    out[pool] = {"top_model": top,
                 "top_resid_by_category": t.groupby("cat").resid.agg(["mean", "count"]).to_dict(orient="index"),
                 "top_resid_selection_weighted_none": float(np.sum(t.resid * t.sel_none) / t.sel_none.sum()),
                 "top_resid_selection_weighted_all_arms": float(np.sum(t.resid * t.sel_all) / t.sel_all.sum()),
                 "top_resid_unweighted": float(t.resid.mean()),
                 "corr_top_resid_vs_times_selected_none": float(np.corrcoef(t.resid, t.sel_none)[0, 1])}
    print(pool, json.dumps(out[pool], default=float)[:600])
dump(out, f"{OUT}/dif_category_check.json")
