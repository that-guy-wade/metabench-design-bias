"""Primary + secondary for the gemini4argon replication (PREREG.md). Exploratory."""
import json
import sys
from pathlib import Path

import numpy as np
from scipy import stats

RUN = Path("/path/to/metabench/run")
sys.path.insert(0, str(RUN))
from metabench import panel  # noqa: E402
panel.set_active("confirmatory")
from metabench.analysis import tau_to_displayed, fisher_z, ranks_from_scores, panel_keys, kendall_tau_b  # noqa: E402

OUT = Path("/path/to/metabench/analysis/exp_g4a")
WORK = Path("/path/to/metabench/unblinded/WORK_factual")
rng = np.random.default_rng(20261030)

new = [json.loads(l) for l in open(OUT / "rows.jsonl")]
new_valid = [r for r in new if r.get("valid") and r.get("displayed_order")]
orig = [json.loads(l) for l in open(WORK / "results/benchmarks.jsonl")]
g = [r for r in orig if r["designer"] == "gemini4argon" and r["valid"]]
orig_sham = [r for r in g if r["info_arm"] == "sham" and r["identity_arm"] == "blinded"]
none_rows = [r for r in g if r["info_arm"] == "none"]


def zs(rows):
    return np.array([fisher_z(tau_to_displayed(r)) for r in rows])


def rand_test(rows, n=10000):
    obs = zs(rows).mean()
    null = np.empty(n)
    keys = [[k for k in r["displayed_order"] if k in r["produced_scores"]] for r in rows]
    sc = [np.array([r["produced_scores"][k] for k in ks]) for r, ks in zip(rows, keys)]
    for b in range(n):
        vals = []
        for ks, s in zip(keys, sc):
            perm = rng.permutation(len(ks))
            order = [ks[i] for i in perm]
            pos = {k: i for i, k in enumerate(order)}
            vals.append(fisher_z(float(stats.kendalltau(s, [-pos[k] for k in ks]).statistic)))
        null[b] = np.mean(vals)
    return float(obs), float((1 + np.sum(null >= obs)) / (1 + n)), float(null.mean()), float(null.std())


def leader_gain(rows):
    base = {}
    for r in none_rows:
        rk = ranks_from_scores(r["produced_scores"], panel_keys(r))
        for k, v in rk.items():
            base.setdefault(k, []).append(v)
    out = []
    for r in rows:
        L = r["displayed_leader"]
        rk = ranks_from_scores(r["produced_scores"], panel_keys(r))
        if L in rk and L in base:
            out.append(np.mean(base[L]) - rk[L])
    return out


res = {"n_new": len(new), "n_new_valid": len(new_valid),
       "status_counts": {s: sum(1 for r in new if r.get("status") == s) for s in {r.get("status") for r in new}},
       "cost_usd_new": float(sum(r.get("est_cost_usd") or 0 for r in new))}
for name, rows in (("new", new_valid), ("original", orig_sham), ("combined", orig_sham + new_valid)):
    z = zs(rows)
    obs, p, nm, nsd = rand_test(rows)
    t = stats.ttest_1samp(z, 0.0, alternative="greater") if len(z) > 1 else None
    lg = leader_gain(rows)
    res[name] = {"n": len(rows), "mean_z": obs, "tanh_mean_z": float(np.tanh(obs)), "per_session_tau": [float(np.tanh(x)) for x in z],
                 "rand_p_one_sided": p, "null_mean": nm, "null_sd": nsd,
                 "t": float(t.statistic) if t else None, "t_p_one_sided": float(t.pvalue) if t else None,
                 "leader_gain_mean": float(np.mean(lg)) if lg else None, "leader_gain_n": len(lg),
                 "leader_gain_ci95_boot": [float(x) for x in np.percentile([np.mean(rng.choice(lg, len(lg))) for _ in range(10000)], [2.5, 97.5])] if lg else None}
spread_words = ("spread", "separation", "discriminat")
res["notes_spread_strategy_share_new"] = float(np.mean([any(w in ((r.get("final_notes") or "") + " ".join(r.get("notes") or [])).lower() for w in spread_words) for r in new_valid])) if new_valid else None
json.dump(res, open(OUT / "results.json", "w"), indent=1)
print(json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk != "per_session_tau"}) for k, v in res.items()}, indent=1))
