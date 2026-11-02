"""Tests for metabench.synthetic: schema key set against docs/ARTEFACT_SCHEMA.md, tree layout, null calibration of
tau(produced, displayed), recovery of injected tracking / rank-gain / identity effects, invalid-session replacement,
determinism and item-outcome row counts.  tau-b is computed directly with scipy (never via metabench.analysis)."""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import kendalltau

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from metabench import synthetic as S  # noqa: E402

SCHEMA = ROOT / "docs" / "ARTEFACT_SCHEMA.md"


def read_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f]


def tau_to_displayed(row):
    order = row["displayed_order"]
    return kendalltau([row["produced_scores"][k] for k in order], [-i for i in range(len(order))], variant="b").statistic


def ranks(row):
    """1 = best, over the displayed order keys (or the displayed panel when no order was shown)."""
    keys = row["displayed_order"] or row["displayed_keys"]
    return {k: i + 1 for i, k in enumerate(sorted(keys, key=lambda k: -row["produced_scores"][k]))}


def designer_mean(values_by_designer):
    return float(np.mean([np.mean(v) for v in values_by_designer.values()]))


def schema_benchmark_fields():
    text = SCHEMA.read_text()
    section = text[text.index("## 2."):text.index("## 3.")]
    fields = []
    for line in section.splitlines():
        if line.startswith("| `"):
            fields += re.findall(r"`([a-z_]+)`", line.split("|")[1])
    return set(fields)


@pytest.fixture(scope="module")
def default_tree(tmp_path_factory):
    """Full registered size (12 designers x frozen cells = 468 sessions), no injected effects, small pool."""
    out = tmp_path_factory.mktemp("default")
    summary = S.generate(out, seed=101, n_pool=150)
    return out, summary


# (1) schema and sizes -------------------------------------------------------------------------------------

def test_benchmark_key_set_and_row_counts(default_tree):
    out, summary = default_tree
    rows = read_jsonl(out / "results" / "benchmarks.jsonl")
    expected = schema_benchmark_fields()
    assert len(expected) == 42
    assert summary["n_registered"] == 468 and summary["n_replacements"] == 0
    assert len(rows) == 468
    for r in rows:
        assert set(r) == expected, set(r) ^ expected
        assert len(r["produced_scores"]) == 17 and len(r["reference_scores"]) == 17 and len(r["panel_keys"]) == 17
        assert set(r["panel_keys"]) == set(r["produced_scores"]) == set(r["reference_scores"])
        assert r["designer"] in r["displayed_keys"] and r["tier"] == "T1" and r["pool_name"] == "math"
        assert isinstance(r["seed"], int) and isinstance(r["replicate"], int) and isinstance(r["valid"], bool)
        assert len(r["monitor_developers"]) == 2 and len(r["config_hash"]) == 64
        if r["info_arm"] in ("sham", "inverted", "true_named", "true_blinded", "instructed"):
            assert r["displayed_order"] and r["n_score_requests"] >= 1
        if r["info_arm"] in ("none", "narrative"):
            assert r["displayed_order"] is None and r["intended_displayed_order"] is None
        if r["info_arm"] == "instructed":
            assert r["target_model"] == r["displayed_leader"]
        assert (r["weights"] != {}) == (r["scoring_rule"] == "weighted_accuracy")
    cells = {}
    for r in rows:
        cells[(r["info_arm"], r["identity_arm"])] = cells.get((r["info_arm"], r["identity_arm"]), 0) + 1
    assert cells[("sham", "blinded")] == 60 and cells[("inverted", "blinded")] == 36 and len(cells) == 9
    assert len({r["designer"] for r in rows}) == 12
    assert len({r["session_id"] for r in rows}) == 468


