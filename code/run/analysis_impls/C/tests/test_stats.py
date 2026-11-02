import numpy as np
from scipy.stats import kendalltau

from cimpl.stats import bh_reject, holm, pair_signs, ranks, rbo_ext, tau_b, tau_b_vectorised


def test_tau_b_vectorised_matches_scipy():
    rng = np.random.default_rng(0)
    x = rng.random(13)
    x[3] = x[7]                                           # a tie in the produced scores
    perms = np.argsort(rng.random((50, 13)), axis=1)
    pos = np.argsort(perms, axis=1)
    mine = tau_b_vectorised(x, pos)
    for p in range(50):
        ref = kendalltau(x, -pos[p], variant="b").statistic
        assert abs(mine[p] - ref) < 1e-12


def test_tau_b_dict_version_and_ranks():
    scores = {"a": 0.9, "b": 0.8, "c": 0.7, "d": 0.7}
    assert tau_b(scores, ["a", "b", "c", "d"]) > 0.9
    assert tau_b(scores, ["d", "c", "b", "a"]) < -0.9
    r = ranks(scores, ["a", "b", "c", "d"])
    assert r["a"] == 1 and r["b"] == 2 and r["c"] == 3.5 and r["d"] == 3.5


def test_rbo_bounds():
    s = list("abcdefghijklm")
    assert abs(rbo_ext(s, s, 0.8) - 1.0) < 1e-12
    assert 0 < rbo_ext(s, s[::-1], 0.8) < 0.5
    assert rbo_ext(s, s[::-1], 0.8) < rbo_ext(s, s[1:] + s[:1], 0.8)


def test_holm_and_bh():
    h = holm({"S1": 0.01, "S2": 0.04, "S3": 0.03, "S4": 0.2})
    assert h["S1"]["p_holm"] == 0.04 and h["S1"]["reject_at_0.05"]
    assert h["S3"]["p_holm"] == 0.09 and not h["S3"]["reject_at_0.05"]
    assert h["S4"]["p_holm"] == 0.2
    rej = bh_reject(np.array([0.001, 0.02, 0.03, 0.5, 0.9]), 0.05)
    assert rej.tolist() == [True, True, True, False, False]
    assert len(pair_signs(np.arange(5))) == 10
