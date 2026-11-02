"""Tests that could fail: null calibration, injected-effect recovery, gamma coverage, determinism, exclusions."""
from __future__ import annotations

import copy
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats

import core
import measurement
import run as runmod

B_DIR = Path(__file__).resolve().parents[1]


def _table(path):
    tree = core.load_tree(path)
    return tree, core.session_table(tree["benchmarks"], tree["configs"])


# ------------------------------------------------------------------------------------------------------------ unit

def test_tau_b_batch_matches_scipy():
    rng = np.random.default_rng(0)
    S = rng.random((200, 13))
    S[:, 3] = S[:, 5]                      # ties in the produced scores
    S[:5, :] = 0.5                         # constant rows -> nan
    y = -np.arange(13, dtype=float)
    got = core.tau_b_batch(S, y)
    want = np.array([stats.kendalltau(s, y, variant="b").statistic for s in S])
    assert np.allclose(got[5:], want[5:], atol=1e-12)
    assert np.all(np.isnan(got[:5]))


def test_rbo_known_values():
    assert core.rbo_ext(list("abcde"), list("abcde"), 0.8) == pytest.approx(1.0)
    assert core.rbo_ext(list("abc"), list("xyz"), 0.8) == pytest.approx(0.0)


def test_holm_and_bh():
    h = core.holm({"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.2})
    assert h["a"]["p_holm"] == pytest.approx(0.04)
    assert h["c"]["p_holm"] == pytest.approx(0.09)
    assert h["b"]["p_holm"] == pytest.approx(0.09)
    assert h["d"]["p_holm"] == pytest.approx(0.2)
    b = core.bh({"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.2})
    assert b["a"]["q_bh"] == pytest.approx(0.04)
    assert b["d"]["q_bh"] == pytest.approx(0.2)


# ------------------------------------------------------------------------------------------------------------ null

def test_null_primary_near_zero_and_randomisation_p_uniform(trees):
    tree, df = _table(trees["null"])
    rng = np.random.default_rng(1)
    p = core.primary_endpoint(df, 2000, 1000, rng)
    assert p["n_benchmarks"] == 60 and p["n_designers"] == 12
    assert abs(p["estimate_tanh"]) < 0.06
    lo, hi = p["cluster_bootstrap"]["ci95_tanh"]
    assert lo < 0 < hi
    assert p["randomisation"]["p_one_sided"] > 0.05
    # Under H0 the produced scores are independent of the display, so re-drawing every displayed order from the registered
    # generator yields exact null replicates of the whole dataset; the randomisation p must then be ~Uniform(0,1).
    pop = df[(df.info_arm == "sham") & (df.identity_arm == "blinded")]
    ps, ests = [], []
    for rep in range(150):
        d2 = pop.copy()
        d2["displayed_order"] = [list(np.array(k)[rng.permutation(len(k))]) for k in d2.displayed_keys]
        d2["tau_disp"] = [core.tau_b(sc, o) for sc, o in zip(d2.disp_scores, d2.displayed_order)]
        d2.attrs.update(df.attrs)
        r = core.primary_endpoint(d2, 400, 20, np.random.default_rng(100 + rep))
        ps.append(r["randomisation"]["p_one_sided"])
        ests.append(r["estimate_tanh"])
    ps = np.array(ps)
    assert stats.kstest(ps, "uniform").pvalue > 0.01, f"p-values not uniform: {np.round(np.sort(ps)[:10], 3)}"
    assert 0.01 <= (ps < 0.05).mean() <= 0.11
    assert abs(np.mean(ests)) < 0.02


def test_null_secondaries_and_gamma_are_null(trees):
    tree, df = _table(trees["null"])
    rng = np.random.default_rng(2)
    s = core.secondary_endpoints(df, 1000, 500, rng)
    assert abs(s["S1"]["estimate_positions"]) < 0.5
    assert abs(s["S1"]["score_shift"]["estimate_gap_units"]) < 0.5
    assert abs(s["S2"]["S2a_self_gain_true_label"]["estimate"]) < 0.6
    assert abs(s["S3"]["estimate"]) < 0.05
    assert not any(v["reject_at_0.05"] for v in s["holm"].values())
    io = core.load_item_outcomes(tree, set(df.session_id))
    design = measurement.build_design(tree, df, io, core.load_reference_outcomes(tree))
    g = measurement.fit_glm_fe(design)
    assert g["converged"]
    lo, hi = g["gamma_pooled_home_advantage"]["ci95_log_odds"]
    assert lo < 0 < hi and abs(g["gamma_pooled_home_advantage"]["log_odds"]) < 0.05


# ------------------------------------------------------------------------------------------------------------ injected effects

def test_injected_tracking_gives_positive_primary(trees):
    tree, df = _table(trees["track"])
    p = core.primary_endpoint(df, 2000, 1000, np.random.default_rng(3))
    assert p["estimate_tanh"] > 0.08
    assert p["randomisation"]["p_one_sided"] < 0.05
    assert p["cluster_bootstrap"]["ci95_tanh"][0] > 0
    assert p["designer_t"]["p_one_sided"] < 0.05


def test_injected_rank_gain_recovered(trees):
    tree, df = _table(trees["gain"])
    s = core.secondary_endpoints(df, 1000, 1000, np.random.default_rng(4))
    s1 = s["S1"]
    # the generator raises the leader's relative score by 2.0 reference gaps; the score-scale companion must recover it
    assert abs(s1["score_shift"]["estimate_gap_units"] - 2.0) < 0.5
    lo, hi = s1["score_shift"]["ci95_gap_units"]
    assert lo < 2.0 < hi
    # in positions the gain is bounded above by the leader's room to move (a leader displayed #1 that already ranks #1 cannot gain),
    # so the positional estimate is positive, significant and within 0.5 positions of the ceiling-adjusted expectation
    assert s1["estimate_positions"] > 1.0
    assert s1["permutation"]["p_one_sided"] < 0.05
    assert s1["cluster_bootstrap"]["ci95"][0] > 0
    expected_positions = _expected_positional_gain(df, 2.0)
    assert abs(s1["estimate_positions"] - expected_positions) < 0.5, (s1["estimate_positions"], expected_positions)
    assert s["holm"]["S1_leader_gain"]["reject_at_0.05"]


def _expected_positional_gain(df: pd.DataFrame, gaps: float) -> float:
    """Expected rank-position gain if the leader's relative score rises by `gaps` reference gaps: apply that shift to each
    none-arm benchmark's produced scores for a uniformly random leader and re-rank."""
    panel13 = df.attrs["panel13"]
    gap = df.attrs["reference_gap"]
    none = df[df.cell == "none/blinded"]
    gains = []
    for r in none.itertuples():
        sc = {k: r.rel13[k] for k in panel13}
        base = core.ranks_desc(sc, panel13)
        for lead in panel13:
            sc2 = dict(sc)
            sc2[lead] += gaps * gap
            gains.append(base[lead] - core.ranks_desc(sc2, panel13)[lead])
    return float(np.mean(gains))


def test_injected_identity_effect_recovered(trees):
    tree, df = _table(trees["ident"])
    s = core.secondary_endpoints(df, 1000, 1000, np.random.default_rng(5))
    s2 = s["S2"]
    assert s2["S2a_self_gain_true_label"]["estimate"] > 1.0
    assert s2["S2a_self_gain_true_label"]["permutation"]["p"] < 0.05
    assert s2["S2a_self_gain_true_label"]["cluster_bootstrap"]["ci95"][0] > 0
    assert s2["S2b_told_identity_gain_false_label"]["estimate"] > 1.0
    assert s2["S2b_told_identity_gain_false_label"]["permutation"]["p"] < 0.05
    assert abs(s2["S2c_actual_self_gain_false_label"]["estimate"]) < 0.6
    sc = s2["score_shift"]
    assert abs(sc["S2a_self_gain_true_label"]["estimate_gap_units"] - 2.0) < 0.5
    assert abs(sc["S2b_told_identity_gain_false_label"]["estimate_gap_units"] - 2.0) < 0.5
    assert abs(sc["S2c_actual_self_gain_false_label"]["estimate_gap_units"]) < 0.5
    assert s["holm"]["S2_self_gain_true_label"]["reject_at_0.05"]
    # the identity tilt must not leak into the primary (sham/blinded has no identity line)
    p = core.primary_endpoint(df, 500, 200, np.random.default_rng(6))
    assert abs(p["estimate_tanh"]) < 0.08


# ------------------------------------------------------------------------------------------------------------ measurement model

def _inject_gamma(src: Path, dst: Path, gamma: float, seed: int = 21, slope_sd: float = 0.15) -> dict:
    """Copy a tree and redraw every item outcome (benchmarks + anchor) from the section-8 model with a known gamma.
    Returns gamma and the realised row-weighted average of gamma + designer slope + evaluee slope over Target rows
    (what a pooled fixed-effect estimate targets when random slopes are present)."""
    rng = np.random.default_rng(seed)
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "results").mkdir(exist_ok=True)
    shutil.copy(src / "results" / "benchmarks.jsonl", dst / "results" / "benchmarks.jsonl")
    tree = core.load_tree(src)
    bench = core.valid_rows(tree["benchmarks"])
    keys = bench[0]["panel_keys"]
    ref = bench[0]["reference_scores"]
    theta = {m: math.log(ref[m] / (1 - ref[m])) for m in keys}
    pool = sorted({i for b in bench for i in b["items"]} | set(pd.read_json(src / "reference_item_outcomes.jsonl", lines=True).item_id))
    beta = {i: float(rng.normal(0.0, 1.0)) for i in pool}
    designers = sorted({b["designer"] for b in bench})
    slope_d = {d: float(rng.normal(0.0, slope_sd)) for d in designers}   # random Target slope by designer
    slope_m = {m: float(rng.normal(0.0, slope_sd)) for m in keys}        # random Target slope by evaluee
    k = 5
    realised = []
    with open(dst / "results" / "item_outcomes.jsonl", "w") as f:
        for b in bench:
            u_b = float(rng.normal(0.0, 0.3))
            leader = b.get("target_model") or b.get("displayed_leader")
            if b["info_arm"] not in core.LEADER_ARMS:
                leader = None
            for i in b["items"]:
                for m in keys:
                    t = 1.0 if m == leader else 0.0
                    if t:
                        realised.append(gamma + slope_d[b["designer"]] + slope_m[m])
                    eta = theta[m] + beta[i] + u_b + t * (gamma + slope_d[b["designer"]] + slope_m[m])
                    y = int(rng.binomial(k, 1 / (1 + math.exp(-eta))))
                    f.write(json.dumps({"session_id": b["session_id"], "item_id": i, "model_key": m, "n_correct": y, "n_samples": k}) + "\n")
    with open(dst / "reference_item_outcomes.jsonl", "w") as f:
        for i in pool:
            for m in keys:
                y = int(rng.binomial(k, 1 / (1 + math.exp(-(theta[m] + beta[i])))))
                f.write(json.dumps({"session_id": "REFERENCE", "item_id": i, "model_key": m, "n_correct": y, "n_samples": k}) + "\n")
    return {"gamma": gamma, "realised_pooled": float(np.mean(realised))}


@pytest.mark.parametrize("slope_sd", [0.0, 0.15])
def test_injected_gamma_covered_by_fallback_glm_ci(trees, tmp_path, slope_sd):
    gamma = 0.5
    inj = _inject_gamma(trees["small"], tmp_path / "gamma_tree", gamma, slope_sd=slope_sd)
    tree, df = _table(tmp_path / "gamma_tree")
    io = core.load_item_outcomes(tree, set(df.session_id))
    design = measurement.build_design(tree, df, io, core.load_reference_outcomes(tree))
    g = measurement.fit_glm_fe(design)
    assert g["converged"]
    est = g["gamma_pooled_home_advantage"]
    lo, hi = est["ci95_log_odds"]
    # with no slope heterogeneity the pooled estimand is gamma itself; with random slopes the pooled fixed effect targets the
    # realised row-weighted average (session-cluster SEs do not carry designer/evaluee heterogeneity: that is the mixed model's job)
    target = gamma if slope_sd == 0 else inj["realised_pooled"]
    assert lo < target < hi, (est["log_odds"], lo, hi, target)
    assert abs(est["log_odds"] - target) < 0.1
    assert est["ets_delta"] == pytest.approx(2.35 * est["log_odds"])
    assert not (lo < 0 < hi)                        # a null gamma must not be covered


@pytest.mark.slow
def test_injected_gamma_covered_by_mixed_model_ci(trees, tmp_path):
    gamma = 0.5
    _inject_gamma(trees["small"], tmp_path / "gamma_tree", gamma)
    tree, df = _table(tmp_path / "gamma_tree")
    io = core.load_item_outcomes(tree, set(df.session_id))
    design = measurement.build_design(tree, df, io, core.load_reference_outcomes(tree))
    m = measurement.fit_mixed_laplace(design, maxiter=120)
    est = m["gamma_pooled_home_advantage"]
    lo, hi = est["ci95_log_odds"]
    assert lo < gamma < hi, (est["log_odds"], lo, hi)
    assert abs(est["log_odds"] - gamma) < 0.25


# ------------------------------------------------------------------------------------------------------------ pipeline

def test_invalid_sessions_excluded_and_counted(trees, tmp_path):
    rep = runmod.run(str(trees["invalid"]), str(tmp_path / "out"), 200, 200, 7, 1.0, False, 10)
    inp = rep["inputs"]
    assert inp["n_invalid"] > 0 and inp["n_replacements"] > 0
    assert inp["n_valid"] + inp["n_invalid"] == inp["n_rows"]
    assert len(inp["invalid_sessions"]) == inp["n_invalid"]
    bench = core.load_tree(trees["invalid"])["benchmarks"]
    n_valid_sham_blinded = sum(1 for b in bench if b["valid"] and b["info_arm"] == "sham" and b["identity_arm"] == "blinded")
    assert rep["primary"]["n_benchmarks"] == n_valid_sham_blinded
    ep = json.load(open(tmp_path / "out" / "endpoints.json"))
    assert ep["measurement_model"]["reported"] == "fallback_glm"


def test_run_is_deterministic(trees, tmp_path):
    args = ["--results", str(trees["small"]), "--n-perm", "300", "--n-boot", "300", "--no-mixed"]
    runmod.main([*args, "--out", str(tmp_path / "a")])
    runmod.main([*args, "--out", str(tmp_path / "b")])
    a = (tmp_path / "a" / "endpoints.json").read_bytes()
    b = (tmp_path / "b" / "endpoints.json").read_bytes()
    assert a == b
    ep = json.loads(a)
    for section in ("primary", "secondary", "exploratory", "measurement_model"):
        assert section in ep
    # every reported estimate carries an interval
    assert "ci95_tanh" in ep["primary"]["cluster_bootstrap"]
    for k in ("S1", "S3", "S4"):
        assert "ci95" in ep["secondary"][k]["cluster_bootstrap"]
    assert "ci95" in ep["secondary"]["S2"]["S2a_self_gain_true_label"]["cluster_bootstrap"]
    assert "ci95_log_odds" in ep["measurement_model"]["fallback_glm"]["gamma_pooled_home_advantage"]
    assert "ci95" in ep["exploratory"]["rbo_p0.8_sham_blinded"]["cluster_bootstrap"]