def test_tree_layout_and_side_files(default_tree):
    out, _ = default_tree
    for rel in ("run_manifest.json", "precompute/math.jsonl", "reference_item_outcomes.jsonl", "registration_full.json",
                "results/benchmarks.jsonl", "results/item_outcomes.jsonl", "results/monitors.jsonl", "results/session_log.jsonl"):
        assert (out / rel).exists(), rel
    rows = read_jsonl(out / "results" / "benchmarks.jsonl")
    reg = json.load(open(out / "registration_full.json"))
    assert set(reg["configs"]) == {r["session_id"] for r in rows}      # the runner's shape: configs under "configs"
    assert (out / "results" / "reference_item_outcomes.jsonl").exists() and (out / "llm_calls.jsonl").exists()
    ref = read_jsonl(out / "reference_item_outcomes.jsonl")
    assert len(ref) == 150 * 17 and all(r["session_id"] == "REFERENCE" and r["n_samples"] == 5 for r in ref)
    log = read_jsonl(out / "results" / "session_log.jsonl")
    assert len(log) == 468 and all(l["attempt"] == 1 and l["exit_code"] == 0 and l["replacement_of"] is None for l in log)
    mons = read_jsonl(out / "results" / "monitors.jsonl")
    assert len(mons) == 468
    for m in mons:
        assert len(m["monitors"]) == 2 and m["monitor_developers"] == sorted(x["developer"] for x in m["monitors"])
        for x in m["monitors"]:
            assert isinstance(x["artifact"]["evidence_score"], int) and isinstance(x["trace"]["evidence_score"], int)
            assert isinstance(x["trace"]["steering_actions"], list)
    for r in rows[:40]:
        d = out / "sessions" / r["session_id"]
        cfg = json.load(open(d / "config.json"))
        assert cfg["config_hash"] == r["config_hash"] and cfg["label_map"] == r["label_map"] and reg["configs"][r["session_id"]] == cfg
        assert (out / "monitors" / f"{r['session_id']}.json").exists()
        actions = read_jsonl(d / "actions.jsonl")
        assert [a["tool"] for a in actions][:1] == ["pool_overview"] and actions[-1]["tool"] == "submit"
        assert sum(a["tool"] == "end_round" for a in actions) == 4
        assert set(actions[0]) == {"session_id", "round", "t", "tool", "args", "result_summary"}
        kinds = {t["kind"] for t in read_jsonl(d / "transcript.jsonl")}
        assert {"system", "user", "assistant", "tool_result", "probe"} <= kinds
        probes = json.load(open(d / "probes.json"))
        assert ("self_recognition" in probes) == (not r["named"])
        assert set(probes) <= {"recall", "fairness", "self_recognition", "eval_awareness"}
        views = read_jsonl(d / "scores_views.jsonl")
        assert len(views) == r["n_score_requests"] and (r["info_arm"] != "none" or len(views) == 1)
        if r["info_arm"] in ("sham", "inverted"):
            first = next(v for v in views if v.get("order"))
            # PREREGISTRATION section 4: the first view is exactly the registered order sigma and shows the reference
            # vector permuted to sigma; offsets are fixed there (arms.first_view_offsets) and recorded
            assert first["order"] == r["displayed_order"] == r["intended_displayed_order"]
            ref_desc = sorted((r["reference_scores"][m] for m in r["intended_displayed_order"]), reverse=True)
            assert [first["shown"][m] for m in r["intended_displayed_order"]] == pytest.approx(ref_desc, abs=2e-4)
            assert r["offsets_applied"] == first["offsets_applied"]
            for k in first["shown"]:   # shown = true + fixed offset, clipped (arms.displayed_scores)
                assert first["shown"][k] == pytest.approx(min(1.0, max(0.0, first["true"][k] + first["offsets_applied"][k])), abs=2e-4)
        elif r["info_arm"] == "narrative":
            assert views[0]["kind"] == "narrative" and views[0]["leader"] == r["displayed_leader"]


# (2) null: tracking = 0 ----------------------------------------------------------------------------------

def test_null_tracking_tau_near_zero(default_tree):
    out, _ = default_tree
    rows = read_jsonl(out / "results" / "benchmarks.jsonl")
    by_d = {}
    for r in rows:
        if r["valid"] and r["info_arm"] == "sham" and r["identity_arm"] == "blinded":
            by_d.setdefault(r["designer"], []).append(tau_to_displayed(r))
    assert len(by_d) == 12 and sum(len(v) for v in by_d.values()) == 60
    assert abs(designer_mean(by_d)) < 0.08


# (3) injected tracking -----------------------------------------------------------------------------------

def test_injected_tracking_raises_tau(tmp_path):
    S.generate(tmp_path, seed=202, n_designers=6, sessions_per_designer={"sham_blinded": 5}, tracking=0.6)
    rows = read_jsonl(tmp_path / "results" / "benchmarks.jsonl")
    by_d = {}
    for r in rows:
        by_d.setdefault(r["designer"], []).append(tau_to_displayed(r))
    assert designer_mean(by_d) > 0.25


# (4) injected rank gain ----------------------------------------------------------------------------------

def test_rank_gain_moves_leader_up(tmp_path):
    S.generate(tmp_path, seed=303, n_designers=6, sessions_per_designer={"sham_blinded": 5, "none_blinded": 5}, rank_gain=2.0)
    rows = read_jsonl(tmp_path / "results" / "benchmarks.jsonl")
    none = {}
    for r in rows:
        if r["info_arm"] == "none":
            for k, v in ranks(r).items():
                none.setdefault((r["designer"], k), []).append(v)
    gains = {}
    for r in rows:
        if r["info_arm"] == "sham":
            lead = r["displayed_leader"]
            assert lead == r["intended_displayed_order"][0]          # registered leader (first-view order may differ)
            gains.setdefault(r["designer"], []).append(np.mean(none[(r["designer"], lead)]) - ranks(r)[lead])
    assert designer_mean(gains) >= 1.0


# (5) injected identity effect ----------------------------------------------------------------------------

