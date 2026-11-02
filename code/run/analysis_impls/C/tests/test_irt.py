"""Measurement-model tests: known-gamma simulation (coverage), generator rank gain (gamma > 0), null (CI covers 0)."""
from __future__ import annotations

import numpy as np
import pytest

from cimpl import irt
from cimpl.load import Bench, load


class _Stub:
    """Minimal Dataset stand-in: valid benches, panel keys and the two outcome iterables."""

    def __init__(self, benches, panel_keys, ref_rows, bench_rows):
        self.valid, self.panel_keys, self._ref, self._rows = benches, panel_keys, ref_rows, bench_rows

    def reference_outcomes(self):
        return iter(self._ref)

    def item_outcomes(self):
        return iter(self._rows)


def _simulate(seed: int, gamma: float, n_items=160, n_models=17, n_bench=72, items_per_bench=60, k=5, slope_sd=0.10):
    rng = np.random.default_rng(seed)
    models = [f"m{j:02d}" for j in range(n_models)]
    items = [f"P{i:04d}" for i in range(n_items)]
    beta = rng.normal(0.4, 1.2, n_items)
    theta = rng.normal(0.8, 0.4, n_models)
    designers = models[:6]
    conds = ["sham", "inverted", "narrative", "instructed", "true_named", "true_blinded"]
    u_sd = 0.15
    d_slope = rng.normal(0, slope_sd, len(designers))
    m_slope = rng.normal(0, slope_sd, n_models)
    ref_rows, bench_rows, benches = [], [], []
    for i, it in enumerate(items):
        for j, m in enumerate(models):
            p = 1 / (1 + np.exp(-(theta[j] + beta[i])))
            ref_rows.append(("REFERENCE", it, m, int(rng.binomial(k, p)), k))
    for b in range(n_bench):
        d = designers[b % len(designers)]
        cond = conds[(b // len(designers)) % len(conds)]        # designers crossed with conditions, as in the design
        leader = models[int(rng.integers(n_models))]
        u_b = rng.normal(0, u_sd)
        sel = rng.choice(n_items, size=items_per_bench, replace=False)
        sid = f"S{b:03d}"
        for i in sel:
            for j, m in enumerate(models):
                eta = theta[j] + beta[i] + u_b
                if m == leader:
                    eta += gamma + d_slope[designers.index(d)] + m_slope[j]
                bench_rows.append((sid, items[i], m, int(rng.binomial(k, 1 / (1 + np.exp(-eta)))), k))
        benches.append(Bench(session_id=sid, designer=d, info_arm=cond, identity_arm="blinded", valid=True, status="ok",
                             displayed_keys=models[:12], panel_keys=models, displayed_order=None, displayed_leader=leader,
                             target_model=leader if cond == "instructed" else None, produced_scores={}, reference_scores={},
                             named=False, n_score_requests=1, designer_model_id="", replacement_of=None))
    return _Stub(benches, models, ref_rows, bench_rows)


@pytest.mark.parametrize("gamma,slope_sd", [(0.6, 0.10), (0.0, 0.10), (0.3, 0.0)])
def test_known_gamma_covered_by_mixed_ci(gamma, slope_sd):
    """Mixed-model Wald CI covers the injected gamma with designer and evaluee slope heterogeneity present. The
    session-clustered fallback GLM is only required to cover when slope heterogeneity is absent: with random slopes
    its clusters (sessions) do not contain the evaluee-level variation, which is the pre-registration's reason for
    the maximal mixed model; with slopes present it is only required to be within 0.1 log-odds."""
    md = irt.build(_simulate(11, gamma, slope_sd=slope_sd))
    mixed = irt.fit_mixed(md)
    assert mixed["converged"]
    rep = irt.summarise_fit(md, mixed)["gamma_pooled"]
    lo, hi = rep["ci95_log_odds"]
    assert lo <= gamma <= hi, (rep, gamma)
    assert abs(rep["log_odds"] - gamma) < 3 * rep["se"]
    glm = irt.summarise_fit(md, irt.fit_glm_cluster(md))["gamma_pooled"]
    if slope_sd == 0.0:
        assert glm["ci95_log_odds"][0] <= gamma <= glm["ci95_log_odds"][1], glm
    else:
        assert abs(glm["log_odds"] - gamma) < 0.1, glm
        assert glm["se"] < rep["se"]            # the fallback is anti-conservative under slope heterogeneity
    if gamma > 0:
        assert lo > 0
        assert rep["ci95_ets_delta"][0] <= 2.35 * gamma <= rep["ci95_ets_delta"][1]
        assert rep["ets_category"] == ("B" if 1.0 <= 2.35 * gamma < 1.5 else "A" if 2.35 * gamma < 1.0 else "C")
        for name, pc in irt.summarise_fit(md, mixed)["gamma_by_condition"].items():
            assert pc["ci95_log_odds"][0] <= gamma <= pc["ci95_log_odds"][1] or abs(pc["log_odds"] - gamma) < 3.5 * pc["se"], name


def test_generator_rank_gain_gives_positive_gamma_and_null_covers_zero(trees):
    md_gain = irt.build(load(trees["rank_gain"]))
    fit = irt.fit_mixed(md_gain)
    g = irt.summarise_fit(md_gain, fit)["gamma_pooled"]
    assert g["ci95_log_odds"][0] > 0, g
    md_null = irt.build(load(trees["null"]))
    g0 = irt.summarise_fit(md_null, irt.fit_mixed(md_null))["gamma_pooled"]
    assert g0["ci95_log_odds"][0] <= 0 <= g0["ci95_log_odds"][1], g0
    assert g["log_odds"] > g0["log_odds"] + 0.05
    screen = irt.dif_screen(md_gain, n_boot=200, seed=0)
    assert screen["n_target_rows"] > 0 and "sham" in screen["by_condition"]
