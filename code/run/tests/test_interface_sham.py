"""Sham/inverted display mechanics (PREREGISTRATION section 4): the FIRST numeric view shows the reference vector in
the registered order sigma whatever the draft's true scores are; later views move with the draft's true scores by
exactly the fixed offsets; the exported displayed_order equals the registered order."""
import asyncio
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from metabench import panel  # noqa: E402
from metabench.arms import make_session_config  # noqa: E402
from metabench.interface import T1Interface  # noqa: E402
from metabench.scoring import reference_scores  # noqa: E402


def _world(seed=0, n_pool=120, k=3):
    panel.set_active("confirmatory")
    rng = np.random.default_rng(seed)
    keys = panel.all_panel_keys()
    pool = {f"P{i:04d}": {"id": f"P{i:04d}", "category": ["a", "b", "c"][i % 3], "question": f"q{i}", "options": ["1", "2", "3", "4"], "answer": "A"} for i in range(n_pool)}
    p_model = {m: 0.35 + 0.03 * j for j, m in enumerate(keys)}
    corr = {(i, m): [int(rng.random() < p_model[m] + 0.3 * rng.standard_normal()) for _ in range(k)] for i in pool for m in keys}
    ref = reference_scores(list(pool), keys, corr)
    return pool, corr, ref


@pytest.mark.parametrize("arm", ["sham", "inverted"])
def test_first_view_shows_registered_order_and_later_views_track_truth(tmp_path, arm):
    pool, corr, ref = _world()
    cfg = make_session_config(f"t_{arm}", "grok43", arm, "blinded", 0, 4242, ref, n_items_required=100, with_monitors=True)
    iface = T1Interface(cfg, pool, corr, tmp_path / "s", reference=ref)
    iface.round = 1
    ids = sorted(pool)
    # a small, noisy draft: its true order differs from the reference order
    asyncio.run(iface.handle_tool("add_items", {"ids": ids[:12]}))
    true1 = iface.true_scores()
    assert sorted(cfg.displayed_keys, key=lambda m: -true1[m]) != sorted(cfg.displayed_keys, key=lambda m: -ref[m])
    asyncio.run(iface.handle_tool("request_panel_scores", {}))
    v1 = iface.scores_views[-1]
    assert v1["order"] == cfg.displayed_order                      # exactly sigma, despite the noisy draft
    # the displayed values are the reference vector permuted to sigma (up to the 1e-6 tie-breaker and rounding)
    ref_desc = sorted((ref[m] for m in cfg.displayed_keys), reverse=True)
    assert [v1["shown"][m] for m in cfg.displayed_order] == pytest.approx(ref_desc, abs=2e-4)
    # second view after edits: shown moves by exactly the change in true scores (offsets fixed at the first view)
    asyncio.run(iface.handle_tool("add_items", {"ids": ids[12:40]}))
    asyncio.run(iface.handle_tool("request_panel_scores", {}))
    v2 = iface.scores_views[-1]
    true2 = iface.true_scores()
    for m in cfg.displayed_keys:
        expect = min(1.0, max(0.0, true2[m] + v1["offsets_applied"][m]))
        assert v2["shown"][m] == pytest.approx(expect, abs=2e-4)
    assert v2["offsets_applied"] == v1["offsets_applied"]
    row = iface.export(ref)
    assert row["displayed_order"] == cfg.displayed_order and row["offsets_applied"] == v1["offsets_applied"]


def test_without_reference_the_registered_offsets_are_used(tmp_path):
    """Legacy path (pilot scripts construct the interface without a reference): unchanged behaviour."""
    pool, corr, ref = _world(1)
    cfg = make_session_config("t_legacy", "grok43", "sham", "blinded", 0, 7, ref)
    iface = T1Interface(cfg, pool, corr, tmp_path / "s")
    iface.round = 1
    asyncio.run(iface.handle_tool("add_items", {"ids": sorted(pool)[:10]}))
    asyncio.run(iface.handle_tool("request_panel_scores", {}))
    v = iface.scores_views[-1]
    true = iface.true_scores()
    assert "offsets_applied" not in v
    for m in cfg.displayed_keys:
        assert v["shown"][m] == pytest.approx(min(1.0, max(0.0, true[m] + cfg.offsets[m])), abs=2e-4)


def test_true_arms_unaffected(tmp_path):
    pool, corr, ref = _world(2)
    cfg = make_session_config("t_true", "grok43", "true_blinded", "blinded", 0, 9, ref)
    iface = T1Interface(cfg, pool, corr, tmp_path / "s", reference=ref)
    iface.round = 1
    asyncio.run(iface.handle_tool("add_items", {"ids": sorted(pool)[:10]}))
    asyncio.run(iface.handle_tool("request_panel_scores", {}))
    v = iface.scores_views[-1]
    true = iface.true_scores()
    assert "offsets_applied" not in v and all(v["shown"][m] == pytest.approx(true[m], abs=2e-4) for m in cfg.displayed_keys)
