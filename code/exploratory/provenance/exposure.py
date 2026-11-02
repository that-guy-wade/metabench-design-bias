"""Reconstruct, for every valid T1 session, which pool items the designer was shown (EXPLORATORY).

Rule (documented in FINDINGS.txt):
  * exposure tools are `list_items` (id, category, format, first 150 chars of the question) and `view_items` (full
    question + human key, at most the first 8 ids, ids not in the pool skipped). No other tool returns item ids
    (pool_overview: category counts; draft_status: category mix; request_panel_scores: per-label accuracy; add/remove/
    edit/set_*: confirmations only).
  * actions.jsonl keeps only the first 400 chars of each result and transcript.jsonl the first 2000, so the full
    list_items page is recomputed from the call's args with the interface's exact logic (metabench/interface.py
    t_list_items: sorted pool ids, category filter case-insensitive, case-insensitive substring query on the CURRENT
    question text, i.e. after any earlier successful edit_item, offset/limit clamped to [0, ..] and [1, 30], default 25).
    Calls whose logged result starts with "ERROR" exposed nothing.
  * Every reconstructed page is checked against the logged (truncated) transcript text: the ids parsed from the log must
    be a prefix of the reconstructed ids and the logged "N matching items" must equal the reconstructed total.
  * listed = ids returned by list_items; viewed_full = ids returned by view_items; exposed = listed U viewed_full.
Output: exposure.jsonl (one row per valid session) and exposure_check.json.
"""
from __future__ import annotations

import json
import re
import sys

from common import OUT, POOLS, UNB, bench_rows, cell, load_pool, read_jsonl

ID_LINE = re.compile(r"^[ *]([A-Z]\d{4}) \|", re.M)
VIEW_ID = re.compile(r"^\[([A-Z]\d{4})\] category=", re.M)
HEAD = re.compile(r"^(\d+) matching items")


def list_page(pool, ordered, edits, category=None, query=None, offset=0, limit=25):
    limit = max(1, min(int(limit or 25), 30))
    offset = max(0, int(offset or 0))
    q = (query or "").lower().strip()
    rows = []
    for iid in ordered:
        it = edits.get(iid, pool[iid])
        if category and it["category"].lower() != category.lower().strip():
            continue
        if q and q not in it["question"].lower() and not any(q in o.lower() for o in it["options"]):
            continue
        rows.append(iid)
    return len(rows), rows[offset: offset + limit]


def main():
    out_rows, checks = [], {}
    for pool in POOLS:
        P = load_pool(pool)
        ordered = sorted(P)
        chk = {"list_calls": 0, "list_errors": 0, "list_prefix_ok": 0, "list_total_ok": 0, "view_calls": 0,
               "view_errors": 0, "view_ok": 0, "pair_name_mismatch": 0, "sessions": 0}
        for r in bench_rows(pool):
            sid = r["session_id"]
            sd = UNB / f"WORK_{pool}" / "sessions" / sid
            acts = read_jsonl(sd / "actions.jsonl")
            tres = [t for t in read_jsonl(sd / "transcript.jsonl") if t["kind"] == "tool_result"]
            if len(tres) != len(acts):
                print("WARN length mismatch", sid, len(acts), len(tres), file=sys.stderr)
            edits = {}
            listed, viewed = {}, {}      # id -> first round exposed
            n_list = n_view = 0
            for k, a in enumerate(acts):
                tool, args, rs = a["tool"], a["args"] or {}, a["result_summary"]
                full = tres[k]["payload"]["result"] if k < len(tres) else None
                if k < len(tres) and tres[k]["payload"]["name"] != tool:
                    chk["pair_name_mismatch"] += 1
                    full = None
                if tool == "edit_item" and rs.startswith("Edited") and args.get("question"):
                    base = dict(edits.get(args["id"], P[args["id"]]))
                    base["question"] = args["question"].strip()
                    edits[args["id"]] = base
                elif tool == "list_items":
                    chk["list_calls"] += 1
                    if rs.startswith("ERROR"):
                        chk["list_errors"] += 1
                        continue
                    kw = {x: args.get(x) for x in ("category", "query", "offset", "limit") if x in args}
                    total, ids = list_page(P, ordered, edits, **kw)
                    n_list += 1
                    if full is not None:
                        logged = ID_LINE.findall(full)
                        chk["list_prefix_ok"] += int(ids[:len(logged)] == logged)
                        m = HEAD.match(full)
                        chk["list_total_ok"] += int(bool(m) and int(m.group(1)) == total)
                    for i in ids:
                        listed.setdefault(i, a["round"])
                elif tool == "view_items":
                    chk["view_calls"] += 1
                    if rs.startswith("ERROR"):
                        chk["view_errors"] += 1
                        continue
                    ids = [i for i in list(args.get("ids") or [])[:8] if isinstance(i, str) and i in P]
                    n_view += 1
                    if full is not None:
                        logged = VIEW_ID.findall(full)
                        chk["view_ok"] += int(ids[:len(logged)] == logged)
                    for i in ids:
                        viewed.setdefault(i, a["round"])
            exposed = set(listed) | set(viewed)
            kept = list(r["items"])
            out_rows.append({
                "pool": pool, "session_id": sid, "designer": r["designer"], "cell": cell(r),
                "n_list_calls": n_list, "n_view_calls": n_view,
                "listed": sorted(listed), "viewed_full": sorted(viewed), "n_exposed": len(exposed),
                "kept": kept, "kept_not_exposed": [i for i in kept if i not in exposed],
                "kept_not_viewed_full": [i for i in kept if i not in viewed],
            })
            chk["sessions"] += 1
        checks[pool] = chk
        print(pool, chk)
    with open(OUT / "exposure.jsonl", "w") as f:
        for row in out_rows:
            f.write(json.dumps(row) + "\n")
    (OUT / "exposure_check.json").write_text(json.dumps(checks, indent=1))


if __name__ == "__main__":
    main()
