"""Merge per-pool batches into one rater sheet + key, then run an independent blinding leak check on the REAL
rater file (the sampler's self-test only exercises synthetic data)."""
import csv, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from sample_diffs_conf import CONF_KEYS, CONF_NAMES
O = Path("/path/to/metabench/analysis/edit_audit")
rows, keys = [], []
for p in ["factual", "math", "code"]:
    rows += [json.loads(l) for l in open(O / "batch" / p / "rater_sheet.jsonl")]
    keys += [json.loads(l) for l in open(O / "batch" / p / "KEY_do_not_share_with_raters.jsonl")]
assert len({r["audit_id"] for r in rows}) == len(rows)
with open(O / "rater_sheet.jsonl", "w") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
with open(O / "rater_sheet.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); [w.writerow(r) for r in rows]
with open(O / "KEY_do_not_share_with_raters.jsonl", "w") as f:
    for k in keys: f.write(json.dumps(k) + "\n")
checks = {
    "designer/panel key (any field)": (re.compile(r"\b(?:" + "|".join(CONF_KEYS) + r")\b", re.I), ["rationale", "action", "items"]),
    "display name (rationale/action)": (re.compile("|".join(re.escape(n) for n in CONF_NAMES), re.I), ["rationale", "action"]),
    "family word (rationale/action)": (re.compile(r"\b(?:claude|gpt|gemini|grok|fable|opus|sonnet|haiku|luna|sol|argon|anthropic|openai|google|xai)\b", re.I), ["rationale", "action"]),
    "interface pseudonym MDL-xx (any field)": (re.compile(r"\bMDL[\s\-]?\d", re.I), ["rationale", "action", "items"]),
    "session id (any field)": (re.compile(r"T1_(?:factual|math|code)_|_r\d_rep1|_blinded_r\d"), ["rationale", "action", "items"]),
    "arm name (rationale/action)": (re.compile(r"\b(?:sham|inverted|true_blinded|true_named|instructed|narrative|none_blinded)\b", re.I), ["rationale", "action"]),
    "key fields present": (re.compile(r'"(?:session_id|designer|info_arm|identity_arm|displayed_leader)"'), ["rationale", "action", "items"]),
}
report = {}
for name, (rx, fields) in checks.items():
    hits = []
    for r in rows:
        for fld in fields:
            for m in rx.finditer(str(r[fld])):
                s = str(r[fld]); hits.append({"audit_id": r["audit_id"], "field": fld, "context": s[max(0, m.start() - 60): m.end() + 60].replace("\n", " ")})
    report[name] = {"n_hits": len(hits), "examples": hits[:8]}
    print(f"{name}: {len(hits)} hits")
    for h in hits[:8]: print("   ", h["audit_id"], h["field"], "|", h["context"])
extra = set(rows[0]) - {"audit_id", "tool", "action", "rationale", "items", "n_items_touched", "q1_changes_relative_difficulty",
                        "q2_rationale_references_scores_or_labels", "q3_direction", "q4_validity_1to5", "q5_notes"}
print("unexpected columns:", extra)
json.dump({"n_rows": len(rows), "checks": report, "unexpected_columns": sorted(extra)}, open(O / "leakcheck.json", "w"), indent=1)
