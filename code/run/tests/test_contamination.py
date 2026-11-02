"""Contamination check (docs/CONTAMINATION_SPEC.md) on synthetic data only: null, injected gap, not-estimable path,
silent CLI, output schema, solver agreement.  n_boot = 300 for speed."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pytest
import statsmodels.api as sm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from metabench import contamination as K  # noqa: E402

OPENAI_CUTOFF = K.DEVELOPER_CUTOFFS["openai"]
N_BOOT = 300


@pytest.fixture(scope="module")
def null_report(tmp_path_factory):
    ref, pool = K.write_synthetic(tmp_path_factory.mktemp("null"), seed=20261025)
    return K.run_check(ref, pool, n_boot=N_BOOT, seed=20261025)


@pytest.fixture(scope="module")
def injected_report(tmp_path_factory):
    ref, pool = K.write_synthetic(tmp_path_factory.mktemp("inj"), seed=20261025,
                                  contaminate={"gpt55": (0.20, OPENAI_CUTOFF)})
    return K.run_check(ref, pool, n_boot=N_BOOT, seed=20261025)


def test_synthetic_pool_matches_cutoff_table():
    items, rows = K.synthetic(seed=1)
    assert len(items) == 600 and len(rows) == 600 * 17
    post = {d: sum(it["post_cutoff_by_developer"][d] for it in items) / 600 for d in K.DEVELOPERS}
    assert 0.18 < post["google"] < 0.32 and 0.06 < post["openai"] < 0.14
    assert post["anthropic"] == 0 and post["xai"] == 0
    for it in items:
        d = date.fromisoformat(it["source_date"])
        assert it["post_cutoff_by_developer"] == {dev: d > c for dev, c in K.DEVELOPER_CUTOFFS.items()}


def test_null_no_flags(null_report):
    r = null_report
    assert r["inputs"]["n_entries"] == 17 and r["split_a"]["method"] == "post_cutoff_union"
    assert r["flagged"]["a"] == []
    assert len(r["flagged"]["b"]) <= 1 and len(r["flagged"]["c"]) <= 1
    assert r["developers"]["anthropic"]["estimable"] is False and r["developers"]["openai"]["estimable"] is True
    assert all(r["entries"][k]["c"]["estimable"] is False for k in ("fable51", "grok47", "placebo_sonnet55"))


def test_null_false_flag_rate_bounded(tmp_path):
    """Per-entry false-flag rate over seeds stays below 0.15 for every statistic (nominal 0.05)."""
    flags = {"a": 0, "b": 0, "c": 0}
    estim = {"a": 0, "b": 0, "c": 0}
    for s in range(6):
        ref, pool = K.write_synthetic(tmp_path / f"s{s}", seed=3000 + s)
        rep = K.run_check(ref, pool, n_boot=200, seed=s)
        for st in "abc":
            estim[st] += sum(e[st]["estimable"] for e in rep["entries"].values())
            flags[st] += len(rep["flagged"][st])
    for st in "abc":
        assert estim[st] > 0 and flags[st] / estim[st] < 0.15, (st, flags, estim)


def test_injected_contamination_is_flagged(injected_report):
    r = injected_report
    assert r["flagged"]["a"] == ["gpt55"]
    g = r["entries"]["gpt55"]
    assert g["a"]["residual"] > 0 and g["a"]["p_value"] < 0.05
    assert g["c"]["estimable"] and g["c"]["gap_adjusted"] > 0 and g["c"]["gap_adjusted_ci"][0] > 0 and g["c"]["flag"]
    assert "gpt55" in r["flagged"]["any"]


def test_not_estimable_path(tmp_path):
    ref, pool = K.write_synthetic(tmp_path / "flat", seed=7, all_dates_2020=True)
    out = tmp_path / "out"
    env = {**os.environ, "OMP_NUM_THREADS": "1"}
    res = subprocess.run([sys.executable, str(ROOT / "scripts_contamination.py"), "--reference", str(ref), "--pool", str(pool),
                          "--out", str(out), "--n-boot", str(N_BOOT)], capture_output=True, text=True, env=env)
    assert res.returncode == 0, res.stderr
    rep = json.loads((out / "contamination.json").read_text())
    assert rep["split_a"]["method"] == "date_quantile_newest_20pct"
    assert all(v["estimable"] is False and "not estimable" in v["reason"] for v in rep["developers"].values())
    assert all(e["c"]["estimable"] is False and e["c"]["n_post"] == 0 for e in rep["entries"].values())
    # one identical date -> (a) and (b) not estimable, still exit 0
    items = [json.loads(l) for l in pool.read_text().splitlines()]
    for it in items:
        it["source_date"] = "2020-06-01"
    pool2 = tmp_path / "pool_same.jsonl"
    pool2.write_text("".join(json.dumps(it) + "\n" for it in items))
    rep2 = K.run_check(ref, pool2, n_boot=50, seed=1)
    assert rep2["split_a"]["method"] == "not_estimable"
    assert all(not e["a"]["estimable"] and not e["b"]["estimable"] for e in rep2["entries"].values())
    assert rep2["flagged"]["any"] == []


def test_cli_prints_only_one_status_line(tmp_path):
    ref, pool = K.write_synthetic(tmp_path / "d", seed=20261025, contaminate={"gpt55": (0.20, OPENAI_CUTOFF)})
    env = {**os.environ, "OMP_NUM_THREADS": "1"}
    res = subprocess.run([sys.executable, str(ROOT / "scripts_contamination.py"), "--reference", str(ref), "--pool", str(pool),
                          "--out", str(tmp_path / "o"), "--n-boot", "100"], capture_output=True, text=True, env=env)
    assert res.returncode == 0, res.stderr
    lines = res.stdout.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("contamination_check entries=17 items=600")
    assert "flag" not in res.stdout.lower() and not re.search(r"\d\.\d{3}", res.stdout)
    assert "gpt55" not in res.stdout
    # failure path: bad input -> exit 1, still one line, traceback on stderr
    bad = subprocess.run([sys.executable, str(ROOT / "scripts_contamination.py"), "--reference", str(tmp_path / "missing.jsonl"),
                          "--pool", str(pool), "--out", str(tmp_path / "o2")], capture_output=True, text=True, env=env)
    assert bad.returncode == 1 and len(bad.stdout.strip().splitlines()) == 1 and "exit=1" in bad.stdout


def test_output_schema(null_report):
    r = null_report
    for top in ("spec_version", "inputs", "split_a", "regression_a", "panel_b", "developers", "entries", "flagged", "elapsed_s"):
        assert top in r
    assert set(r["flagged"]) == {"a", "b", "c", "any"}
    assert set(r["developers"]) == set(K.DEVELOPERS)
    assert len(r["entries"]) == 17
    for k, e in r["entries"].items():
        assert list(e) == K.ENTRY_FIELDS, k
        assert e["developer"] == K.SPECS[k].provider
        assert set(e["a"]) == set(K.A_FIELDS) and set(e["b"]) == set(K.B_FIELDS) and set(e["c"]) == set(K.C_FIELDS)
        for blk in ("a", "b", "c"):
            assert isinstance(e[blk]["flag"], bool) and isinstance(e[blk]["estimable"], bool)
            if not e[blk]["estimable"]:
                assert e[blk]["reason"] and e[blk]["flag"] is False
        assert len(e["accuracy_ci"]) == 2 and e["accuracy_ci"][0] <= e["accuracy"] <= e["accuracy_ci"][1]
    json.dumps(r)   # serialisable, no NaN leaks


def test_batched_logistic_matches_statsmodels():
    rng = np.random.default_rng(0)
    n = 400
    X = np.column_stack([np.ones(n), rng.normal(size=n), rng.normal(size=n)])
    S = np.full(n, 5.0)
    C = rng.binomial(5, 1 / (1 + np.exp(-(X @ [0.2, -0.5, 0.8])))).astype(float)
    fit = sm.GLM(np.column_stack([C, S - C]), X, family=sm.families.Binomial()).fit()
    b = K.batched_logistic(X, C, S, np.ones((1, n)))[0]
    assert np.abs(b - fit.params).max() < 1e-5
    # bootstrap weights: two draws give two different, finite solutions
    W = rng.multinomial(n, np.full(n, 1 / n), size=2).astype(float)
    bb = K.batched_logistic(X, C, S, W)
    assert bb.shape == (2, 3) and np.isfinite(bb).all() and not np.allclose(bb[0], bb[1])
