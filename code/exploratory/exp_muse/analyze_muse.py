"""Pre-registered analysis of the Muse replication (PREREG.md). Exploratory."""
import json
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from scipy import stats

RUN = Path("/path/to/metabench/run")
OUT = Path("/path/to/metabench/analysis/exp_muse")
CTRL = Path("/path/to/metabench/analysis/controls")
sys.path.insert(0, str(RUN))
sys.path.insert(0, str(CTRL))
sys.path.insert(0, str(CTRL / "scripts"))
from metabench import panel  # noqa: E402
panel.set_active("confirmatory")
from metabench.analysis import tau_to_displayed, fisher_z, ranks_from_scores  # noqa: E402
import judge_c1 as J  # noqa: E402

rng = np.random.default_rng(20261031)
rows = [json.loads(l) for l in open(OUT / "rows.jsonl")]
valid = [r for r in rows if r.get("valid")]
res = {"n_rows": len(rows), "n_valid": len(valid),
       "invalid": {r["session_id"]: r.get("status") for r in rows if not r.get("valid")}}


def keys12(r):
    return [k for k in r["displayed_keys"] if not k.startswith("placebo_")]


def rank_of(r, model):
    m = "sonnet55" if model == "placebo_sonnet55" else model
    return ranks_from_scores(r["produced_scores"], keys12(r))[m]


def psi(sham):
    """designer-averaged Fisher z; randomisation p (uniform re-draws); benchmark bootstrap CI within designer."""
    by_d = defaultdict(list)
    for r in sham:
        by_d[r["designer"]].append(fisher_z(tau_to_displayed(r)))
    stat = np.mean([np.mean(v) for v in by_d.values()])
    keys = [[k for k in r["displayed_order"] if k in r["produced_scores"]] for r in sham]
    sc = [np.array([r["produced_scores"][k] for k in ks]) for r, ks in zip(sham, keys)]
    null = np.empty(10000)
    for b in range(10000):
        bd = defaultdict(list)
        for r, ks, s in zip(sham, keys, sc):
            perm = rng.permutation(len(ks))
            pos = {ks[i]: j for j, i in enumerate(perm)}
            bd[r["designer"]].append(fisher_z(float(stats.kendalltau(s, [-pos[k] for k in ks]).statistic)))
        null[b] = np.mean([np.mean(v) for v in bd.values()])
    boots = [np.mean([np.mean(rng.choice(v, len(v))) for v in by_d.values()]) for _ in range(10000)]
    return {"n": len(sham), "per_designer": {d: [len(v), float(np.tanh(np.mean(v)))] for d, v in by_d.items()},
            "psi": float(np.tanh(stat)), "p_one_sided": float((1 + np.sum(null >= stat)) / 10001),
            "ci95_bench": [float(np.tanh(x)) for x in np.percentile(boots, [2.5, 97.5])],
            "upper95_one_sided": float(np.tanh(np.percentile(boots, 95)))}


def gain(arm_rows, base_rows, model_of):
    base = defaultdict(list)
    for r in base_rows:
        for k, v in ranks_from_scores(r["produced_scores"], keys12(r)).items():
            base[(r["designer"], r["pool_name"], k)].append(v)
    by_d = defaultdict(list)
    for r in arm_rows:
        m = model_of(r)
        m2 = "sonnet55" if m == "placebo_sonnet55" else m
        b = base.get((r["designer"], r["pool_name"], m2))
        if b:
            by_d[r["designer"]].append(np.mean(b) - rank_of(r, m))
    allv = [x for v in by_d.values() for x in v]
    boots = [np.mean([np.mean(rng.choice(v, len(v))) for v in by_d.values()]) for _ in range(10000)] if allv else [np.nan]
    return {"n": len(allv), "mean": float(np.mean([np.mean(v) for v in by_d.values()])) if allv else None,
            "per_designer": {d: [len(v), float(np.mean(v))] for d, v in by_d.items()},
            "ci95_bench": [float(x) for x in np.percentile(boots, [2.5, 97.5])]}


for scope in ["factual", "math", "code", "pooled"]:
    pick = (lambda r: True) if scope == "pooled" else (lambda r, s=scope: r["pool_name"] == s)
    sham = [r for r in valid if r["info_arm"] == "sham" and pick(r)]
    none = [r for r in valid if r["info_arm"] == "none" and pick(r)]
    res[scope] = {"psi": psi(sham) if sham else None,
                  "S1_leader_gain": gain(sham, none, lambda r: r["displayed_leader"])}

# rigging compliance: same judge and rubric as analysis/controls
J.sess_dir = lambda pool, sid: OUT / "sessions" / sid
instr = [r for r in valid if r["info_arm"] == "instructed"]
raw_path = OUT / "judge_raw.jsonl"
done = {json.loads(l)["session_id"]: json.loads(l) for l in open(raw_path)} if raw_path.exists() else {}
todo = [r for r in instr if r["session_id"] not in done]
if todo:
    c = J.client()
    with ThreadPoolExecutor(8) as ex, open(raw_path, "a") as f:
        for o in ex.map(lambda r: J.call(c, r["session_id"], J.build_input(r["pool_name"], r)), todo):
            f.write(json.dumps(o) + "\n")
            done[o["session_id"]] = o
lab = {}
for sid, o in done.items():
    try:
        j = json.loads(o["raw"])
        lab[sid] = str(j.get("label") or j.get("classification") or "").upper()
    except Exception:  # noqa: BLE001
        lab[sid] = "PARSE_ERROR"
counts = defaultdict(lambda: defaultdict(int))
for r in instr:
    counts[r["designer"]][lab.get(r["session_id"], "MISSING")] += 1
res["instructed_labels"] = {d: dict(v) for d, v in counts.items()}
base_none = [r for r in valid if r["info_arm"] == "none"]
for grp in ["ALL", "COMPLIED", "REFUSED"]:
    sel = [r for r in instr if grp == "ALL" or lab.get(r["session_id"], "").startswith(grp)]
    res[f"instructed_gain_{grp}"] = gain(sel, base_none, lambda r: r["target_model"])
res["instructed_target_first"] = {d: sum(1 for r in instr if r["designer"] == d and rank_of(r, r["target_model"]) == 1)
                                  for d in counts}
res["judge_cost_usd"] = float(sum(o.get("cost", 0) for o in done.values()))
json.dump(res, open(OUT / "results.json", "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "invalid"}, indent=1)[:6000])
