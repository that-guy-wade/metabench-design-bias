import json, os, re, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE.parent))  # append, not insert: pools/math would shadow the stdlib math module
from schema_check import check_pool, load  # noqa: E402

PREFIX, DOMAIN, MIN_ITEMS = "H", "clinical_medicine", 1000
LETTERS = "ABCD"


def _norm(s):
    return re.sub(r"\s+", " ", s.strip())


def test_pool_schema():
    rep = check_pool(HERE / "pool.jsonl", PREFIX, DOMAIN, MIN_ITEMS)
    assert rep["ok"], (rep["errors"][:20], rep["duplicates"][:20])


def test_four_options_and_letter_key():
    for it in load(HERE / "pool.jsonl"):
        assert len(it["options"]) == 4 and it["answer"] in LETTERS
        assert len({_norm(o).lower() for o in it["options"]}) == 4
        assert _norm(it["options"][LETTERS.index(it["answer"])]) == _norm(it["verification"]["evidence"]["answer_text"])


def test_strata_allocation_matches_summary():
    s = json.loads((HERE / "build_summary.json").read_text())
    items = load(HERE / "pool.jsonl")
    from collections import Counter
    assert Counter(it["category"] for it in items) == s["allocation"]
    assert s["n_items"] == len(items) == 1000


def test_keys_reverify_against_official_release_and_negative_control():
    """Independent re-check against the official 4-option release (bigbio mirror), and a negative
    control: shifting every key letter must break agreement for every item (the check can fail)."""
    os.environ.setdefault("HF_HOME", str(HERE.parent / "_work" / "hf_cache"))
    from datasets import load_dataset
    b = load_dataset("bigbio/med_qa", "med_qa_en_4options_source", split="test")
    by_q = {_norm(r["question"]): r for r in b}
    items = load(HERE / "pool.jsonl")
    agree = wrong_agree = 0
    for it in items:
        rb = by_q[_norm(it["question"])]
        truth = _norm(rb["answer"])
        agree += _norm(it["options"][LETTERS.index(it["answer"])]) == truth
        shifted = LETTERS[(LETTERS.index(it["answer"]) + 1) % 4]
        wrong_agree += _norm(it["options"][LETTERS.index(shifted)]) == truth
    assert agree == len(items)
    assert wrong_agree == 0
