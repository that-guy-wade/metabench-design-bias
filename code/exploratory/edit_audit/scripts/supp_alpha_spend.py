"""Run after run_analysis.py: supplementary alphas (excluding instructed; binary directional-vs-not) and LLM spend -> results.json."""
import csv, json
import numpy as np
U = list(csv.DictReader(open("/path/to/metabench/analysis/edit_audit/units_labelled.csv")))
def an(pairs):
    cats = sorted({x for p in pairs for x in p}); ix = {c: j for j, c in enumerate(cats)}
    o = np.zeros((len(cats),) * 2)
    for a, b in pairs: o[ix[a], ix[b]] += 1; o[ix[b], ix[a]] += 1
    n = o.sum(); nc = o.sum(1)
    return 1 - ((n - np.trace(o)) / n) / ((n * n - (nc ** 2).sum()) / (n * (n - 1)))
rng = np.random.default_rng(1)
def boot(pairs):
    out = [an([pairs[j] for j in rng.integers(0, len(pairs), len(pairs))]) for _ in range(2000)]
    return [float(np.nanpercentile(out, 2.5)), float(np.nanpercentile(out, 97.5))]
D = ("favours_leader", "disfavours_leader")
ex = [(u["d1"], u["d2"]) for u in U if u["arm"] != "instructed"]
bi = [(u["d1"] in D, u["d2"] in D) for u in U]
bi_ex = [(u["d1"] in D, u["d2"] in D) for u in U if u["arm"] != "instructed"]
out = {"alpha_direction_excl_instructed": [an(ex), boot(ex), len(ex)], "alpha_directional_vs_not_all": [an(bi), boot(bi), len(bi)],
       "alpha_directional_vs_not_excl_instructed": [an(bi_ex), boot(bi_ex), len(bi_ex)]}
O = "/path/to/metabench/analysis/edit_audit/"
r = json.load(open(O + "results.json")); r["supp_alpha"] = out
spend = {w: sum(json.loads(l)["cost"] for l in open(O + f"raw/{w}_raw.jsonl")) for w in ["r1", "r2", "adj"]}
spend["muse_smoke_test"] = 0.016
spend["total"] = sum(spend.values())
spend["note"] = "gpt-5.5 $5/$30, claude-opus-5-5 $4/$20 per 1M tokens (metabench/llm.py PRICES); muse-wonder price unknown, estimated at $3/$15 as in analysis/exp_muse"
r["llm_spend_usd"] = spend
r["models"] = {"r1": "gpt-5.5 (OpenAI chat.completions, default reasoning effort and temperature)", "r2": "claude-opus-5-5 (adaptive thinking, effort medium = default; no temperature parameter)", "adjudicator": "muse-wonder via https://<openai-compatible-provider>/v1"}
json.dump(r, open(O + "results.json", "w"), indent=1, default=float)
