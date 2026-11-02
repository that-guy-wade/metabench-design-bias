"""Held-out domain pool: clinical medicine (MedQA USMLE 4-option test split).

Deterministic. Key verification = three-way cross-source agreement between
(a) GBaker/MedQA-USMLE-4-options test, (b) bigbio/med_qa med_qa_en_4options_source test (mirror of the
official jind11/MedQA 4-option release) and (c) bigbio/med_qa med_qa_en_source test (official 5-option
release): same question text, same answer text in all three, 4-option set is a subset of the 5-option set.
Sampling: seeded stratified random (seed 20261025) by USMLE step, proportional allocation, n = 1000.
"""
from __future__ import annotations
import hashlib, json, random, re, sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))  # append: pools/math must not shadow stdlib math
from schema_check import DEVELOPER_CUTOFFS, CUTOFF_REFERENCE  # noqa: E402

SEED = 20261025
N_TARGET = 1000
OUT = ROOT / "heldout_clinical_medicine" / "pool.jsonl"
SOURCE_DATE = date(2020, 9, 28)   # arXiv:2009.13081 v1 posted 2020-09-28; repo released with the paper
LETTERS = "ABCD"


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def main() -> None:
    from datasets import load_dataset
    a = load_dataset("GBaker/MedQA-USMLE-4-options", split="test")
    b = load_dataset("bigbio/med_qa", "med_qa_en_4options_source", split="test")
    c = load_dataset("bigbio/med_qa", "med_qa_en_source", split="test")
    b_by_q = {norm(r["question"]): r for r in b}
    c_by_q = defaultdict(list)
    for r in c:
        c_by_q[norm(r["question"])].append(r)
    assert len(b_by_q) == len(b), "duplicate questions inside bigbio 4-option test"
    excl = Counter()
    verified = []
    for idx, r in enumerate(a):
        q = norm(r["question"])
        opts = r["options"] if isinstance(r["options"], dict) else json.loads(r["options"].replace("'", '"')) if False else None
        if opts is None:
            # GBaker stores options as a dict column in parquet; datasets returns a dict
            opts = r["options"]
        if not isinstance(opts, dict) or sorted(opts) != list(LETTERS):
            excl["bad_option_set"] += 1; continue
        key = r["answer_idx"]
        if key not in LETTERS or norm(opts[key]) != norm(r["answer"]):
            excl["key_letter_text_mismatch_in_a"] += 1; continue
        rb = b_by_q.get(q)
        if rb is None:
            excl["not_in_bigbio_4opt"] += 1; continue
        b_opts = {o["key"]: o["value"] for o in rb["options"]}
        if norm(rb["answer"]) != norm(r["answer"]) or {norm(v) for v in b_opts.values()} != {norm(v) for v in opts.values()}:
            excl["disagree_a_vs_b"] += 1; continue
        rcs = c_by_q.get(q, [])
        rc = next((x for x in rcs if norm(x["answer"]) == norm(r["answer"])), None)
        if rc is None:
            excl["not_in_bigbio_5opt_or_answer_differs"] += 1; continue
        c_vals = {norm(o["value"]) for o in rc["options"]}
        if not {norm(v) for v in opts.values()} <= c_vals:
            excl["4opt_not_subset_of_5opt"] += 1; continue
        if len({norm(v) for v in opts.values()}) != 4:
            excl["duplicate_options"] += 1; continue
        verified.append({
            "source_index": idx, "meta_info": r["meta_info"], "question": r["question"].strip(),
            "options": [opts[L].strip() for L in LETTERS], "answer": key, "answer_text": r["answer"].strip(),
            "n_options_original": len(rc["options"]),
        })
    # duplicate question texts across verified items: keep first
    seen = set(); uniq = []
    for v in verified:
        k = norm(v["question"]).lower()
        if k in seen:
            excl["duplicate_question"] += 1; continue
        seen.add(k); uniq.append(v)
    verified = uniq
    strata = defaultdict(list)
    for v in verified:
        strata[v["meta_info"]].append(v)
    rng = random.Random(SEED)
    total = len(verified)
    n_take = min(N_TARGET, total)
    # proportional allocation with largest remainders
    quotas = {s: n_take * len(v) / total for s, v in strata.items()}
    alloc = {s: int(q) for s, q in quotas.items()}
    for s in sorted(quotas, key=lambda s: quotas[s] - alloc[s], reverse=True)[: n_take - sum(alloc.values())]:
        alloc[s] += 1
    chosen = []
    for s in sorted(strata):
        rows = sorted(strata[s], key=lambda v: v["source_index"])
        rng.shuffle(rows)
        chosen += rows[: alloc[s]]
    rng.shuffle(chosen)
    items = []
    for i, v in enumerate(chosen):
        items.append({
            "id": f"H{i+1:04d}", "domain": "clinical_medicine",
            "source": "GBaker/MedQA-USMLE-4-options:test", "source_id": str(v["source_index"]),
            "source_url": "https://huggingface.co/datasets/GBaker/MedQA-USMLE-4-options",
            "licence": "CC-BY-4.0 (GBaker HF card); original MedQA repo github.com/jind11/MedQA MIT",
            "source_date": SOURCE_DATE.isoformat(),
            "question": v["question"], "options": v["options"], "answer": v["answer"], "key_type": "letter",
            "category": v["meta_info"],
            "strata": {"usmle_step": v["meta_info"], "n_options_original": v["n_options_original"]},
            "verification": {
                "method": "three-way cross-source agreement: GBaker 4-option == bigbio med_qa_en_4options_source (official 4-option release) on answer text and option set; answer text present in bigbio med_qa_en_source (official 5-option release) and 4-option set is a subset of its options",
                "verified": True,
                "evidence": {"answer_text": v["answer_text"], "sources_agreeing": 3,
                             "bigbio_4opt_config": "med_qa_en_4options_source", "bigbio_5opt_config": "med_qa_en_source"},
            },
            "post_cutoff": SOURCE_DATE > CUTOFF_REFERENCE,
            "post_cutoff_by_developer": {d: SOURCE_DATE > cut for d, cut in DEVELOPER_CUTOFFS.items()},
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    summary = {"source_rows": len(a), "verified": total, "exclusions": dict(excl), "strata_verified": {s: len(v) for s, v in strata.items()},
               "allocation": alloc, "n_items": len(items), "seed": SEED,
               "pool_sha256": hashlib.sha256(OUT.read_bytes()).hexdigest()}
    (OUT.parent / "build_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
