"""Tests for metabench.power: type-I control at the null, monotone power in D, agreement with the digest table."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from metabench import power as P  # noqa: E402


def test_rank_gain_matches_digest_cell():
    # digests/E-power-sim.py table: k=2, sigma=1, D=8, M=5 -> 0.95; D=4, M=10 -> 0.60
    assert abs(P.power_rank_gain(12, 2.0, 1.0, 8, 5, 0.5, sims=1000, seed=1) - 0.95) < 0.06
    assert abs(P.power_rank_gain(12, 2.0, 1.0, 4, 10, 0.5, sims=1000, seed=1) - 0.60) < 0.08


def test_rank_gain_null_type_I():
    assert P.power_rank_gain(12, 0.0, 2.0, 8, 5, 0.5, sims=1500, seed=2) < 0.09


def test_power_monotone_in_D():
    pr = [P.power_rank_gain(12, 1.5, 2.0, D, 5, 0.5, sims=800, seed=3) for D in (3, 6, 10, 14)]
    assert all(b >= a - 0.03 for a, b in zip(pr, pr[1:])), pr
    pt = [P.power_tau_primary(12, 0.2, 2.0, D, 5, 0.5, sims=800, seed=3) for D in (3, 6, 10, 14)]
    t = [r["power_t"] for r in pt]; rnd = [r["power_randomization"] for r in pt]
    assert all(b >= a - 0.03 for a, b in zip(t, t[1:])), t
    assert all(b >= a - 0.03 for a, b in zip(rnd, rnd[1:])), rnd


def test_tau_primary_null_and_effect():
    null = P.power_tau_primary(12, 0.0, 2.0, 8, 5, 0.5, sims=1500, seed=4)
    assert null["power_t"] < 0.09 and null["power_randomization"] < 0.09
    assert abs(null["mean_psi_tau"]) < 0.03
    eff = P.power_tau_primary(12, 0.3, 2.0, 8, 10, 0.5, sims=600, seed=4)
    assert eff["power_t"] > 0.8 and eff["power_randomization"] > 0.8 and eff["mean_psi_tau"] > 0.1


def test_psi_null_draws_centered():
    d = P._psi_null_draws(12, 8, 5, n_draws=4000)
    assert abs(d.mean()) < 0.01
    assert 0.0 < d.std() < 0.1


def test_ceiling_rows_shape():
    rows = P.attainable_power_ceiling(12, 2.0, 0.5, sims=100, seed=0, D_range=range(3, 5), M_inf=50)
    assert [r["D"] for r in rows] == [3, 4]
    assert all(0.0 <= v <= 1.0 for r in rows for k, v in r.items() if k not in ("D", "M"))
