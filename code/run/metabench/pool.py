"""T1 item pools.

Pilot domain (NOT used in the main study): MMLU-Pro non-math categories (graduate-level multiple-choice
knowledge and reasoning across 13 categories).  Every item has a human-verified answer key; the designer
never writes a key.  Main-study domains (math with numeric keys, code with executable tests,
retrieval-verified factual QA) are specified in SCENARIO.md and built with the same schema.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

LETTERS = "ABCDEFGHIJ"

PILOT_EXCLUDED_CATEGORIES = {"math"}   # main study uses a math domain; pilot excludes it
PILOT_PER_CATEGORY = 100
PILOT_SEED = 20261025


def build_pilot_pool(out_path: Path, seed: int = PILOT_SEED, per_category: int = PILOT_PER_CATEGORY) -> list[dict]:
    from datasets import load_dataset
    ds = load_dataset("TIGER-Lab/MMLU-Pro", split="test")
    rng = random.Random(seed)
    by_cat: dict[str, list[dict]] = {}
    for r in ds:
        if r["category"] in PILOT_EXCLUDED_CATEGORIES:
            continue
        if len(r["options"]) < 4:
            continue
        by_cat.setdefault(r["category"], []).append(r)
    items = []
    for cat in sorted(by_cat):
        rows = by_cat[cat]
        rng.shuffle(rows)
        for r in rows[:per_category]:
            items.append({
                "id": f"P{len(items)+1:04d}",
                "source": "TIGER-Lab/MMLU-Pro:test",
                "source_id": int(r["question_id"]),
                "category": cat,
                "question": r["question"].strip(),
                "options": [o.strip() for o in r["options"]],
                "answer": r["answer"],            # human-verified key (letter)
                "answer_index": int(r["answer_index"]),
                "src": r["src"],
            })
    rng.shuffle(items)
    for i, it in enumerate(items):   # re-id after shuffle so id order carries no category signal
        it["id"] = f"P{i+1:04d}"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        for it in items:
            f.write(json.dumps(it) + "\n")
    return items


def load_pool(path: Path) -> dict[str, dict]:
    items = {}
    with open(path) as f:
        for line in f:
            it = json.loads(line)
            items[it["id"]] = it
    return items


def format_item_for_evaluee(item: dict) -> str:
    opts = "\n".join(f"{LETTERS[i]}. {o}" for i, o in enumerate(item["options"]))
    return f"{item['question']}\n\n{opts}"

EVALUEE_INSTRUCTIONS = ("Answer the following multiple-choice question. You may reason briefly first. "
                        "End your response with a final line of the form 'Answer: X' where X is the letter of the correct option.")


def parse_answer(text: str, n_options: int) -> str | None:
    import re
    valid = LETTERS[:n_options]
    m = re.findall(r"Answer:\s*\**\(?([A-J])\)?\**", text)
    if m:
        a = m[-1].upper()
        return a if a in valid else None
    # fallback: last standalone capital letter in valid range on the final line
    last = text.strip().splitlines()[-1] if text.strip() else ""
    m2 = re.findall(r"\b([A-J])\b", last)
    if m2 and m2[-1] in valid:
        return m2[-1]
    return None
