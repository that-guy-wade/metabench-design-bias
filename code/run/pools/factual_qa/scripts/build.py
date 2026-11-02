"""Build pools/factual_qa/pool.jsonl from pools/_work/factual_qa/verified.jsonl.
Deterministic: seeded (20261025) stratified random sample of TARGET verified items (strata = topic, proportional
allocation with largest remainders), then a seeded shuffle for id assignment F0001.. Also writes stats.json in _work.
"""
from __future__ import annotations
import json, random, re, sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))  # append: pools/math must not shadow stdlib math
from schema_check import CUTOFF_REFERENCE, DEVELOPER_CUTOFFS  # noqa: E402

HERE = Path(__file__).resolve().parents[1]
WORK = HERE.parent / "_work" / "factual_qa"
SEED, TARGET = 20261025, 2000
SOURCE, SOURCE_DATE = "openai/simple-evals:simple_qa_test_set", "2024-10-30"
LICENCE = "MIT (simple-evals); cited pages under their own licences (Wikipedia CC BY-SA 4.0)"


def largest_remainders(counts: dict[str, int], total: int) -> dict[str, int]:
    n = sum(counts.values())
    if n <= total:
        return dict(counts)
    quotas = {k: c * total / n for k, c in counts.items()}
    alloc = {k: int(q) for k, q in quotas.items()}
    for k in sorted(quotas, key=lambda k: (-(quotas[k] - alloc[k]), k))[: total - sum(alloc.values())]:
        alloc[k] += 1
    return alloc


def main() -> int:
    recs = [json.loads(l) for l in open(WORK / "verified.jsonl", encoding="utf-8") if l.strip()]
    stats = {"seed": SEED, "target": TARGET, "n_rows": len(recs), "status_counts": Counter(r["status"] for r in recs)}
    verified = [r for r in recs if r["status"] == "verified"]
    # drop duplicate question texts (schema rule), keeping the lowest row index
    seen, dedup = set(), []
    for r in verified:
        key = re.sub(r"\s+", " ", r["question"].strip().lower())
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)
    stats["duplicate_questions_dropped"] = len(verified) - len(dedup)
    by_topic = defaultdict(list)
    for r in dedup:
        by_topic[r["topic"]].append(r)
    alloc = largest_remainders({t: len(v) for t, v in by_topic.items()}, TARGET)
    rng = random.Random(SEED)
    chosen = []
    for t in sorted(by_topic):
        pool = sorted(by_topic[t], key=lambda r: r["row"])
        chosen += pool if alloc[t] >= len(pool) else rng.sample(pool, alloc[t])
    rng.shuffle(chosen)
    d = date.fromisoformat(SOURCE_DATE)
    with open(HERE / "pool.jsonl", "w", encoding="utf-8") as out:
        for i, r in enumerate(chosen, 1):
            ev = r["evidence"]
            item = {"id": f"F{i:04d}", "domain": "factual_qa", "source": SOURCE, "source_id": str(r["row"]),
                    "source_url": ev["url"], "licence": LICENCE, "source_date": SOURCE_DATE,
                    "question": r["question"], "options": [], "answer": r["answer"], "key_type": "string",
                    "category": r["topic"],
                    "strata": {"topic": r["topic"], "answer_type": r["answer_type"], "n_urls": len(r["urls"])},
                    "cited_urls": r["urls"],
                    "verification": {"method": "cited_page_substring_match_v1", "verified": True, "evidence": ev},
                    "post_cutoff": d > CUTOFF_REFERENCE,
                    "post_cutoff_by_developer": {k: d > c for k, c in DEVELOPER_CUTOFFS.items()}}
            out.write(json.dumps(item, ensure_ascii=False) + "\n")
    # statistics for PROVENANCE
    def frac(key):
        tot, ver = Counter(r[key] for r in recs), Counter(r[key] for r in verified)
        return {k: {"total": tot[k], "verified": ver[k], "fraction": round(ver[k] / tot[k], 3)} for k in sorted(tot)}
    stats["per_topic"] = frac("topic")
    stats["per_answer_type"] = frac("answer_type")
    stats["match_form"] = Counter(r["evidence"]["match_form"] for r in verified)
    stats["allocation"] = alloc
    stats["pool_per_topic"] = Counter(r["topic"] for r in chosen)
    stats["pool_per_answer_type"] = Counter(r["answer_type"] for r in chosen)
    stats["pool_n"] = len(chosen)
    excl = [r for r in recs if r["status"] != "verified"]
    stats["excluded_by_reason"] = Counter(r["status"] for r in excl)
    stats["excluded_by_reason_and_topic"] = {s: dict(Counter(r["topic"] for r in excl if r["status"] == s))
                                             for s in stats["excluded_by_reason"]}
    (WORK / "stats.json").write_text(json.dumps(stats, indent=1, sort_keys=True, default=dict) + "\n")
    print(json.dumps({k: stats[k] for k in ("status_counts", "pool_n", "pool_per_topic", "match_form")}, default=dict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
