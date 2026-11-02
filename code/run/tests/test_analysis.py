"""Tests for metabench.analysis: hand-computed tau-b, null calibration of the primary randomization test, detection
of an injected tracking effect, injected rank-gain recovery, DIF gamma recovery, CLI round trip."""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from metabench import analysis as A  # noqa: E402

KEYS = ["opus55", "sonnet55", "sonnet46", "haiku45", "gpt55", "gpt54mini", "gpt54nano", "gpt51", "gpt41", "gpt4omini"]
EXTRA = ["placebo_sonnet55", "heldout_opus5", "heldout_gpt54"]
DESIGNERS = ["opus55", "sonnet55", "gpt55"]


def reference_scores(gap=0.03):
    """Equally spaced reference ranking over the displayed panel; placebo == sonnet55; held-outs mid-pack."""
    order = ["gpt55", "opus55", "sonnet55", "gpt51", "sonnet46", "gpt54mini", "gpt41", "haiku45", "gpt54nano", "gpt4omini"]
    ref = {k: 0.9 - i * gap for i, k in enumerate(order)}
    ref["placebo_sonnet55"] = ref["sonnet55"]
    ref["heldout_opus5"] = ref["opus55"] - gap / 2
    ref["heldout_gpt54"] = ref["gpt51"] - gap / 2
    return ref


def make_rows(rng, n_per_designer=4, arms=("none", "sham"), sigma=0.01, track=0.0, identity="blinded", seed_base=0):
    """Synthetic benchmark rows. produced = reference + noise + track*(displayed_score - reference) in sham arms."""
    rows = []
    ref = reference_scores()
    gap = 0.03
    sid = 0
    for d in DESIGNERS:
        for arm in arms:
            for rep in range(n_per_designer):
                sid += 1
                keys = KEYS + EXTRA
                prod = {k: ref[k] + sigma * rng.standard_normal() for k in keys}
                prod["placebo_sonnet55"] = ref["sonnet55"] + sigma * rng.standard_normal()
                disp = None; leader = None
                if arm in ("sham", "true_blinded", "true_named", "inverted", "instructed"):
                    if arm == "sham":
                        disp = [KEYS[i] for i in rng.permutation(len(KEYS))]
                    elif arm == "inverted":
                        disp = sorted(KEYS, key=lambda k: ref[k])
                    else:
                        disp = sorted(KEYS, key=lambda k: -ref[k])
                    leader = disp[0]
                    if track:
                        dscore = {k: ref[disp[0]] - gap * i for i, k in enumerate(disp)}  # displayed score of model k
                        for k in KEYS:
                            prod[k] += track * (dscore[k] - ref[k])
                rows.append({"session_id": f"s{seed_base}_{sid}", "designer": d, "info_arm": arm, "identity_arm": identity,
                             "tier": "T1", "replicate": rep, "seed": sid, "valid": True,
                             "items": [f"P{i:04d}" for i in range(1, 101)], "weights": {},
                             "displayed_order": disp, "displayed_leader": leader, "target_model": None,
                             "produced_scores": prod, "reference_scores": dict(ref)})
    return rows


# ---------------------------------------------------------------------------------------------- tau-b

def test_tau_b_hand_examples():
    a = {"x": 3, "y": 2, "z": 1}
    assert A.kendall_tau_b(a, {"x": 30, "y": 20, "z": 10}) == pytest.approx(1.0)
    assert A.kendall_tau_b(a, {"x": 1, "y": 2, "z": 3}) == pytest.approx(-1.0)
    # one swap among 4 -> (5-1)/6
    assert A.kendall_tau_b({"a": 4, "b": 3, "c": 2, "d": 1}, {"a": 4, "b": 2, "c": 3, "d": 1}) == pytest.approx(4 / 6)
    # ties: a = (1,1,0), b = (2,1,0): S=2, n0=3, n1=1, n2=0 -> 2/sqrt(6)
    assert A.kendall_tau_b({"A": 1, "B": 1, "C": 0}, {"A": 2, "B": 1, "C": 0}) == pytest.approx(2 / math.sqrt(6))
    assert math.isnan(A.kendall_tau_b({"A": 1, "B": 1}, {"A": 2, "B": 1}))      # constant input
    # displayed-order conversion: best-first order equals ranking by scores
    assert A.kendall_tau_b(a, A.order_to_scores(["x", "y", "z"])) == pytest.approx(1.0)


