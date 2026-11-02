import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE.parent))  # append, not insert: pools/math would shadow the stdlib math module
sys.path.insert(0, str(HERE / "scripts"))
from schema_check import check_pool, load  # noqa: E402
from verify import match_in, normalise, snippet_matches  # noqa: E402

PREFIX, DOMAIN, MIN_ITEMS = "F", "factual_qa", 1500


def test_pool_schema():
    rep = check_pool(HERE / "pool.jsonl", PREFIX, DOMAIN, MIN_ITEMS)
    assert rep["ok"], (rep["errors"][:20], rep["duplicates"][:20])


def test_evidence_snippet_contains_answer_under_match_rule():
    for it in load(HERE / "pool.jsonl"):
        ev = it["verification"]["evidence"]
        assert ev["match_form"] in ("exact", "digits", "date"), it["id"]
        assert snippet_matches(ev["snippet"], ev["match_form"], ev["matched"]), it["id"]
        # the snippet must contain the key under the same rule (any form; a digits snippet may also satisfy exact)
        hit = match_in(ev["snippet"], it["answer"], it["strata"]["answer_type"], numeric_text=ev["snippet"])
        assert hit is not None, (it["id"], it["answer"], ev)
        assert ev["match_form"] != "exact" or normalise(it["answer"]) in ev["snippet"], it["id"]
        for k in ("url", "fetched_at", "page_sha256"):
            assert ev.get(k), (it["id"], k)


def test_no_duplicate_questions():
    qs = [normalise(it["question"]) for it in load(HERE / "pool.jsonl")]
    assert len(qs) == len(set(qs))


def test_source_url_is_a_cited_url():
    for it in load(HERE / "pool.jsonl"):
        assert it["source_url"] in it["cited_urls"], it["id"]
        assert it["source_url"] == it["verification"]["evidence"]["url"], it["id"]
        assert it["strata"]["n_urls"] == len(it["cited_urls"]), it["id"]
