"""PREREG section 10 kept-vs-viewed decomposition (Kaushik et al.), EXPLORATORY.

For each valid benchmark in the focus cells, compare the kept set (the 100 submitted items) with 200 random
min(100, |V|)-item subsets drawn without replacement from the designer's exposed set V (exposure.py), and with 200
random 100-item subsets of the whole pool (to split the total kept-minus-pool shift into
selection = kept - random_from_viewed and exposure = random_from_viewed - random_from_pool).

Scoring is the same for kept and random sets so that only the item choice differs: unweighted mean of the
per-(item, key) reference accuracy n_correct/n_samples (reference_item_outcomes.jsonl; NaNs skipped), i.e. the
precomputed correctness of the UNEDITED items. (The produced benchmark's own produced_scores include weights and live
re-scores of edited items; tau with those is stored as kept_produced_* for comparison.)

Metrics on the fixed 13-key set K13 = 12 designer keys + placebo_sonnet55:
  tau_disp   = Kendall tau-b(subset scores, displayed_order) (displayed_order: sham = registered order shown at the
               first scores view; true_blinded = the draft's true order at the first request; none: undefined)
  tau_ref    = Kendall tau-b(subset scores, full-pool reference scores)
  tau_r1     = Kendall tau-b(subset scores, scores of the designer's own draft at the end of round 1), the draft
               replayed from add_items/remove_items in actions.jsonl and scored the same A-based way. A same-definition
               overlap control for every arm: the true_blinded display is the true order of an early draft that the
               kept set largely retains, so part of its kept-vs-viewed tau_disp is shared sampling noise, not steering.
  difficulty = mean over subset items of the item's mean reference accuracy over the 12 designer keys (as in
               analysis/reconcile); in accuracy points (x100)
Per benchmark: diff = metric(kept) - mean over draws; pctl = share of draws with metric < kept (+0.5 ties).
Aggregation: designer-averaged mean (mean of per-designer means); 95% CI from a designer-cluster bootstrap (designers
resampled, then benchmarks within designer), 5000 reps. Pooled = mean of the three pool estimates, with the same
designer draw used in every pool for each bootstrap rep.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

import numpy as np

from common import DESIGNERS, K13, OUT, POOLS, UNB, bench_rows, cell, read_jsonl, reference_matrix
from metabench.analysis import order_to_scores, tau_b_vectorised

CELLS = ["sham/blinded", "none/blinded", "true_blinded/blinded", "sham/true", "sham/false"]
N_DRAW, N_BOOT, SEED = 200, 5000, 20261030
METRICS = ["tau_disp", "tau_r1", "tau_ref", "difficulty"]
CONTRASTS = ["selection", "exposure", "total", "selection_fullview"]


def replay_draft(actions, upto_round):
    """Draft item list after every action with round <= upto_round (interface add/remove semantics)."""
    d = []
    for a in actions:
        if a["round"] > upto_round:
            break
        ids = (a["args"] or {}).get("ids") or []
        if a["tool"] == "add_items" and not a["result_summary"].startswith("ERROR"):
            for i in ids:
                if isinstance(i, str) and i not in d and POOL_IDS.get(i):
                    d.append(i)
        elif a["tool"] == "remove_items" and not a["result_summary"].startswith("ERROR"):
            d = [i for i in d if i not in set(ids)]
    return d


POOL_IDS: dict = {}


def metrics_for(idx_sets, A, D12, disp, ref, r1=None):
    """idx_sets: (n, k) item indices -> dict of arrays (n,)."""
    sc = np.nanmean(A[idx_sets], axis=1)                 # (n, 13)
    out = {"tau_r1": tau_b_vectorised(r1, sc) if r1 is not None else np.full(len(sc), np.nan),"tau_ref": tau_b_vectorised(ref, sc), "difficulty": 100 * np.nanmean(D12[idx_sets], axis=1)}
    out["tau_disp"] = tau_b_vectorised(disp, sc) if disp is not None else np.full(len(sc), np.nan)
    return out


def draws(rng, pool_idx, k):
    pool_idx = np.asarray(pool_idx)
    if len(pool_idx) <= k:
        return pool_idx[None, :]
    return np.stack([rng.choice(pool_idx, size=k, replace=False) for _ in range(N_DRAW)])


def per_session(pool, rng):
    items, ii, A = reference_matrix(pool, K13)
    D12 = np.nanmean(A[:, :12], axis=1)
    ref = np.nanmean(A, axis=0)
    POOL_IDS.clear(); POOL_IDS.update({i: True for i in items})
    replay_ok = 0
    expo = {r["session_id"]: r for r in read_jsonl(OUT / "exposure.jsonl") if r["pool"] == pool}
    out = []
    for r in bench_rows(pool):
        c = cell(r)
        if c not in CELLS:
            continue
        e = expo[r["session_id"]]
        disp = None
        if r.get("displayed_order") and c != "none/blinded":
            s = order_to_scores(r["displayed_order"])
            disp = np.array([s.get(k, np.nan) for k in K13])
            if np.isnan(disp).any():           # fixed key set: a key missing from the shown order -> tau_disp undefined
                disp = None
        acts = read_jsonl(UNB / f"WORK_{pool}" / "sessions" / r["session_id"] / "actions.jsonl")
        replay_ok += int(replay_draft(acts, 10**6) == list(r["items"]))
        d1 = [ii[i] for i in replay_draft(acts, 1)]
        r1 = np.nanmean(A[d1], axis=0) if len(d1) >= 2 else None
        kept = np.array([ii[i] for i in r["items"]])
        V = [ii[i] for i in sorted(set(e["listed"]) | set(e["viewed_full"]))]
        VF = [ii[i] for i in e["viewed_full"]]
        mk = metrics_for(kept[None, :], A, D12, disp, ref, r1)
        mv = metrics_for(draws(rng, V, 100), A, D12, disp, ref, r1)
        mf = metrics_for(draws(rng, VF, 100), A, D12, disp, ref, r1) if VF else None
        mp = metrics_for(draws(rng, np.arange(len(items)), 100), A, D12, disp, ref, r1)
        prod = np.array([r["produced_scores"][k] for k in K13])
        row = {"pool": pool, "session_id": r["session_id"], "designer": r["designer"], "cell": c, "n_draft_r1": len(d1),
               "kept_overlap_draft_r1": len(set(r["items"]) & set(items[j] for j in d1)),
               "n_exposed": len(V), "n_viewed_full": len(VF), "n_kept_not_exposed": len(e["kept_not_exposed"]),
               "kept_produced_tau_ref": float(tau_b_vectorised(ref, prod[None, :])[0]),
               "kept_produced_tau_disp": float(tau_b_vectorised(disp, prod[None, :])[0]) if disp is not None else None}
        for m in METRICS:
            k_ = float(mk[m][0])
            row[f"kept_{m}"] = k_
            row[f"randviewed_{m}"] = float(np.mean(mv[m]))
            row[f"randpool_{m}"] = float(np.mean(mp[m]))
            row[f"randfull_{m}"] = float(np.mean(mf[m])) if mf is not None else None
            row[f"pctl_viewed_{m}"] = float(np.mean(mv[m] < k_) + 0.5 * np.mean(mv[m] == k_)) if not np.isnan(k_) else None
        out.append(row)
    print(pool, "final-draft replay matches items:", replay_ok, "/", len(out), file=sys.stderr)
    return out


def contrast(row, m, which):
    k, v, p, f = row[f"kept_{m}"], row[f"randviewed_{m}"], row[f"randpool_{m}"], row[f"randfull_{m}"]
    val = {"selection": k - v, "exposure": v - p, "total": k - p,
           "selection_fullview": (k - f) if f is not None else np.nan}[which]
    return val


def by_designer(rows, fn):
    d = defaultdict(list)
    for r in rows:
        v = fn(r)
        if v is not None and not np.isnan(v):
            d[r["designer"]].append(v)
    return {k: np.array(v) for k, v in d.items()}


def dmean(bd):
    return float(np.mean([v.mean() for v in bd.values()])) if bd else float("nan")


def boot_pooled(bd_by_pool, rng):
    """bd_by_pool: {pool: {designer: values}}. Returns point (mean over pools of designer-averaged means), per-pool
    points and CIs (designer-cluster bootstrap with a shared designer draw across pools)."""
    pools = [p for p in bd_by_pool if bd_by_pool[p]]
    if not pools:
        return None
    pts = {p: dmean(bd_by_pool[p]) for p in pools}
    bs = {p: np.empty(N_BOOT) for p in pools}
    for b in range(N_BOOT):
        ds = rng.choice(DESIGNERS, size=len(DESIGNERS), replace=True)
        for p in pools:
            bd = bd_by_pool[p]
            means = [bd[d][rng.integers(0, len(bd[d]), len(bd[d]))].mean() for d in ds if d in bd]
            bs[p][b] = np.mean(means) if means else np.nan
    pooled_bs = np.nanmean(np.stack([bs[p] for p in pools]), axis=0)
    res = {p: {"est": pts[p], "ci": [float(np.nanpercentile(bs[p], 2.5)), float(np.nanpercentile(bs[p], 97.5))],
               "n_bench": int(sum(len(v) for v in bd_by_pool[p].values())), "n_designers": len(bd_by_pool[p])} for p in pools}
    if len(pools) == 3:
        res["pooled"] = {"est": float(np.mean(list(pts.values()))),
                         "ci": [float(np.nanpercentile(pooled_bs, 2.5)), float(np.nanpercentile(pooled_bs, 97.5))],
                         "n_bench": int(sum(res[p]["n_bench"] for p in pools)),
                         "n_designers": len(set().union(*[bd_by_pool[p] for p in pools]))}
    return res


def main():
    rng = np.random.default_rng(SEED)
    rows = []
    for pool in POOLS:
        rows += per_session(pool, rng)
        print("done", pool, file=sys.stderr)
    with open(OUT / "kept_vs_viewed_sessions.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    brng = np.random.default_rng(SEED + 1)
    res = {}
    for c in CELLS:
        R = [r for r in rows if r["cell"] == c]
        for m in METRICS:
            if m == "tau_disp" and c in ("none/blinded", "sham/true", "sham/false"):
                continue                     # no display (none) or a 12-key named display (fixed 13-key set undefined)
            for lvl in ["kept", "randviewed", "randpool", "randfull"]:
                res[f"{c}|{m}|level_{lvl}"] = boot_pooled({p: by_designer([r for r in R if r["pool"] == p], lambda r: r[f"{lvl}_{m}"]) for p in POOLS}, brng)
            for w in CONTRASTS:
                res[f"{c}|{m}|{w}"] = boot_pooled({p: by_designer([r for r in R if r["pool"] == p], lambda r: contrast(r, m, w)) for p in POOLS}, brng)
            res[f"{c}|{m}|pctl_viewed"] = boot_pooled({p: by_designer([r for r in R if r["pool"] == p], lambda r: r[f"pctl_viewed_{m}"]) for p in POOLS}, brng)
    # sham/blinded minus none/blinded selection effect on difficulty & tau_ref (does a score display change selection?)
    # arm minus none, per designer (designer mean in arm - designer mean in none), designer-cluster bootstrap
    for arm in ["sham/blinded", "true_blinded/blinded"]:
        for m in ["tau_r1", "tau_ref", "difficulty"]:
            for w in ["selection", "exposure"]:
                bdp = {}
                for p in POOLS:
                    a = by_designer([r for r in rows if r["pool"] == p and r["cell"] == arm], lambda r: contrast(r, m, w))
                    b = by_designer([r for r in rows if r["pool"] == p and r["cell"] == "none/blinded"], lambda r: contrast(r, m, w))
                    bdp[p] = {d: np.array([a[d].mean() - b[d].mean()]) for d in a if d in b}
                res[f"{arm.split('/')[0]}_minus_none|{m}|{w}"] = boot_pooled(bdp, brng)
    # per-designer selection on tau_disp in sham/blinded (heterogeneity)
    perd = {}
    for p in POOLS:
        bd = by_designer([r for r in rows if r["pool"] == p and r["cell"] == "sham/blinded"], lambda r: contrast(r, "tau_disp", "selection"))
        perd[p] = {d: {"mean": float(v.mean()), "n": len(v)} for d, v in bd.items()}
    res["sham/blinded|tau_disp|selection|per_designer"] = perd
    (OUT / "kept_vs_viewed_results.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
