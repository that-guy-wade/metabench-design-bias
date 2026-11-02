#!/usr/bin/env python3
"""Sample design diffs from MetaBench session action logs for blinded human audit.

Unit of audit: one *diff* = one action that changes the draft (add_items, remove_items, edit_item,
set_weights, set_format) together with the designer's most recent write_notes text before it
(the rationale) and the item text of every item the action touches.

Blinding: the rater file contains the diff, the item text(s) and the rationale.  It does NOT contain
the designer, the information arm, the identity arm, the session id, or any model label.  Any model
label or display name that appears in the rationale is replaced by a per-session pseudonym X1..Xn,
and numeric scores are kept.  The key file (designer, arms, session, the X-map) is written separately.

Stratification: by (info_arm, designer); n_per_stratum diffs per stratum (or all if fewer).
Deterministic under --seed.

Usage:
  sample_diffs.py --sessions run/sessions --benchmarks run/results/benchmarks.jsonl \
                  --out run/human_audit/audit_batch_01 --n-per-stratum 12 --seed 20261025
  sample_diffs.py --self-test
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

DIFF_TOOLS = {"add_items", "remove_items", "edit_item", "set_weights", "set_format"}

# model keys / display names that may leak into rationales.
# DEVIATION (exploratory audit 2026-10-31): the frozen list covered the PILOT panel only; extended here to the
# confirmatory panel (keys, display names, MDL-xx interface pseudonyms, family words, developer names).
CONF_KEYS = ["fable51", "sonnet55", "opus5", "gpt61sol", "gpt6luna", "gpt55", "gemini4argon", "gemini38flash",
             "gemini31pro", "grok47", "grok45", "grok43", "placebo_sonnet55", "heldout_sonnet46", "heldout_gpt54",
             "heldout_gemini35flash", "heldout_grok420"]
CONF_NAMES = ["Claude Fable 5.1", "Claude Sonnet 5.5 (B)", "Claude Sonnet 5.5", "Claude Opus 5", "GPT-6.1 Sol", "GPT-6 Luna",
              "GPT-5.5", "Gemini 4 Argon", "Gemini 3.8 Flash", "Gemini 3.1 Pro", "Grok 4.7", "Grok 4.5", "Grok 4.3",
              "Claude Sonnet 4.6", "GPT-5.4", "Gemini 3.5 Flash", "Gemini 2.5 Pro", "Grok 4.20"]
def _flex(name):
    return r"\b" + r"[\s\-]*".join(re.escape(tok) for tok in re.split(r"[\s\-]+", name)) + r"(?!\w|\.\d)"
LABEL_PATTERNS = (
    [r"\bMDL[\s\-]?\d{1,2}\b"]
    + [_flex(n) for n in sorted(CONF_NAMES, key=len, reverse=True)]
    + [r"\b(?:" + "|".join(sorted(CONF_KEYS, key=len, reverse=True)) + r")\b"]
    + [r"\b(?:claude[\s\-]*)?(?:fable|opus|sonnet|haiku|mythos)(?:[\s\-]*\d+(?:\.\d+)?)?(?:\s*\(B\))?",
       r"\bgpt(?:[\s\-]*\d+(?:\.\d+)?(?:[\s\-]*(?:sol|luna|mini|nano))?)?\b",
       r"\bgemini(?:[\s\-]*\d+(?:\.\d+)?)?(?:[\s\-]*(?:pro|flash|argon))?\b",
       r"\bgrok(?:[\s\-]*\d+(?:\.\d+)?)?\b",
       r"\b(?:sol|luna|argon)\b", r"\bclaude\b", r"\b(?:anthropic|openai|google|deepmind|xai)\b"]
    + [  # frozen pilot patterns kept
    r"Claude Opus 5\.5", r"Claude Sonnet 4\.6", r"Claude Haiku 4\.5",
    r"GPT-5\.4 mini", r"GPT-5\.4 nano", r"GPT-5\.1", r"GPT-4\.1", r"GPT-4o mini",
    r"\bopus55\b", r"\bsonnet46\b", r"\bhaiku45\b", r"\bgpt54mini\b", r"\bgpt54nano\b",
    r"\bgpt51\b", r"\bgpt41\b", r"\bgpt4omini\b",
    r"\bModel [A-Z]\b", r"\bM(?:odel)?-?\d{1,2}\b"])
MAX_ITEM_CHARS = None
LABEL_RE = re.compile("|".join(f"(?:{p})" for p in LABEL_PATTERNS), re.IGNORECASE)


def canon(tok: str) -> str:
    """Canonical form so 'MDL-03'/'mdl 03' or 'Grok 4.7'/'Grok-4.7'/'grok47' share one pseudonym."""
    t = re.sub(r"[\s\-_]+", "", tok.lower()).replace("claude", "")
    return t.replace(".", "")


_SLASH_LIST = re.compile(r"\b(MDL[\s\-]?)(\d{1,2})((?:\s*/\s*\d{1,2}\b)+)", re.IGNORECASE)


def expand_shorthand(text: str) -> str:
    """'MDL-01/03/12' -> 'MDL-01/MDL-03/MDL-12' so every label gets its own pseudonym (no raw label numbers survive)."""
    def rep(m):
        nums = [m.group(2)] + re.findall(r"\d{1,2}", m.group(3))
        return "/".join(f"MDL-{n}" for n in nums)
    return _SLASH_LIST.sub(rep, text or "")


def pseudonymise(text: str, xmap: dict[str, str]) -> str:
    text = expand_shorthand(text)
    def rep(m):
        tok = canon(m.group(0))
        if tok not in xmap:
            xmap[tok] = f"X{len(xmap) + 1}"
        return xmap[tok]
    return LABEL_RE.sub(rep, text or "")


def load_jsonl(p: Path):
    with open(p) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_sessions(sessions_dir: Path, benchmarks_path: Path | None, valid_only: bool = False, arms: set | None = None):
    meta = {}
    if benchmarks_path and benchmarks_path.exists():
        for b in load_jsonl(benchmarks_path):
            meta[b["session_id"]] = b
    sessions = []
    for sdir in sorted(sessions_dir.iterdir()):
        ap = sdir / "actions.jsonl"
        if not ap.exists():
            continue
        actions = list(load_jsonl(ap))
        sid = sdir.name
        m = meta.get(sid, {})
        if valid_only and not m.get("valid"):
            continue
        if arms and m.get("info_arm") not in arms:
            continue
        # fall back to a session meta.json if present
        mp = sdir / "meta.json"
        if not m and mp.exists():
            m = json.loads(mp.read_text())
        sessions.append({"session_id": sid, "designer": m.get("designer", "?"), "info_arm": m.get("info_arm", "?"),
                         "identity_arm": m.get("identity_arm", "?"), "displayed_leader": m.get("displayed_leader"),
                         "target_model": m.get("target_model"), "label_map": m.get("label_map") or {}, "pool_name": m.get("pool_name"),
                         "actions": actions})
    return sessions


def extract_diffs(session: dict, pool: dict[str, dict]) -> list[dict]:
    diffs = []
    last_note = ""
    for i, a in enumerate(session["actions"]):
        tool = a.get("tool")
        if tool == "write_notes":
            last_note = (a.get("args") or {}).get("text", "") or ""
            continue
        if tool not in DIFF_TOOLS:
            continue
        args = a.get("args") or {}
        ids = []
        if tool in ("add_items", "remove_items"):
            ids = list(args.get("ids", []))
        elif tool == "edit_item":
            ids = [args.get("id")] if args.get("id") else []
        elif tool == "set_weights":
            w = args.get("weights", {})
            ids = list(w.keys()) if isinstance(w, dict) else []
        items = []
        for iid in ids[:10]:   # cap item text shown per diff
            it = pool.get(iid)
            if it:
                opts = "\n".join(f"{chr(65 + j)}. {o}" for j, o in enumerate(it["options"]))
                q = it["question"]
                if MAX_ITEM_CHARS and len(q) > MAX_ITEM_CHARS:   # DEVIATION: cap long (code) statements for LLM-rater cost
                    q = q[:MAX_ITEM_CHARS] + f" [... statement shortened for this sheet; {len(it['question'])} chars in full]"
                items.append({"id": iid, "category": it["category"], "text": f"{q}\n{opts}\nKey: {it['answer']}"})
            else:
                items.append({"id": iid, "category": "?", "text": "(item text unavailable)"})
        diffs.append({"session_id": session["session_id"], "action_index": i, "round": a.get("round"), "tool": tool,
                      "args": args, "rationale": last_note, "items": items, "n_items_touched": len(ids)})
    return diffs


def sample(sessions, pool, n_per_stratum: int, seed: int):
    rng = random.Random(seed)
    strata = defaultdict(list)
    for s in sessions:
        for d in extract_diffs(s, pool):
            strata[(s["info_arm"], s["designer"])].append((s, d))
    chosen = []
    for key in sorted(strata):
        rows = strata[key]
        rng.shuffle(rows)
        chosen.extend(rows[:n_per_stratum])
    rng.shuffle(chosen)
    return chosen, {k: len(v) for k, v in strata.items()}


def write_batch(chosen, out_dir: Path, seed: int, id_prefix: str = "A"):
    out_dir.mkdir(parents=True, exist_ok=True)
    rater_rows, key_rows = [], []
    xmaps: dict[str, dict] = defaultdict(dict)
    for k, (s, d) in enumerate(chosen):
        audit_id = f"{id_prefix}{k + 1:04d}"
        xmap = xmaps[s["session_id"]]
        rationale = pseudonymise(d["rationale"], xmap)
        args_txt = json.dumps(d["args"], ensure_ascii=False)
        args_txt = pseudonymise(args_txt, xmap)
        item_block = "\n\n---\n\n".join(f"[{it['id']} | {it['category']}]\n{it['text']}" for it in d["items"])
        rater_rows.append({"audit_id": audit_id, "tool": d["tool"], "action": args_txt, "rationale": rationale,
                           "items": item_block, "n_items_touched": d["n_items_touched"],
                           # annotation fields (blank)
                           "q1_changes_relative_difficulty": "", "q2_rationale_references_scores_or_labels": "",
                           "q3_direction": "", "q4_validity_1to5": "", "q5_notes": ""})
        key_rows.append({"audit_id": audit_id, "session_id": s["session_id"], "action_index": d["action_index"], "round": d["round"],
                         "designer": s["designer"], "info_arm": s["info_arm"], "identity_arm": s["identity_arm"],
                         "displayed_leader": s.get("displayed_leader"),
                         "displayed_leader_pseudonym": xmap.get(str(s.get("displayed_leader")), None),
                         "target_model": s.get("target_model"), "pool": s.get("pool_name"),
                         "leader_label": (s.get("label_map") or {}).get(s.get("displayed_leader")),
                         "target_label": (s.get("label_map") or {}).get(s.get("target_model")),
                         "xmap": json.dumps(xmap)})
    # resolve leader/target pseudonyms against the FINAL per-session X-map (frozen code used a raw key lookup)
    for kr in key_rows:
        xm = xmaps[kr["session_id"]]
        kr["xmap"] = json.dumps(xm)
        kr["leader_pseudonym"] = xm.get(canon(kr["leader_label"])) if kr["leader_label"] else None
        kr["target_pseudonym"] = xm.get(canon(kr["target_label"])) if kr["target_label"] else None
    with open(out_dir / "rater_sheet.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rater_rows[0].keys()) if rater_rows else ["audit_id"])
        w.writeheader()
        for r in rater_rows:
            w.writerow(r)
    with open(out_dir / "rater_sheet.jsonl", "w") as f:
        for r in rater_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(out_dir / "KEY_do_not_share_with_raters.jsonl", "w") as f:
        for r in key_rows:
            f.write(json.dumps(r) + "\n")
    (out_dir / "batch_meta.json").write_text(json.dumps({"seed": seed, "n": len(chosen)}, indent=2))
    return len(rater_rows)


def self_test() -> bool:
    """Builds a tiny synthetic session tree, samples, and checks blinding invariants."""
    tmp = Path(tempfile.mkdtemp(prefix="audit_selftest_"))
    pool = {f"P{i:04d}": {"id": f"P{i:04d}", "category": "law" if i % 2 else "physics",
                          "question": f"Q{i}?", "options": ["a", "b", "c", "d"], "answer": "B"} for i in range(1, 40)}
    sessions_dir = tmp / "sessions"
    bench = tmp / "benchmarks.jsonl"
    rows = []
    for sid, designer, arm, leader in [("s1", "opus55", "sham", "gpt55"), ("s2", "gpt55", "none", None), ("s3", "sonnet55", "sham", "opus55")]:
        d = sessions_dir / sid
        d.mkdir(parents=True)
        acts = [
            {"session_id": sid, "round": 1, "t": 0, "tool": "write_notes", "args": {"text": f"GPT-5.5 is leading; Claude Opus 5.5 trails. Keep items where Model B scores 0.9. MDL-03 beats MDL-11; Grok 4.7 and grok-4.7 tie; GPT-6.1 Sol, Gemini 4 Argon, Claude Fable 5.1 and Sonnet 5.5 (B) and fable51."}, "result_summary": "ok"},
            {"session_id": sid, "round": 1, "t": 1, "tool": "add_items", "args": {"ids": ["P0001", "P0002"]}, "result_summary": "ok"},
            {"session_id": sid, "round": 1, "t": 2, "tool": "request_panel_scores", "args": {}, "result_summary": "ok"},
            {"session_id": sid, "round": 2, "t": 3, "tool": "remove_items", "args": {"ids": ["P0002"]}, "result_summary": "ok"},
            {"session_id": sid, "round": 2, "t": 4, "tool": "set_weights", "args": {"weights": {"P0001": 2.0}}, "result_summary": "ok"},
            {"session_id": sid, "round": 2, "t": 5, "tool": "submit", "args": {}, "result_summary": "ok"},
        ]
        with open(d / "actions.jsonl", "w") as f:
            for a in acts:
                f.write(json.dumps(a) + "\n")
        rows.append({"session_id": sid, "designer": designer, "info_arm": arm, "identity_arm": "blinded", "displayed_leader": leader,
                     "items": ["P0001"], "weights": {}, "displayed_order": [], "produced_scores": {}, "reference_scores": {}})
    with open(bench, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    sessions = load_sessions(sessions_dir, bench)
    chosen, counts = sample(sessions, pool, n_per_stratum=2, seed=1)
    out = tmp / "batch"
    n = write_batch(chosen, out, seed=1)
    ok = bool(n == 6)
    # determinism
    chosen2, _ = sample(sessions, pool, n_per_stratum=2, seed=1)
    ok &= [c[1]["action_index"] for c in chosen] == [c[1]["action_index"] for c in chosen2]
    # blinding: no designer/arm/label strings in rater sheet
    rater_txt = (out / "rater_sheet.jsonl").read_text()
    for bad in ["opus55", "gpt55", "sonnet55", "sham", "GPT-5.5", "Claude Opus", "Model B", "\"session_id\"", "MDL-", "Grok", "Sol", "Argon", "Fable", "fable51", "Sonnet", "(B)"]:
        if bad in rater_txt:
            print("BLINDING LEAK:", bad)
            ok = False
    ok &= "X1" in rater_txt and "X2" in rater_txt
    # key file reconstructs mapping
    keys = list(load_jsonl(out / "KEY_do_not_share_with_raters.jsonl"))
    ok &= all("designer" in k and "info_arm" in k for k in keys)
    print(f"self-test: n={n} strata={counts} ok={ok}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", type=Path)
    ap.add_argument("--benchmarks", type=Path)
    ap.add_argument("--pool", type=Path, default=Path("/path/to/metabench/run/data/pool_pilot.jsonl"))
    ap.add_argument("--out", type=Path)
    ap.add_argument("--n-per-stratum", type=int, default=12)
    ap.add_argument("--seed", type=int, default=20261025)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--valid-only", action="store_true")
    ap.add_argument("--arms", default="")
    ap.add_argument("--id-prefix", default="A")
    ap.add_argument("--max-item-chars", type=int, default=0)
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    global MAX_ITEM_CHARS
    MAX_ITEM_CHARS = a.max_item_chars or None
    pool = {r["id"]: r for r in load_jsonl(a.pool)}
    sessions = load_sessions(a.sessions, a.benchmarks, a.valid_only, set(filter(None, a.arms.split(","))))
    chosen, counts = sample(sessions, pool, a.n_per_stratum, a.seed)
    n = write_batch(chosen, a.out, a.seed, a.id_prefix)
    print(f"wrote {n} diffs to {a.out}; available per stratum: {counts}")


if __name__ == "__main__":
    main()