def test_tau_b_vectorised_matches_scipy():
    rng = np.random.default_rng(0)
    s = rng.standard_normal(10)
    s[3] = s[4]  # a tie
    orders = rng.random((50, 10)).argsort(axis=1).astype(float)
    v = A.tau_b_vectorised(s, orders)
    from scipy import stats
    for i in range(50):
        assert v[i] == pytest.approx(stats.kendalltau(s, orders[i], variant="b")[0], abs=1e-12)


def test_fisher_holm_rbo():
    assert A.fisher_z(0.5) == pytest.approx(np.arctanh(0.5))
    assert A.fisher_z(1.0) == pytest.approx(np.arctanh(0.999))
    assert A.fisher_z_mean([0.5, 0.5]) == pytest.approx(0.5)
    assert A.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert A.holm([0.2, float("nan")])[0] == pytest.approx(0.2) and math.isnan(A.holm([0.2, float("nan")])[1])
    assert A.rbo(list("abcdef"), list("abcdef"), 0.8) == pytest.approx(1.0)
    assert A.rbo(list("abcdef"), list("fedcba"), 0.8) < 0.6


# ---------------------------------------------------------------------------------------------- primary endpoint

def test_primary_null_calibration():
    """Under H0 (produced independent of displayed), p-values are ~uniform and Psi ~ 0."""
    rng = np.random.default_rng(1)
    ps, psis = [], []
    for i in range(100):
        rows = make_rows(rng, n_per_designer=4, arms=("sham",), sigma=0.01, track=0.0, seed_base=i)
        r = A.primary_endpoint(rows, n_perm=200, n_boot=20, seed=i)
        ps.append(r["p_one_sided"]); psis.append(r["psi"])
    assert abs(np.mean(ps) - 0.5) < 0.08, np.mean(ps)
    assert abs(np.mean(psis)) < 0.05, np.mean(psis)
    assert np.mean(np.array(ps) < 0.05) < 0.12   # type-I control (loose, 100 datasets)


def test_primary_detects_tracking():
    rng = np.random.default_rng(2)
    rows = make_rows(rng, n_per_designer=5, arms=("sham",), sigma=0.01, track=0.5)
    r = A.primary_endpoint(rows, n_perm=1000, n_boot=200, seed=3)
    assert r["psi"] > 0.15
    assert r["p_one_sided"] < 0.05
    assert r["ci95_bench_tau"][0] > 0
    assert r["n_designers"] == 3 and r["cluster_bootstrap_degenerate"] is True


def test_primary_is_pseudonymous_not_pooled():
    """PREREGISTRATION section 7: the primary is Psi in the sham arm under pseudonymous identity (identity_arm == "blinded").
    Pilot defect (DEVIATIONS 2026-10-25 02:05, section 7): the CLI pooled every sham session regardless of identity arm."""
    rng = np.random.default_rng(21)
    rows = make_rows(rng, n_per_designer=10, arms=("sham",), sigma=0.01, track=0.0, identity="blinded")
    rows += make_rows(rng, n_per_designer=10, arms=("sham",), sigma=0.01, track=0.8, identity="true", seed_base=1)
    prim = A.primary_endpoint(rows, n_perm=200, n_boot=50, seed=1)
    pooled = A.primary_endpoint(rows, n_perm=200, n_boot=50, seed=1, identity_arm=None)
    assert prim["identity_arm"] == "blinded" and prim["n"] == 30
    assert abs(prim["psi"]) < 0.1, prim["psi"]
    assert pooled["identity_arm"] == "pooled" and pooled["n"] == 60
    assert pooled["psi"] > 0.15, pooled["psi"]
    named = A.primary_endpoint(rows, n_perm=200, n_boot=50, seed=1, identity_arm="true")
    assert named["n"] == 30 and named["psi"] > 0.5
    assert A.primary_endpoint(rows, n_perm=10, n_boot=10, identity_arm="false")["n"] == 0


