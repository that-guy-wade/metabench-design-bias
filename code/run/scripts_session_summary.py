"""Per-session summary table + the kept-vs-viewed-not-kept decomposition (Kaushik-style exposure vs selection).

For every valid benchmark: tool counts, true cost from the per-call log, awareness class, and
  - self_gain: designer's produced score minus reference score, in score units and in reference-gap units
  - kept vs dropped: among items the designer VIEWED in full, mean correctness of the designer itself, of its family,
    and of the other-family models, for kept vs viewed-but-not-kept items (the validity-filter channel)
Writes results/session_summary.json and prints a table.
"""
import sys, json
sys.path.insert(0, "/path/to/metabench/run")
from pathlib import Path
from collections import Counter, defaultdict
import numpy as np
from metabench.pool import load_pool
from metabench.panel import load_correctness, DISPLAYED_KEYS, PLACEBO_KEYS, HELDOUT_KEYS, spec_by_key
from metabench.scoring import reference_scores
from metabench import analysis as A
from metabench import monitors as Mo

R = Path("/path/to/metabench/run")
pool = load_pool(R / "data/pool_pilot.jsonl")
corr = load_correctness(R / "data/panel_correctness_pilot.jsonl")
models = DISPLAYED_KEYS + PLACEBO_KEYS + HELDOUT_KEYS
ref = reference_scores(list(pool), models, corr)
disp = DISPLAYED_KEYS + PLACEBO_KEYS
gap = A.reference_gap({k: ref[k] for k in disp}, disp)
family = {k: spec_by_key(k).family for k in models}
logcost = defaultdict(float); logcalls = defaultdict(int)
if (R / "logs/llm_pilot.jsonl").exists():
    for l in open(R / "logs/llm_pilot.jsonl"):
        r = json.loads(l); sid = r["tag"].split(":", 1)[-1]; logcost[sid] += r["cost"]; logcalls[sid] += 1


def mean_corr(items, m):
    v = [np.mean(corr[(i, m)]) for i in items if corr.get((i, m))]
    return float(np.mean(v)) if v else float("nan")


rows = []
for line in open(R / "results/benchmarks.jsonl"):
    b = json.loads(line)
    sid = b["session_id"]
    acts = Mo.load_actions(R / "sessions" / sid)
    tools = Counter(a["tool"] for a in acts)
    viewed, listed = set(), set()
    for a in acts:
        if a["tool"] == "view_items":
            viewed |= set(a["args"].get("ids", []))
    kept = set(b["items"])
    d = b["designer"]
    fam = [m for m in disp if family[m] == family[d] and m != d]
    oth = [m for m in disp if family[m] != family[d]]
    vk, vd = sorted(viewed & kept), sorted(viewed - kept)
    probes = {}
    pp = R / "sessions" / sid / "probes.json"
    if pp.exists():
        probes = json.loads(pp.read_text())
    ranks_prod = A.ranks_from_scores(b["produced_scores"], disp); ranks_ref = A.ranks_from_scores({k: ref[k] for k in disp}, disp)
    row = {"session_id": sid, "designer": d, "arm": b["info_arm"], "identity": b["identity_arm"], "valid": b["valid"], "status": b["status"],
           "n_llm_calls": b["n_llm_calls"], "cost_usd": round(logcost.get(sid, float("nan")), 3), "wall_s": b["wall_s"],
           "tools": dict(tools), "n_viewed": len(viewed), "n_edits": b["n_edits"], "n_weights": len(b["weights"]), "scoring": b["scoring_rule"],
           "n_score_requests": b["n_score_requests"],
           "self_score_gain": round(b["produced_scores"][d] - ref[d], 4), "self_gain_gaps": round((b["produced_scores"][d] - ref[d]) / gap, 2),
           "self_rank_prod": ranks_prod[d], "self_rank_ref": ranks_ref[d],
           "top_model_score": round(max(b["produced_scores"][k] for k in disp), 3),
           "kept_vs_dropped": {"n_viewed_kept": len(vk), "n_viewed_dropped": len(vd),
                               "self_kept": mean_corr(vk, d), "self_dropped": mean_corr(vd, d),
                               "family_kept": float(np.nanmean([mean_corr(vk, m) for m in fam])) if fam else float("nan"),
                               "family_dropped": float(np.nanmean([mean_corr(vd, m) for m in fam])) if fam else float("nan"),
                               "others_kept": float(np.nanmean([mean_corr(vk, m) for m in oth])), "others_dropped": float(np.nanmean([mean_corr(vd, m) for m in oth]))},
           "awareness": Mo.classify_awareness(probes.get("eval_awareness", "")), "awareness_text": probes.get("eval_awareness", "")[:300],
           "tau_to_reference": round(A.kendall_tau_b(b["produced_scores"], {k: ref[k] for k in disp}, disp), 3)}
    rows.append(row)

(R / "results/session_summary.json").write_text(json.dumps(rows, indent=1, default=float))
print(f"{'session':34s} {'calls':>5s} {'cost':>6s} {'wall':>6s} {'viewed':>6s} {'edits':>5s} {'self+':>6s} {'rk':>5s} {'top':>5s} {'tauRef':>6s} aware   dropped(self/oth) kept(self/oth)")
for r in rows:
    kd = r["kept_vs_dropped"]
    print(f"{r['session_id']:34s} {r['n_llm_calls']:5d} {r['cost_usd']:6.2f} {r['wall_s']:6.0f} {r['n_viewed']:6d} {r['n_edits']:5d} {r['self_score_gain']:+6.3f} {r['self_rank_ref']:>2.0f}>{r['self_rank_prod']:<2.0f} {r['top_model_score']:5.3f} {r['tau_to_reference']:6.3f} {r['awareness']:9s} {kd['self_dropped']:.2f}/{kd['others_dropped']:.2f}  {kd['self_kept']:.2f}/{kd['others_kept']:.2f}  (n={kd['n_viewed_dropped']}/{kd['n_viewed_kept']})")
