"""The precompute-estimate summariser reads only safe fields: it never emits correctness or predictions."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scripts_precompute_estimate as E  # noqa: E402
from metabench import panel  # noqa: E402


def test_summary_and_estimate_carry_no_correctness_or_predictions():
    panel.set_active("confirmatory")
    recs, calls = [], []
    for m in ("fable51", "grok43", "gemini38flash"):
        for i in range(4):
            recs.append({"item": f"M{i}", "model": m, "sample": 0, "pred": "SECRET-PRED", "correct": 1, "parsed": int(i != 3),
                         "grade": "exact", "grade_error": "boom" if i == 2 else None, "grade_s": 0.5, "in": 100, "out": 50, "stop": "end_turn", "text_tail": "SECRET"})
            calls.append({"t": 0, "tag": f"panel:{m}", "model": "x", "in": 100, "out": 50, "cost": 0.001, "latency": 2.0, "stop": "end_turn"})
    s = E.summarise(recs, calls)
    txt = json.dumps(s) + json.dumps(E.extrapolate(s, 4, 1)) + E.render("math", 4, s, 10.0, E.extrapolate(s, 4, 1))
    assert "SECRET" not in txt and "correct" not in txt and "pred" not in txt
    assert s["parse_failures"] == 3 and s["grader_errors"] == 3 and s["per_model"]["grok43"]["calls"] == 4
    est = E.extrapolate(s, 4, 1)
    assert est["calls_full"] == 3 * 10000 and abs(est["cost_usd"] - 3 * 0.001 * 10000) < 1e-6
    assert est["api_wall_s_by_provider"]["openai"] if "openai" in est["api_wall_s_by_provider"] else True
    assert est["api_wall_s_by_provider"]["xai"] == 10000 * 2.0 / 32
