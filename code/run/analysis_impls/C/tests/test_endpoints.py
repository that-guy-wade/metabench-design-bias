"""Endpoint tests on synthetic trees (the shared generator is the only test-data source). Each can fail."""
from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import kstest

from cimpl.endpoints import Table, primary, secondary
from cimpl.load import load
from conftest import PY, RUN, SMALL, generate

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run as runmod  # noqa: E402

N_PERM, N_BOOT = 1000, 400


def _ref_rank12(b, key: str) -> int:
    keys = sorted(b.displayed_keys, key=lambda k: -b.reference_scores[k])
    keys = [k for k in keys if k in b.panel_keys]
    return keys.index(key) + 1


def test_null_primary_p_uniform_and_estimate_near_zero(tmp_path_factory):
    """16 independent null trees: randomisation p ~ U(0,1) (KS), designer-averaged tanh(psi) ~ 0."""
    base = tmp_path_factory.mktemp("nulls")
    seeds = list(range(7001, 7017))
    with ThreadPoolExecutor(4) as ex:
        dirs = list(ex.map(lambda s: generate(base / f"n{s}", s, *SMALL), seeds))
    ps, ests, covers = [], [], []
    for d in dirs:
        r = primary(Table(load(d)), 600, 300, 1)
        ps.append(r["randomisation"]["p_one_sided"]); ests.append(r["estimate_tanh_psi"])
        lo, hi = r["cluster_bootstrap"]["ci95_tanh"]; covers.append(lo <= 0 <= hi)
    ps, ests = np.array(ps), np.array(ests)
    assert kstest(ps, "uniform").pvalue > 0.01, ps
    assert abs(ests.mean()) < 3 * ests.std(ddof=1) / np.sqrt(len(ests)) + 0.02, ests
    assert np.mean(covers) >= 0.75, covers


def test_tracking_detected(trees):
    r = primary(Table(load(trees["tracking"])), N_PERM, N_BOOT, 1)
    assert r["estimate_tanh_psi"] > 0.1
    assert r["randomisation"]["p_one_sided"] < 0.05
    assert r["cluster_bootstrap"]["ci95_tanh"][0] > 0
    r0 = primary(Table(load(trees["null"])), N_PERM, N_BOOT, 1)
    assert r0["estimate_tanh_psi"] < r["estimate_tanh_psi"] - 0.1


def test_rank_gain_recovered_within_half_position(trees):
    tab = Table(load(trees["rank_gain"]))
    s = secondary(tab, N_PERM, N_BOOT, 1)["S1_displayed_leader_rank_gain"]
    # the generator raises the leader's relative score by 2 reference gaps; in positions that is the number of displayed
    # entries whose reference score lies within 2 gaps above the leader (a leader near the top cannot gain 2 positions)
    rows = [b for b in tab.rows if b.info_arm in ("sham", "narrative") and b.displayed_leader]
    gap = tab.reference_gap
    expected = float(np.mean([sum(1 for k in b.displayed_keys if b.reference_scores[b.displayed_leader] < b.reference_scores[k]
                                  <= b.reference_scores[b.displayed_leader] + 2 * gap) for b in rows]))
    assert abs(s["estimate"] - expected) < 0.5, (s["estimate"], expected)
    assert abs(s["leader_score_shift"]["estimate_in_reference_gaps"] - 2.0) < 0.4, s["leader_score_shift"]
    assert s["permutation"]["p_one_sided"] < 0.05
    assert s["ci95_cluster_bootstrap"][0] > 0
    s0 = secondary(Table(load(trees["null"])), N_PERM, N_BOOT, 1)["S1_displayed_leader_rank_gain"]
    assert abs(s0["estimate"]) < 0.5


def test_identity_effect_recovered_in_identity_contrast(trees):
    tab = Table(load(trees["identity"]))
    s2 = secondary(tab, N_PERM, N_BOOT, 1)["S2_designer_self_rank_gain"]
    designers = sorted({b.designer for b in tab.rows})
    expected = float(np.mean([min(2, _ref_rank12(next(b for b in tab.rows if b.designer == d), d) - 1) for d in designers]))
    assert abs(s2["estimate"] - expected) < 0.6, (s2["estimate"], expected)
    assert s2["permutation"]["p_one_sided"] < 0.05
    gains = s2["self_rank_gain_vs_none_by_arm"]
    assert gains["true_self"]["estimate"] > gains["blinded_self"]["estimate"] + 0.5
    assert gains["false_told"]["estimate"] > 0.5                       # the told entry gains in the false-label arm
    assert gains["false_told"]["randomisation"]["p_one_sided"] < 0.05
    assert abs(gains["blinded_self"]["estimate"]) < 0.6                # pseudonyms: no self effect injected
    s2_null = secondary(Table(load(trees["null"])), N_PERM, N_BOOT, 1)["S2_designer_self_rank_gain"]
    assert abs(s2_null["estimate"]) < 0.6


def test_holm_family_has_four_members(trees):
    s = secondary(Table(load(trees["null"])), 200, 100, 1)
    assert sorted(s["holm"]) == ["S1", "S2", "S3", "S4"]
    for v in s["holm"].values():
        assert 0 <= v["p_one_sided"] <= v["p_holm"] <= 1


def test_determinism_two_runs_identical(trees, tmp_path):
    outs = []
    for i in range(2):
        out = tmp_path / f"run{i}"
        subprocess.run([PY, str(Path(runmod.__file__)), "--results", str(trees["null"]), "--out", str(out),
                        "--n-perm", "200", "--n-boot", "200"], check=True, cwd=RUN, capture_output=True)
        outs.append((out / "endpoints.json").read_bytes())
    assert outs[0] == outs[1]
    e = json.loads(outs[0])
    assert "estimate_tanh_psi" in e["primary"] and "gamma_pooled" in e["measurement_model"]["mixed"]


def test_every_estimate_carries_a_ci(trees, tmp_path):
    out = tmp_path / "ci"
    subprocess.run([PY, str(Path(runmod.__file__)), "--results", str(trees["null"]), "--out", str(out),
                    "--n-perm", "100", "--n-boot", "100", "--skip-measurement"], check=True, cwd=RUN, capture_output=True)
    e = json.loads((out / "endpoints.json").read_text())

    def walk(node, path):
        if isinstance(node, dict):
            if "estimate" in node:
                assert any(k.startswith("ci95") for k in node), path
            for k, v in node.items():
                walk(v, path + "/" + k)
        elif isinstance(node, list):
            for v in node:
                walk(v, path)
    walk(e["primary"], "primary"); walk(e["secondary"], "secondary"); walk(e["exploratory"], "exploratory")
    assert "ci95_tanh" in e["primary"]["cluster_bootstrap"]