# ---------------------------------------------------------------------------------------------- secondary + recovery

def test_recover_injected_effect():
    rng = np.random.default_rng(4)
    rows = make_rows(rng, n_per_designer=4, arms=("none",), sigma=0.002)
    # On an equally spaced reference a latent boost of exactly k gaps lands on a tie (expected realised gain k - 0.5),
    # so boost by k + 0.5 gaps: the realised rank gain is then exactly k, which the estimator must recover.
    for k in (1, 3):
        res = A.recover_injected_effect(rows, target="gpt41", k=k + 0.5, n_perm=200, n_boot=200)
        assert abs(res["gain"] - k) <= 0.5, (k, res["gain"])
        assert res["p_perm_one_sided"] < 0.05
    # no injection -> ~0 gain
    res0 = A.recover_injected_effect(rows, target="gpt41", k=0.0, n_perm=200, n_boot=200)
    assert abs(res0["gain"]) <= 0.5


def test_secondary_endpoints_run_and_detect_leader_gain():
    rng = np.random.default_rng(5)
    rows = make_rows(rng, n_per_designer=4, arms=("none", "sham", "true_blinded", "inverted"), sigma=0.005, track=0.6)
    rows += make_rows(rng, n_per_designer=2, arms=("none", "true_named"), sigma=0.005, identity="true", seed_base=99)
    sec = A.secondary_endpoints(rows, None, n_perm=300, n_boot=300)
    assert sec["leader_rank_gain"]["sham"]["gain"] > 1.0
    assert sec["leader_rank_gain"]["sham"]["p_perm_one_sided"] < 0.05
    assert set(sec["holm"]) == {"leader_rank_gain[sham]", "self_rank_true_vs_blinded", "inverted_tau_minus_none", "true_minus_none_tau"}
    # inverted arm with tracking moves tau up relative to none-arm tau to the reversed reference
    assert sec["inverted_tau"]["diff_z"] > 0
    # placebo: identical configs separate only by noise in none arm
    assert sec["placebo_separation"]["none"]["mean_abs_sep"] < 0.02
    assert "heldout_opus5" in sec["heldout_shift"]
    assert sec["rank_flips"]["by_arm"]["none"]["mean_flips"] < 3


# ---------------------------------------------------------------------------------------------- DIF model

