"""Merge per-question outputs into ../results.json (EXPLORATORY)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import OUT, dump
cost = sum(json.loads(l).get("cost", 0) for f in ("judge/c1_judge_raw.jsonl", "judge/probe_llm_raw.jsonl") for l in open(OUT / f))
man = json.load(open(OUT / "judge/c1_manual_verification.json"))["checks"]
dump({"label": "EXPLORATORY post-unblinding analysis, 2026-10-30",
      "llm_spend_usd_estimate": cost,
      "judge": {"model": "gpt-5.5-2026-04-23", "seed": 20261030, "temperature": "1 (only value allowed)", "reasoning_effort": "medium"},
      "judge_manual_agreement": {"k": sum(c["judge"] == c["analyst"] for c in man), "n": len(man)},
      "Q1_C1_compliance_and_gain": json.load(open(OUT / "q1_results.json")),
      "Q2_C1_monitor_recall": json.load(open(OUT / "q2_results.json")),
      "Q3_Q4_C6_and_self_recognition": json.load(open(OUT / "q34_results.json"))}, "results.json")
print("ok", round(cost, 2))
