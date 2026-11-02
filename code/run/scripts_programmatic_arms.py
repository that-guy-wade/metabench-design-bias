"""Designer-free arms for T1, scored exactly like LLM benchmarks (no LLM calls).

  random        200 random 100-item subsets (same-size random-subset control, C3)
  stratified    for each LLM benchmark in results/benchmarks.jsonl, 20 random subsets matching its category mix
  oracle        greedy steering oracle with correctness access: for each displayed key as target, pick 100 items
                maximising target's advantage over the rest (known-magnitude positive control, C4)
Each row carries a registered displayed order drawn from the same sham generator so that the sham primary endpoint
can be computed on designer-free benchmarks (expected ~0).
Writes results/programmatic_benchmarks.jsonl.
"""
import sys, json, hashlib
sys.path.insert(0, "/path/to/metabench/run")
from pathlib import Path
import numpy as np
from metabench.pool import load_pool
from metabench.panel import load_correctness, DISPLAYED_KEYS, HELDOUT_KEYS, PLACEBO_KEYS, TIERS
from metabench.scoring import reference_scores, benchmark_scores, ranking
from metabench.arms import draw_displayed_order

R = Path("/path/to/metabench/run")
pool = load_pool(R / "data/pool_pilot.jsonl")
corr = load_correctness(R / "data/panel_correctness_pilot.jsonl")
models = DISPLAYED_KEYS + PLACEBO_KEYS + HELDOUT_KEYS
ref = reference_scores(list(pool), models, corr)
ids = sorted(pool)
cats = {i: pool[i]["category"] for i in ids}
by_cat = {}
for i in ids:
    by_cat.setdefault(cats[i], []).append(i)
rng = np.random.default_rng(777)
out_path = R / "results/programmatic_benchmarks.jsonl"
out_path.parent.mkdir(exist_ok=True)
rows = []

def row(kind, rep, items, target=None, displayed_order=None, extra=None):
    sc = benchmark_scores(items, {}, models, corr)
    r = {"session_id": f"PROG_{kind}_r{rep}", "designer": "programmatic", "info_arm": kind, "identity_arm": "blinded", "tier": "T1",
         "replicate": rep, "seed": int(rng.integers(1 << 31)), "valid": True, "n_items": len(items), "items": list(items), "weights": {},
         "displayed_order": displayed_order, "displayed_leader": (displayed_order[0] if displayed_order else target), "target_model": target,
         "named": False, "produced_scores": {k: round(v, 5) for k, v in sc.items()}, "reference_scores": {k: round(v, 5) for k, v in ref.items()},
         "status": "ok"}
    if extra:
        r.update(extra)
    rows.append(r)

disp = DISPLAYED_KEYS + PLACEBO_KEYS
# 1) random subsets with a registered random displayed order
for rep in range(200):
    items = list(rng.choice(ids, 100, replace=False))
    order = draw_displayed_order(rng, disp, False, TIERS)
    row("random", rep, items, displayed_order=order)

# 2) stratified-random matched to each LLM benchmark's category mix
bpath = R / "results/benchmarks.jsonl"
if bpath.exists():
    n = 0
    for line in open(bpath):
        b = json.loads(line)
        if not b.get("valid"):
            continue
        mix = {}
        for i in b["items"]:
            mix[cats[i]] = mix.get(cats[i], 0) + 1
        for rep in range(20):
            items = []
            for c, k in mix.items():
                items += list(rng.choice(by_cat[c], k, replace=False))
            order = draw_displayed_order(rng, disp, False, TIERS)
            row("stratified", n, items, displayed_order=order, extra={"matched_session": b["session_id"]})
            n += 1

# 3) greedy steering oracle: maximise target's mean advantage over the other displayed models
def item_adv(i, target):
    t = corr.get((i, target)); 
    if not t: return None
    tm = sum(t) / len(t)
    others = [sum(corr[(i, m)]) / len(corr[(i, m)]) for m in disp if m != target and corr.get((i, m))]
    return tm - (sum(others) / len(others) if others else 0.0)

for target in disp:
    adv = [(item_adv(i, target), i) for i in ids]
    adv = [(a, i) for a, i in adv if a is not None]
    adv.sort(reverse=True)
    for rep in range(3):   # three oracle strengths: top-100, top-200 random 100, top-400 random 100
        pool_k = [100, 200, 400][rep]
        cand = [i for _, i in adv[:pool_k]]
        items = list(rng.choice(cand, 100, replace=False)) if pool_k > 100 else cand
        row("oracle", rep, items, target=target, extra={"oracle_pool": pool_k})

with open(out_path, "w") as f:
    for r in rows:
        f.write(json.dumps(r) + "\n")
print(f"wrote {len(rows)} programmatic benchmarks to {out_path}")
# quick summary: oracle target rank gain vs reference
ref_rank = {k: j + 1 for j, k in enumerate(ranking({k: ref[k] for k in disp}))}
for r in rows:
    if r["info_arm"] == "oracle" and r["oracle_pool"] == 100:
        pr = {k: j + 1 for j, k in enumerate(ranking({k: r["produced_scores"][k] for k in disp}))}
        t = r["target_model"]
        print(f"oracle target={t:18s} ref_rank={ref_rank[t]:2d} produced_rank={pr[t]:2d} score {ref[t]:.3f}->{r['produced_scores'][t]:.3f}")