def synth_item_outcomes(rng, n_items=150, gamma=0.6, n_samples=3, items_per_bench=60, n_narrative=0, n_saturated=0,
                        saturated_arm="sham"):
    """Reference pool + sham/none benchmarks with a home advantage `gamma` for the sham leader.
    n_narrative > 0 adds narrative sessions with one target model answered correctly on every item (perfect separation of
    Target x narrative); n_saturated > 0 adds `saturated_arm` sessions in which every model is correct on every item
    (outcomes identical across the whole session cluster)."""
    models = KEYS + EXTRA
    theta = {m: rng.normal(0, 0.8) for m in models}
    theta["placebo_sonnet55"] = theta["sonnet55"]
    beta = {f"P{i:04d}": rng.normal(0.5, 1.0) for i in range(1, n_items + 1)}
    sig = lambda x: 1 / (1 + np.exp(-x))
    ref_rows = [{"session_id": "REFERENCE", "item_id": i, "model_key": m, "n_samples": n_samples,
                 "n_correct": int(rng.binomial(n_samples, sig(theta[m] + beta[i])))} for i in beta for m in models]
    bench, item_rows = [], []
    sid = 0
    for d in DESIGNERS:
        for arm in ("sham", "none"):
            for rep in range(2):
                sid += 1
                items = [f"P{i:04d}" for i in rng.choice(np.arange(1, n_items + 1), items_per_bench, replace=False)]
                leader = None
                if arm == "sham":
                    leader = KEYS[rng.integers(len(KEYS))]
                prod = {}
                for m in models:
                    cs = []
                    for i in items:
                        adv = gamma if (arm == "sham" and m == leader) else 0.0
                        c = int(rng.binomial(n_samples, sig(theta[m] + beta[i] + adv)))
                        item_rows.append({"session_id": f"b{sid}", "item_id": i, "model_key": m, "n_samples": n_samples, "n_correct": c})
                        cs.append(c / n_samples)
                    prod[m] = float(np.mean(cs))
                bench.append({"session_id": f"b{sid}", "designer": d, "info_arm": arm, "identity_arm": "blinded", "tier": "T1",
                              "replicate": rep, "seed": sid, "valid": True, "items": items, "weights": {},
                              "displayed_order": (sorted(KEYS, key=lambda k: -prod[k]) if arm == "sham" else None),
                              "displayed_leader": leader, "target_model": None, "produced_scores": prod,
                              "reference_scores": {m: float(np.mean([r["n_correct"] / n_samples for r in ref_rows if r["model_key"] == m])) for m in models}})
    for j, arm in enumerate(["narrative"] * n_narrative + [saturated_arm] * n_saturated):
        sid += 1
        items = [f"P{i:04d}" for i in rng.choice(np.arange(1, n_items + 1), items_per_bench, replace=False)]
        prod = {}
        for m in models:
            cs = []
            for i in items:
                c = n_samples if (m == "gpt41" or j >= n_narrative) else int(rng.binomial(n_samples, sig(theta[m] + beta[i])))
                item_rows.append({"session_id": f"b{sid}", "item_id": i, "model_key": m, "n_samples": n_samples, "n_correct": c})
                cs.append(c / n_samples)
            prod[m] = float(np.mean(cs))
        bench.append({"session_id": f"b{sid}", "designer": DESIGNERS[j % len(DESIGNERS)], "info_arm": arm, "identity_arm": "blinded",
                      "tier": "T1", "replicate": j, "seed": sid, "valid": True, "items": items, "weights": {},
                      "displayed_order": (sorted(KEYS, key=lambda k: -prod[k]) if arm == "sham" else None),
                      "displayed_leader": "gpt41", "target_model": None, "produced_scores": prod, "reference_scores": bench[0]["reference_scores"]})
    return item_rows, bench, ref_rows


def test_dif_model_recovers_gamma():
    rng = np.random.default_rng(6)
    item_rows, bench, ref_rows = synth_item_outcomes(rng, gamma=0.6)
    res = A.dif_model(item_rows, bench, ref_rows, baseline_arm="sham", fit_mixed=False)
    g = res["effects"]["gamma_Target"]
    lo, hi = g["ci95"]
    assert lo <= 0.6 <= hi, (g["log_odds"], lo, hi)
    assert g["log_odds"] > 0.2
    assert g["ets_delta"] == pytest.approx(2.35 * g["log_odds"])
    assert g["ets_category"] in ("A", "B", "C")
    # null: no advantage -> CI covers 0
    item_rows0, bench0, ref0 = synth_item_outcomes(rng, gamma=0.0)
    res0 = A.dif_model(item_rows0, bench0, ref0, baseline_arm="sham", fit_mixed=False)
    lo0, hi0 = res0["effects"]["gamma_Target"]["ci95"]
    assert lo0 <= 0.0 <= hi0


def test_dif_mixed_model_runs_or_fails_gracefully():
    rng = np.random.default_rng(7)
    item_rows, bench, ref_rows = synth_item_outcomes(rng, n_items=60, gamma=0.8, items_per_bench=25)
    res = A.dif_model(item_rows, bench, ref_rows, baseline_arm="sham", fit_mixed=True, max_mixed_rows=50000)
    mx = res["mixed"]
    assert mx["status"] in ("ok", "failed", "skipped")
    if mx["status"] == "ok":
        assert mx["gamma"] > 0.0


