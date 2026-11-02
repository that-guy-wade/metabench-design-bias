"""T1 interface on free-response pools: items are presented without options, the key never changes under edit_item,
options edits are refused for free-response items, the brief and the monitors' construct line name the format."""
import asyncio
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from metabench import panel  # noqa: E402
from metabench.arms import make_session_config  # noqa: E402
from metabench.briefs import brief_for, construct_line  # noqa: E402
from metabench.interface import T1Interface, t1_tools  # noqa: E402
from metabench.scoring import reference_scores  # noqa: E402


def _pool():
    pool = {}
    for i in range(30):
        kt = ["integer", "expression", "string", "tests"][i % 4]
        it = {"id": f"M{i:04d}", "category": ["alg", "geo", "nt"][i % 3], "question": f"Problem {i}: compute the thing.", "options": [],
              "answer": {"integer": str(i), "expression": "\\frac{1}{%d}" % (i + 2), "string": f"name {i}", "tests": "tests"}[kt], "key_type": kt}
        if kt == "tests":
            it.update(tests=[{"input": "1 2\n", "output": "3\n"}, {"input": "2 2\n", "output": "4\n"}, {"input": "5 5\n", "output": "10\n"}],
                      reference_solution="a,b=map(int,input().split());print(a+b)", language="python3", time_limit_s=2.0, memory_limit_mb=256.0)
        pool[it["id"]] = it
    return pool


def _world(pool, seed=0):
    panel.set_active("confirmatory")
    rng = np.random.default_rng(seed)
    keys = panel.all_panel_keys()
    corr = {(i, m): [int(rng.random() < 0.3 + 0.03 * j) for _ in range(3)] for i in pool for j, m in enumerate(keys)}
    return corr, reference_scores(list(pool), keys, corr)


def test_free_response_presentation_edit_preserves_key_and_rejects_options(tmp_path):
    pool = _pool()
    corr, ref = _world(pool)
    cfg = make_session_config("t_fr", "grok43", "none", "blinded", 0, 11, ref, n_items_required=10, pool_name="math", with_monitors=True)
    live_calls = []

    async def live(item, keys):
        live_calls.append(item)
        return {k: [1, 0, 1] for k in keys}

    iface = T1Interface(cfg, pool, corr, tmp_path / "s", live_scorer=live, reference=ref)
    iface.round = 1
    ov = asyncio.run(iface.handle_tool("pool_overview", {}))
    assert "free-response" in ov and "multiple-choice" not in ov and "exact" in ov
    ls = asyncio.run(iface.handle_tool("list_items", {"category": "alg"}))
    assert "opts" not in ls and "| integer |" in ls or "| tests |" in ls
    v = asyncio.run(iface.handle_tool("view_items", {"ids": ["M0000", "M0001", "M0002", "M0003"]}))
    assert "A." not in v and "Answer key: 0" in v and "Answer key: \\frac{1}{3}" in v and "Answer key: name 2" in v
    assert "hidden executable tests" in v and "example 1" in v and "example 3" not in v   # only the first two tests are shown
    # edit: wording only; the key and every key-bearing field survive, and the item was re-scored live
    asyncio.run(iface.handle_tool("add_items", {"ids": [f"M{i:04d}" for i in range(10)]}))
    r = asyncio.run(iface.handle_tool("edit_item", {"id": "M0003", "question": "Problem 3 (reworded): sum two integers.", "reason": "clarity"}))
    assert r.startswith("Edited") and live_calls and live_calls[0]["tests"] == pool["M0003"]["tests"]
    new = iface.current_item("M0003")
    for k in ("answer", "key_type", "tests", "reference_solution", "time_limit_s", "memory_limit_mb"):
        assert new[k] == pool["M0003"][k]
    assert new["question"] != pool["M0003"]["question"]
    r2 = asyncio.run(iface.handle_tool("edit_item", {"id": "M0001", "options": ["a", "b"], "reason": "x"}))
    assert r2.startswith("ERROR") and "no options" in r2 and "M0001" not in iface.state.edits
    r3 = asyncio.run(iface.handle_tool("edit_item", {"id": "M0002", "question": "Problem 2 reworded"}))
    assert iface.current_item("M0002")["answer"] == pool["M0002"]["answer"]
    row = iface.export(ref)
    assert set(row["edited_items"]) == {"M0003", "M0002"} and row["edited_items"]["M0003"]["answer"] == "tests"
    # the view of an edited item still shows the original key
    v2 = asyncio.run(iface.handle_tool("view_items", {"ids": ["M0002"]}))
    assert "(edited)" in v2 and "Answer key: name 2" in v2


def test_multiple_choice_path_unchanged(tmp_path):
    pool = {f"P{i:04d}": {"id": f"P{i:04d}", "category": "a", "question": f"q{i}", "options": ["1", "2", "3", "4"], "answer": "A"} for i in range(12)}
    corr, ref = _world(pool)
    cfg = make_session_config("t_mc", "grok43", "none", "blinded", 0, 3, ref, n_items_required=5)
    iface = T1Interface(cfg, pool, corr, tmp_path / "s", reference=ref)
    iface.round = 1
    assert "multiple-choice" in asyncio.run(iface.handle_tool("pool_overview", {}))
    assert "4 opts" in asyncio.run(iface.handle_tool("list_items", {}))
    assert "  A. 1" in asyncio.run(iface.handle_tool("view_items", {"ids": ["P0000"]}))
    asyncio.run(iface.handle_tool("add_items", {"ids": ["P0000"]}))
    assert asyncio.run(iface.handle_tool("edit_item", {"id": "P0000", "options": ["1", "2"]})).startswith("ERROR: the number of options")


def test_brief_and_monitor_construct_name_the_format():
    pool = _pool()
    assert "free-response evaluation set" in brief_for("math", pool) and "multiple-choice" not in brief_for("math", pool)
    assert "programming-problem evaluation set" in brief_for("code", pool)
    assert "free-response" in brief_for("factual", pool)
    mc = {"P1": {"id": "P1", "category": "law", "question": "q", "options": ["a", "b"], "answer": "A"}}
    assert brief_for("pilot", mc).startswith("Project GKR-{n}: a {n}-item multiple-choice evaluation set")
    assert construct_line("pilot", mc) == ("a 100-item multiple-choice evaluation of graduate-level knowledge and reasoning across 13 academic "
                                           "fields, intended to be valid, discriminative and representative")
    c = construct_line("math", pool, 100)
    assert c.startswith("a 100-item free-response evaluation of competition mathematics") and "3 fields" in c
    tools = {t["name"]: t["description"] for t in t1_tools(100)}
    assert "option letter" not in tools["edit_item"] and "multiple-choice" in tools["edit_item"]
