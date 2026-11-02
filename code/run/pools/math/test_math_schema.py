import json, re, sys
from collections import Counter
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE.parent))  # append, not insert: pools/math would shadow the stdlib math module
from schema_check import check_pool, load  # noqa: E402

PREFIX, DOMAIN, MIN_ITEMS = "M", "math", 2000
sys.path.insert(0, str(HERE / "scripts"))
import add_math_level5  # noqa: E402


def items():
    return load(HERE / "pool.jsonl")


def test_pool_schema():
    rep = check_pool(HERE / "pool.jsonl", PREFIX, DOMAIN, MIN_ITEMS)
    assert rep["ok"], (rep["errors"][:20], rep["duplicates"][:20])


def test_aime_keys_are_integers_0_999():
    for it in items():
        if it["category"] == "AIME":
            assert it["key_type"] == "integer", it["id"]
            assert re.fullmatch(r"\d{1,3}", it["answer"]) and 0 <= int(it["answer"]) <= 999, (it["id"], it["answer"])


def test_no_duplicate_questions():
    c = Counter(re.sub(r"\s+", " ", it["question"].strip().lower()) for it in items())
    assert all(n == 1 for n in c.values()), [k[:60] for k, n in c.items() if n > 1][:5]


def test_every_item_verified_with_evidence():
    allowed = {"two-source agreement", "official-pdf agreement", "two-mirror transcription check of a human-written boxed answer "
               "(qwedsacf/competition_math vs EleutherAI/hendrycks_math; not two independent keyings)",
               "single-source (MathArena transcription of official key)",
               "single-source (AoPS-wiki transcription of official key, gneubig/aime-1983-2024)"}
    for it in items():
        v = it["verification"]
        assert v["verified"] is True and v["method"] in allowed, (it["id"], v["method"])
        key = v["evidence"].get("primary_answer", v["evidence"].get("boxed_answer_original"))
        assert re.sub(r"\s+", " ", str(key).strip()) == it["answer"], it["id"]
        if v["method"] == "two-source agreement":
            assert v["evidence"]["cross_sources"] and all(x["agree"] for x in v["evidence"]["cross_sources"].values()), it["id"]
        if v["method"] == "official-pdf agreement":
            assert v["evidence"]["official_pdf"].startswith(("https://hmmt-archive.s3.amazonaws.com/", "https://www.brumo.org/s/",
                                                             "https://cmimc.math.cmu.edu/archive/cmimc2025/")), it["id"]
            assert v["evidence"]["pdf_answer_raw"], it["id"]


def test_no_figure_or_proof_text():
    fig = re.compile(r"\[asy\]|\bfigures?\b|\bdiagrams?\b|as shown|shown (below|above|here|in the)", re.I)
    proof = re.compile(r"\b(prove|show that|proof)\b", re.I)
    for it in items():
        assert not fig.search(it["question"]), it["id"]
        assert not proof.search(it["question"]), it["id"]


def test_ids_are_unique_and_shuffled():
    ids = [it["id"] for it in items()]
    assert len(set(ids)) == len(ids)
    base = [i for i in ids if int(i[1:]) <= 1209]
    new = [i for i in ids if int(i[1:]) > 1209]
    assert new == [f"M{i:04d}" for i in range(1210, 1210 + len(new))]
    assert len(base) + len(new) == len(ids)
    # id order must not track source order: adjacent items come from many sources
    srcs = [it["source"] for it in items()]
    assert len(set(srcs[:50])) >= 3


def test_dates_and_cutoff_flags_match_provenance_rules():
    for it in items():
        y = it["strata"]["year"]
        if y is None:
            assert it["category"] == "MATH" and it["source_date"] == "2021-03-05", it["id"]
        else:
            assert it["source_date"].startswith(str(y)), (it["id"], it["source_date"], y)
        assert it["strata"]["contest"].startswith(it["category"]), it["id"]


def test_math_level5_items_and_frozen_base():
    import hashlib
    man = json.loads((HERE / "base_manifest.json").read_text())["items"]
    base = [it for it in items() if int(it["id"][1:]) <= 1209]
    for it in base:  # every retained base item keeps the id and content it was given on 2026-10-25
        m = man[f"{it['source']}||{it['source_id']}"]
        assert it["id"] == m["id"], it["id"]
        assert hashlib.sha256(json.dumps([it["source"], it["source_id"], it["question"], it["answer"]]).encode()).hexdigest() == m["content_sha256"], it["id"]
    rep = json.loads((HERE / "build_report.json").read_text())
    assert len(base) == 1209 - len(rep["frozen_base"]["removed_ids"])
    math_items = [it for it in items() if it["category"] == "MATH"]
    assert len(math_items) == 2000 - len(base) and all(int(it["id"][1:]) > 1209 for it in math_items)
    for it in math_items:
        ev = it["verification"]["evidence"]
        assert ev["boxed_answer_original"] == ev["boxed_answer_mirror"], it["id"]
        assert re.sub(r"\s+", " ", ev["boxed_answer_original"].strip()) == it["answer"], it["id"]
        assert ev["level"] == 5 and it["strata"]["level"] == 5 and it["source_date"] == "2021-03-05"
        assert it["post_cutoff"] is False and not any(it["post_cutoff_by_developer"].values())


def test_boxed_check_can_fail():
    sol = "We get $x=\\frac{1}{2}$, so the answer is $\\boxed{\\frac{1}{2}}$."
    ok, rule, ev = add_math_level5.verify_pair(sol, sol)
    assert ok and ev["boxed_answer_original"] == "\\frac{1}{2}"
    ok, rule, _ = add_math_level5.verify_pair(sol, sol.replace("\\boxed{\\frac{1}{2}}", "\\boxed{\\frac{1}{3}}"))
    assert not ok and rule == "boxed_answer_mismatch"
    ok, rule, _ = add_math_level5.verify_pair(sol + " Also $\\boxed{7}$.", sol + " Also $\\boxed{7}$.")
    assert not ok and rule == "boxed_count_not_one"
    ok, rule, _ = add_math_level5.verify_pair(sol, sol.replace("so the", "therefore the"))
    assert not ok and rule == "solution_text_mismatch"
    assert add_math_level5.extract_boxed("$\\boxed{a_{1}+\\{b\\}}$ x") == ["a_{1}+\\{b\\}"]
