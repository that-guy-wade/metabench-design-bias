"""Offline tests for the T3 agentic-template tier (no LLM calls)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from metabench.t3_agentic import (
    TEMPLATES, FROZEN_SEED_SET, SCRIPTED_AGENTS, T3Interface, Budget, FSStrictness, APIStrictness, SchedStrictness,
    make_env, run_instance, agent_oracle, agent_fast_sloppy, agent_over_verifier, T3_TOOLS, ParamError, _check_params,
)

LAX = {
    "fs_clean": FSStrictness(tolerate_whitespace=True, tolerate_column_order=True, require_no_collateral_edits=False, require_within_steps=False, pass_threshold=0.5),
    "api_workflow": APIStrictness(exact_set=False, require_confirmed=False, idempotency_check=False, forbid_forbidden_calls=False, require_within_steps=False, pass_threshold=0.5),
    "scheduling": SchedStrictness(all_hard=False, soft_weighted=False, must_detect_infeasible=False, require_within_steps=False),
}


def _rate(template, fn, strictness, params=None, budget=None, n=60):
    res = [run_instance(template, params or {}, strictness, s, budget or Budget(), fn) for s in FROZEN_SEED_SET[template][:n]]
    return sum(r.passed for r in res) / len(res)


@pytest.mark.parametrize("template", list(TEMPLATES))
def test_oracle_solves_defaults(template):
    strict = TEMPLATES[template].STRICTNESS()
    assert _rate(template, agent_oracle, strict) >= 0.95


@pytest.mark.parametrize("template", list(TEMPLATES))
def test_verifier_strictness_is_a_lever(template):
    strict = TEMPLATES[template].STRICTNESS()
    o_s, s_s = _rate(template, agent_oracle, strict), _rate(template, agent_fast_sloppy, strict)
    o_l, s_l = _rate(template, agent_oracle, LAX[template]), _rate(template, agent_fast_sloppy, LAX[template])
    assert s_s < o_s, "sloppy agent must score below the oracle under the strict verifier"
    assert (o_l - s_l) < (o_s - s_s), "the oracle-sloppy gap must shrink under the lax verifier"


@pytest.mark.parametrize("template", ["fs_clean", "api_workflow"])
def test_over_verifier_is_punished_only_by_specific_knobs(template):
    strict = TEMPLATES[template].STRICTNESS()
    assert _rate(template, agent_over_verifier, strict) < 0.5
    assert _rate(template, agent_over_verifier, LAX[template]) >= 0.95


def test_budget_knob_reorders():
    tight = Budget(max_steps=12, max_tool_calls=80)
    s = FSStrictness(tolerate_whitespace=True, tolerate_column_order=True, require_no_collateral_edits=False, require_within_steps=True, pass_threshold=0.5)
    assert _rate("fs_clean", agent_over_verifier, s, params={"max_steps": 12}, budget=tight) < 0.2
    assert _rate("fs_clean", agent_oracle, s, params={"max_steps": 12}, budget=tight) >= 0.8


@pytest.mark.parametrize("template", list(TEMPLATES))
def test_seed_determinism(template):
    a, b = make_env(template, {}, 123, Budget()), make_env(template, {}, 123, Budget())
    assert a.task_text == b.task_text and a.expected_state() == b.expected_state()
    c = make_env(template, {}, 124, Budget())
    assert c.task_text != a.task_text or c.expected_state() != a.expected_state()


def test_param_validation():
    with pytest.raises(ParamError):
        _check_params(TEMPLATES["fs_clean"].PARAM_SCHEMA, {"n_files": 99})
    with pytest.raises(ParamError):
        _check_params(TEMPLATES["fs_clean"].PARAM_SCHEMA, {"noise_types": ["lasers"]})
    with pytest.raises(ParamError):
        _check_params(TEMPLATES["api_workflow"].PARAM_SCHEMA, {"bogus": 1})
    ui = T3Interface()
    assert ui.handle_tool("set_params", {"template": "scheduling", "params": {"n_people": 50}}).startswith("ERROR")
    assert ui.handle_tool("set_verifier", {"template": "scheduling", "strictness": {"nope": True}}).startswith("ERROR")
    assert ui.handle_tool("set_mix", {"mix": {"fs_clean": 0.7, "api_workflow": 0.7}}).startswith("ERROR")


def test_interface_validity_logging_and_scores():
    ui = T3Interface()
    assert ui.handle_tool("set_mix", {"mix": {"fs_clean": 1.0}}).startswith("ok")
    assert "at least 2 templates" in ui.handle_tool("submit", {})
    assert ui.handle_tool("set_mix", {"mix": {"fs_clean": 0.5, "scheduling": 0.5}}).startswith("ok")
    assert len(ui.instances()) == 60
    view = ui.handle_tool("request_panel_scores", {}, panel={"A": agent_oracle, "B": agent_fast_sloppy})
    assert "A:" in view and "B:" in view
    assert ui.score_requests and ui.score_requests[0]["true_scores"]["A"] > ui.score_requests[0]["true_scores"]["B"]
    n_cached = len(ui._cache)
    ui.handle_tool("request_panel_scores", {}, panel={"A": agent_oracle, "B": agent_fast_sloppy})
    assert len(ui._cache) == n_cached, "identical config must hit the cache"
    assert ui.handle_tool("submit", {"final_notes": "done"}).startswith("submitted")
    assert ui.handle_tool("set_mix", {"mix": {"fs_clean": 1.0}}).startswith("ERROR")  # frozen after submit
    tools = [e["tool"] for e in ui.log]
    assert tools[:3] == ["set_mix", "submit", "set_mix"] and all("config_hash" in e for e in ui.log)
    # none-arm view hook: no panel -> no scores
    assert "not available" in T3Interface().handle_tool("request_panel_scores", {})


def test_oracle_gate_rejects_unreachable_config():
    ui = T3Interface()
    ui.handle_tool("set_mix", {"mix": {"fs_clean": 0.5, "api_workflow": 0.5}})
    ui.handle_tool("set_budget", {"max_steps": 5, "max_tool_calls": 5})   # nobody can finish in 5 calls
    out = ui.handle_tool("submit", {})
    assert out.startswith("ERROR") and "oracle solvability" in out


def test_tool_schemas_are_strict_json_schema():
    for t in T3_TOOLS:
        assert set(t) == {"name", "description", "input_schema"}
        assert t["input_schema"]["additionalProperties"] is False
    for cls in TEMPLATES.values():
        for t in cls({}, 1, Budget()).tools():
            assert t["input_schema"]["additionalProperties"] is False