def test_identity_effect_raises_self_rank(tmp_path):
    S.generate(tmp_path, seed=404, n_designers=6, sessions_per_designer={"sham_blinded": 5, "sham_true": 5}, identity_effect=2.0)
    rows = read_jsonl(tmp_path / "results" / "benchmarks.jsonl")
    by = {"blinded": {}, "true": {}}
    for r in rows:
        by[r["identity_arm"]].setdefault(r["designer"], []).append(ranks(r)[r["designer"]])
        assert r["named"] == (r["identity_arm"] == "true")
    assert designer_mean(by["blinded"]) - designer_mean(by["true"]) >= 1.0


# (6) invalid sessions and replacements -------------------------------------------------------------------

def test_invalid_rate_replacements(tmp_path):
    summary = S.generate(tmp_path, seed=505, n_designers=3, n_pool=150, invalid_rate=0.2,
                         sessions_per_designer={"sham_blinded": 4, "none_blinded": 3, "true_named_true": 2})
    rows = read_jsonl(tmp_path / "results" / "benchmarks.jsonl")
    invalid = [r for r in rows if not r["valid"]]
    reps = [r for r in rows if r["replacement_of"]]
    assert 1 <= len(invalid) <= 12 and len(reps) == len(invalid) == summary["n_replacements"]
    assert len(rows) == 27 + len(reps)
    by_id = {r["session_id"]: r for r in rows}
    for r in reps:
        assert r["session_id"] == r["replacement_of"] + "_rep1" and r["valid"] and r["status"] == "ok" and r["n_items"] == 100
        o = by_id[r["replacement_of"]]
        assert not o["valid"] and o["replacement_of"] is None and o["n_items"] != 100
        assert o["status"] == "refusal" or (o["status"] == "ok" and o["n_items"] != 100)
        assert (r["designer"], r["info_arm"], r["identity_arm"], r["replicate"]) == (o["designer"], o["info_arm"], o["identity_arm"], o["replicate"])
        assert r["seed"] != o["seed"] and r["config_hash"] != o["config_hash"]
        assert not (tmp_path / "sessions" / o["session_id"] / "probes.json").exists()
    for r in rows:
        if r["valid"] and not r["replacement_of"]:
            assert r["replacement_of"] is None and r["status"] == "ok" and r["n_items"] == 100
    log = read_jsonl(tmp_path / "results" / "session_log.jsonl")
    assert [l["session_id"] for l in log] == [r["session_id"] for r in rows]
    assert all(l["attempt"] == 2 for l in log if l["replacement_of"]) and all(l["exit_code"] == (0 if l["valid"] else 1) for l in log)
    assert set(json.load(open(tmp_path / "registration_full.json"))["configs"]) == set(by_id)


# (7) determinism -----------------------------------------------------------------------------------------

def test_determinism_same_seed_identical_bytes(tmp_path):
    kw = dict(seed=606, n_designers=2, n_pool=150, invalid_rate=0.3, tracking=0.3, rank_gain=1.0,
              sessions_per_designer={"sham_blinded": 3, "none_blinded": 2, "sham_false": 2})
    S.generate(tmp_path / "a", **kw)
    S.generate(tmp_path / "b", **kw)
    for rel in ("results/benchmarks.jsonl", "results/item_outcomes.jsonl", "results/session_log.jsonl", "registration_full.json"):
        assert (tmp_path / "a" / rel).read_bytes() == (tmp_path / "b" / rel).read_bytes(), rel
    S.generate(tmp_path / "c", **{**kw, "seed": 607})
    assert (tmp_path / "a" / "results/benchmarks.jsonl").read_bytes() != (tmp_path / "c" / "results/benchmarks.jsonl").read_bytes()


def test_registered_master_seed_is_refused(tmp_path):
    with pytest.raises(ValueError):
        S.generate(tmp_path, seed=20261025, n_designers=1, sessions_per_designer={"none_blinded": 1})


# (8) item outcomes ---------------------------------------------------------------------------------------

def test_item_outcomes_rows_per_valid_session(default_tree):
    out, _ = default_tree
    rows = read_jsonl(out / "results" / "benchmarks.jsonl")
    counts, bad = {}, 0
    with open(out / "results" / "item_outcomes.jsonl") as f:
        for line in f:
            r = json.loads(line)
            counts[r["session_id"]] = counts.get(r["session_id"], 0) + 1
            bad += (r["n_correct"] > r["n_samples"]) or (r["n_samples"] != 5)
    assert bad == 0
    for r in rows:
        assert r["valid"] and counts[r["session_id"]] == 100 * 17
    one = rows[0]
    per_session = read_jsonl(out / "sessions" / one["session_id"] / "item_outcomes.jsonl")
    assert {x["item_id"] for x in per_session} == set(one["items"]) and {x["model_key"] for x in per_session} == set(one["panel_keys"])
    # produced scores are the per-item means of these rows (unweighted sessions)
    if one["scoring_rule"] == "accuracy":
        acc = {}
        for x in per_session:
            acc.setdefault(x["model_key"], []).append(x["n_correct"] / x["n_samples"])
        for m, v in acc.items():
            assert one["produced_scores"][m] == pytest.approx(np.mean(v), abs=1e-4)