def test_dif_model_degenerate_arm_reported_and_other_ses_finite():
    """Pilot defect (DEVIATIONS 2026-10-25 02:05, section 8): a narrative arm with 3 sessions whose target is correct on
    every item (perfect separation) and one session with identical outcomes across the whole cluster drove the
    session-clustered sandwich onto a singular Hessian: NaN / meaningless SEs. The arm must be reported as degenerate and
    every reported effect must keep finite SE, CI and p; gamma is still recovered."""
    rng = np.random.default_rng(11)
    item_rows, bench, ref_rows = synth_item_outcomes(rng, gamma=0.6, n_narrative=3, n_saturated=1)
    res = A.dif_model(item_rows, bench, ref_rows, baseline_arm="sham", fit_mixed=False)
    assert "narrative" in res["degenerate_arms"], res.get("degenerate_arms")
    assert "separation" in res["degenerate_arms"]["narrative"]["reason"]
    assert res["degenerate_arms"]["narrative"]["n_sessions"] == 3
    assert not any(k.endswith("narrative]") or k.endswith("_narrative") for k in res["effects"]), list(res["effects"])
    for k, v in res["effects"].items():
        assert math.isfinite(v["se"]) and v["se"] > 0, (k, v)
        assert all(math.isfinite(x) for x in v["ci95"]), (k, v)
        if "p" in v:
            assert math.isfinite(v["p"]), (k, v)
    g = res["effects"]["gamma_Target"]
    assert g["ci95"][0] <= 0.6 <= g["ci95"][1], g
    assert res["n_sessions"] == 12 and list(res["degenerate_sessions"]) == ["b16"]
    assert res["degenerate_sessions"]["b16"]["arm"] == "sham" and "warning" not in res


def test_dif_model_separation_never_yields_nan_ses():
    """Saturated session inside the separated narrative arm: on the unscreened fit this is the pilot's exact symptom
    (narrative delta at +26 log-odds and se = NaN, CI = [NaN, NaN], p = NaN for EVERY effect, gamma included)."""
    rng = np.random.default_rng(11)
    item_rows, bench, ref_rows = synth_item_outcomes(rng, gamma=0.6, n_narrative=3, n_saturated=1, saturated_arm="narrative")
    res = A.dif_model(item_rows, bench, ref_rows, baseline_arm="sham", fit_mixed=False)
    assert all(math.isfinite(v["se"]) and abs(v["log_odds"]) < 10 for v in res["effects"].values()), res["effects"]
    assert res["degenerate_arms"]["narrative"]["n_sessions"] == 3 and res["degenerate_sessions"]["b16"]["arm"] == "narrative"


# ---------------------------------------------------------------------------------------------- CLI

