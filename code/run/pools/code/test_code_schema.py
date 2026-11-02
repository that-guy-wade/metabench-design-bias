# Code pool schema tests (template: pools/_test_schema_template.py; PREFIX "C", DOMAIN "code", MIN_ITEMS 1500).
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE.parent))  # append, not insert: pools/math would shadow the stdlib math module
from schema_check import check_pool, load  # noqa: E402

PREFIX, DOMAIN, MIN_ITEMS = "C", "code", 1500


def items():
    return load(HERE / "pool.jsonl")


def test_pool_schema():
    rep = check_pool(HERE / "pool.jsonl", PREFIX, DOMAIN, MIN_ITEMS)
    assert rep["ok"], (rep["errors"][:20], rep["duplicates"][:20])


def test_every_item_has_at_least_three_tests():
    for it in items():
        assert len(it["tests"]) >= 3, it["id"]
        assert all(set(t) == {"input", "output"} for t in it["tests"]), it["id"]
        assert it["strata"]["n_tests"] == len(it["tests"]) == it["verification"]["evidence"]["n_tests"], it["id"]


def test_reference_passes_all_tests_per_evidence():
    for it in items():
        ev = it["verification"]["evidence"]
        assert ev["reference_pass"] == ev["n_tests"] == len(it["tests"]), it["id"]
        assert it["language"] == "python3" and it["reference_solution"].strip(), it["id"]
        assert re.fullmatch(r"[0-9a-f]{64}", ev["solution_sha256"]), it["id"]


def test_empty_and_wrong_programs_fail_per_evidence():
    for it in items():
        ev = it["verification"]["evidence"]
        assert ev["empty_pass"] < ev["n_tests"], it["id"]
        assert ev["wrong_pass"] < ev["n_tests"], it["id"]


def test_no_duplicate_statements():
    texts = Counter(re.sub(r"\s+", " ", it["question"].strip().lower()) for it in items())
    assert all(c == 1 for c in texts.values()), [k[:60] for k, c in texts.items() if c > 1][:5]
    assert len({it["source_id"] for it in items()}) == len(items())


def test_code_fields_and_cutoff_flags():
    for it in items():
        assert it["key_type"] == "tests" and it["answer"] == "tests" and it["options"] == [], it["id"]
        assert it["time_limit_s"] > 0 and it["memory_limit_mb"] > 0, it["id"]
        assert it["post_cutoff"] is False and not any(it["post_cutoff_by_developer"].values()), it["id"]
        assert it["category"] == it["strata"]["platform"], it["id"]
