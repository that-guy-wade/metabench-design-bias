"""Merge the part outputs into results.json (EXPLORATORY).  Usage: python assemble.py"""
import json
from pathlib import Path

OUT = Path("/path/to/metabench/analysis/sensitivity")
res = {"label": "EXPLORATORY, post-unblinding sensitivity analyses (no LLM calls)",
       "scripts": ["scommon.py", "p1_simulate.py", "p1_stats.py", "p1_partial_designers.py", "p2_robust.py",
                   "p2_pooled_shared_null.py", "p3_heldout.py", "assemble.py"]}
for name, f in (("part1_followers", "p1_results.json"), ("part1_partial_designers", "p1_partial_designers.json"),
                ("part2_robustness", "p2_results.json"), ("part2_pooled_shared_null", "p2_pooled_shared_null.json"), ("part3_heldout", "p3_results.json")):
    p = OUT / f
    res[name] = json.load(open(p)) if p.exists() else None
# drop the long unresolved-triple lists into their own file
ut = {}
for pool in ("factual", "math", "code"):
    ut[pool] = res["part2_robustness"][pool].pop("d_unresolved_triples")
json.dump(ut, open(OUT / "unresolved_triples.json", "w"), indent=0)
json.dump(res, open(OUT / "results.json", "w"), indent=1, default=float)
print("wrote results.json and unresolved_triples.json")