def test_cli_round_trip(tmp_path):
    rng = np.random.default_rng(8)
    rows = make_rows(rng, n_per_designer=3, arms=("none", "sham", "true_blinded"), sigma=0.005, track=0.4)
    item_rows, bench, ref_rows = synth_item_outcomes(rng, n_items=40, gamma=0.5, items_per_bench=20)
    resd = tmp_path / "results"; resd.mkdir()
    with open(resd / "benchmarks.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    outd = tmp_path / "out"
    A.main(["--results", str(resd), "--out", str(outd), "--n-perm", "200", "--n-boot", "100", "--no-dif"])
    ep = json.loads((outd / "endpoints.json").read_text())
    assert ep["primary"]["n"] == 9 and (outd / "endpoints.md").exists()
    assert "Psi" in (outd / "endpoints.md").read_text()


def test_cli_writes_primary_by_identity_arm(tmp_path):
    rng = np.random.default_rng(9)
    rows = make_rows(rng, n_per_designer=3, arms=("none", "sham"), sigma=0.005, track=0.4)
    rows += make_rows(rng, n_per_designer=2, arms=("sham",), sigma=0.005, track=0.4, identity="true", seed_base=1)
    resd = tmp_path / "results"; resd.mkdir()
    with open(resd / "benchmarks.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    outd = tmp_path / "out"
    A.main(["--results", str(resd), "--out", str(outd), "--n-perm", "100", "--n-boot", "50", "--no-dif"])
    ep = json.loads((outd / "endpoints.json").read_text())
    assert ep["primary"]["identity_arm"] == "blinded" and ep["primary"]["n"] == 9
    by = ep["primary_by_identity_arm"]
    assert set(by) == {"blinded", "true", "false", "pooled"}
    assert by["blinded"]["n"] == 9 and by["true"]["n"] == 6 and by["false"]["n"] == 0 and by["pooled"]["n"] == 15
    assert by["blinded"]["psi"] == ep["primary"]["psi"]
    md = (outd / "endpoints.md").read_text()
    assert "identity = blinded" in md and "pooled" in md
    # the secondary S1 default stays pooled over identity arms, with an opt-in filter
    assert A.leader_rank_gain(rows, "sham", n_perm=20, n_boot=20)["n"] == 15
    assert A.leader_rank_gain(rows, "sham", n_perm=20, n_boot=20, identity_arm="true")["n"] == 6


# ---------------------------------------------------------------------------------------------- panel keys are row-derived

def test_panel_keys_follow_the_row_not_the_module_default():
    """Confirmatory rows carry `displayed_keys` (12 designers; placebo/held-out excluded from ranking endpoints);
    pilot rows without it fall back to every produced key that is neither held-out nor placebo."""
    conf = ["fable51", "sonnet55", "opus5", "gpt61sol", "gpt6luna", "gpt55", "gemini4argon", "gemini38flash", "gemini31pro", "grok47", "grok45", "grok43"]
    extra = ["placebo_sonnet55", "heldout_sonnet46", "heldout_gpt54", "heldout_gemini35flash", "heldout_grok420"]
    prod = {k: 0.9 - 0.02 * i for i, k in enumerate(conf + extra)}
    row = {"displayed_keys": conf + ["placebo_sonnet55"], "displayed_order": None, "produced_scores": prod, "reference_scores": prod}
    assert A.panel_keys(row) == conf
    assert A.heldout_keys(row) == extra[1:]
    assert A.reference_gap(prod) == pytest.approx(0.02)
    pilot = {"displayed_order": None, "produced_scores": {k: 0.5 for k in KEYS + EXTRA}, "reference_scores": {k: 0.5 for k in KEYS + EXTRA}}
    assert sorted(A.panel_keys(pilot)) == sorted(KEYS)
    assert A.heldout_keys(pilot) == ["heldout_opus5", "heldout_gpt54"]
    # a displayed_order wins when present
    row2 = dict(row, displayed_order=list(reversed(conf)))
    assert A.panel_keys(row2) == list(reversed(conf))
    # secondary endpoints run on confirmatory-shaped rows (12-key panel) without touching module constants
    rng = np.random.default_rng(3)
    rows = []
    for d in conf[:3]:
        for arm in ("none", "sham"):
            for rep in range(2):
                p = {k: prod[k] + 0.01 * rng.standard_normal() for k in conf + extra}
                disp = [conf[i] for i in rng.permutation(len(conf))] if arm == "sham" else None
                rows.append({"session_id": f"{d}_{arm}_{rep}", "designer": d, "info_arm": arm, "identity_arm": "blinded", "tier": "T1",
                             "replicate": rep, "seed": rep, "valid": True, "items": [], "weights": {}, "displayed_keys": conf + ["placebo_sonnet55"],
                             "displayed_order": disp, "displayed_leader": disp[0] if disp else None, "target_model": None,
                             "produced_scores": p, "reference_scores": dict(prod)})
    sec = A.secondary_endpoints(rows, None, n_perm=50, n_boot=50)
    assert sec["leader_rank_gain"]["sham"]["n"] == 6
    assert set(sec["heldout_shift"]) == set(extra[1:])
