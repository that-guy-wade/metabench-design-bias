"""Print the markdown statistics tables used in PROVENANCE.md from fetch_log.jsonl and stats.json (no judgement)."""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

WORK = Path(__file__).resolve().parents[2] / "_work" / "factual_qa"


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def main():
    last = {}
    for l in open(WORK / "fetch_log.jsonl", encoding="utf-8"):
        if l.strip():
            r = json.loads(l)
            last[r["url"]] = r
    recs = list(last.values())
    print(f"Unique cited URLs with a terminal fetch record: {len(recs)}\n")
    st = Counter()
    for r in recs:
        if r["status"] == 200 and r["page_sha256"]:
            st["200 (text stored)"] += 1
        elif r["status"] == 200:
            st["200 but non-text (pdf)"] += 1
        elif r["status"] is not None:
            st[str(r["status"])] += 1
        else:
            st["no response: " + (r["error"] or "").split(":")[0].replace("skipped", "skipped (host circuit open)")] += 1
    print("### Fetch outcome by status\n")
    print(table(["outcome", "URLs"], sorted(st.items(), key=lambda kv: -kv[1])))
    hosts = Counter(r["host"] for r in recs)
    ok = Counter(r["host"] for r in recs if r["page_sha256"])
    print("\n### Top 25 hosts (unique URLs, text stored)\n")
    print(table(["host", "URLs", "text stored"], [(h or "(no scheme/host)", n, ok[h]) for h, n in hosts.most_common(25)]))
    s = json.load(open(WORK / "stats.json"))
    print(f"\nHosts total: {len(hosts)}; items (CSV rows): {s['n_rows']}; status counts: {s['status_counts']}\n")
    print("### Verified fraction per topic\n")
    print(table(["topic", "items", "verified", "fraction", "in pool"],
                [(k, v["total"], v["verified"], v["fraction"], s["pool_per_topic"].get(k, 0)) for k, v in s["per_topic"].items()]))
    print("\n### Verified fraction per answer_type\n")
    print(table(["answer_type", "items", "verified", "fraction", "in pool"],
                [(k, v["total"], v["verified"], v["fraction"], s["pool_per_answer_type"].get(k, 0)) for k, v in s["per_answer_type"].items()]))
    print("\n### Match form among verified items\n")
    print(table(["form", "items"], sorted(s["match_form"].items())))
    print("\n### Exclusions by reason and topic\n")
    reasons = sorted(s["excluded_by_reason"])
    topics = sorted(s["per_topic"])
    print(table(["topic"] + reasons, [[t] + [s["excluded_by_reason_and_topic"][r].get(t, 0) for r in reasons] for t in topics]
                + [["total"] + [s["excluded_by_reason"][r] for r in reasons]]))
    print(f"\nDuplicate question texts dropped before sampling: {s['duplicate_questions_dropped']}; seed {s['seed']}; "
          f"target {s['target']}; pool size {s['pool_n']}.")


if __name__ == "__main__":
    main()
