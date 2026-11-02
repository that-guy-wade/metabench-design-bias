"""Tests for the blinded health view (scripts_health_view.py) and its checker (scripts_health_check.py).

The fixture below writes a minimal WORK/ tree per docs/ARTEFACT_SCHEMA.md with made-up content; no real session data.
"""
from __future__ import annotations

import importlib
import json
import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import scripts_health_check as hc  # noqa: E402
import scripts_health_view as hv  # noqa: E402

KEYS = hv.panel_keys()
CELLS = hv.load_frozen_cells()
SMALL_CELLS = {c: 1 for c in CELLS}
DESIGNERS = ["fable51", "gpt55", "grok43"]
FORBIDDEN = ["session_id", "designer", "info_arm", "identity_arm", "label_map", "displayed_order", "reference_scores",
             "notes", "config_hash", "seed", "decoy"]


def make_work(root: Path, designers=DESIGNERS, cells=None, seed=7) -> Path:
    """Minimal WORK/ tree: sessions/<id>/{7 files}, monitors/<id>.json, results/{benchmarks,session_log,monitors}.jsonl."""
    cells = CELLS if cells is None else cells
    rnd = random.Random(seed)
    work = root / "WORK"
    (work / "results").mkdir(parents=True)
    (work / "monitors").mkdir()
    t = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)
    benches, log, mons = [], [], []
    sessions = [(d, c, r) for c, n in cells.items() for r in range(n) for d in designers]
    rnd.shuffle(sessions)   # interleaved designers and arms in start order
    for i, (d, cell, r) in enumerate(sessions):
        info, ident = hv.parse_cell(cell)
        sid = f"T1_math_{d}_{info}_{ident}_r{r}"
        sdir = work / "sessions" / sid
        sdir.mkdir(parents=True)
        invalid = i == 3
        start = t + timedelta(minutes=7 * i)
        wall = 300.0 + rnd.random() * 100
        produced = {k: round(rnd.random(), 4) for k in KEYS}
        cfg = {"session_id": sid, "designer": d, "info_arm": info, "identity_arm": ident, "replicate": r, "seed": 1234 + i,
               "label_map": {k: f"MDL-{j:02d}" for j, k in enumerate(KEYS[:13])}, "config_hash": f"h{i:03d}"}
        (sdir / "config.json").write_text(json.dumps(cfg))
        acts = [{"session_id": sid, "round": 1, "t": start.timestamp() + j, "tool": "add_item", "args": {"id": f"P{j}"},
                 "result_summary": "ERROR: no such item" if j == 0 and i % 2 else "Added P%d" % j} for j in range(4)]
        (sdir / "actions.jsonl").write_text("".join(json.dumps(a) + "\n" for a in acts))
        (sdir / "transcript.jsonl").write_text(json.dumps({"t": start.timestamp(), "round": 1, "kind": "system", "payload": "x"}) + "\n")
        if info != "none":
            (sdir / "scores_views.jsonl").write_text(json.dumps({"kind": "numeric", "round": 1, "n_items": 10, "t": 0, "true_all": {}}) + "\n")
        bench = {**cfg, "tier": "T1", "pool_name": "math", "status": "ok", "valid": not invalid, "n_items": 90 if invalid else 100,
                 "items": [f"P{j}" for j in range(4)], "weights": {}, "scoring_rule": "accuracy", "edited_items": {}, "named": False,
                 "displayed_keys": KEYS[:13], "panel_keys": KEYS, "displayed_order": None, "intended_displayed_order": None,
                 "displayed_leader": None, "target_model": None, "n_score_requests": i % 3, "n_edits": i % 2,
                 "produced_scores": produced, "reference_scores": {k: 0.5 for k in KEYS}, "notes": ["[round 1] hi"],
                 "final_notes": "", "presentation_note": "", "monitor_developers": ["google", "xai"], "n_llm_calls": 20 + i,
                 "designer_model_id": d, "designer_effort": "medium", "est_cost_usd": 1.0, "wall_s": wall, "api_errors": 2 if i == 5 else 0,
                 "started_at": start.isoformat().replace("+00:00", "Z"),
                 "ended_at": (start + timedelta(seconds=wall)).isoformat().replace("+00:00", "Z"), "replacement_of": None}
        (sdir / "benchmark.json").write_text(json.dumps(bench))
        benches.append(bench)
        (sdir / "item_outcomes.jsonl").write_text("".join(json.dumps({"session_id": sid, "item_id": f"P{j}", "model_key": k,
                                                                      "n_correct": 1, "n_samples": 5}) + "\n"
                                                          for j in range(4) for k in KEYS))
        if not invalid:
            (sdir / "probes.json").write_text(json.dumps({"recall": "a", "fairness": "b", "self_recognition": "c", "eval_awareness": "d"}))
        mon = {"session_id": sid, "monitor_developers": ["google", "xai"], "n_actions": 4, "monitors": [
            {"developer": "google", "monitor_model": "m1", "status": "ok",
             "artifact": {"evidence_score": 1, "favoured_label": None, "disfavoured_label": None, "rationale": ""},
             "trace": {"evidence_score": 0, "favoured_label": None, "disfavoured_label": None, "steering_actions": [], "rationale": ""}},
            {"developer": "xai", "monitor_model": "m2", "status": "ok",
             "artifact": {"evidence_score": None if i == 2 else 2, "favoured_label": None, "disfavoured_label": None, "rationale": ""},
             "trace": {"evidence_score": 1, "favoured_label": None, "disfavoured_label": None, "steering_actions": [], "rationale": ""}}]}
        (work / "monitors" / f"{sid}.json").write_text(json.dumps(mon))
        mons.append(mon)
        log.append({"session_id": sid, "designer": d, "info_arm": info, "identity_arm": ident, "attempt": 1, "replacement_of": None,
                    "status": "ok", "valid": not invalid, "n_items": bench["n_items"], "api_errors": bench["api_errors"],
                    "n_llm_calls": bench["n_llm_calls"], "wall_s": wall, "started_at": bench["started_at"],
                    "ended_at": bench["ended_at"], "exit_code": 1 if invalid else 0})
    for name, rows in [("benchmarks.jsonl", benches), ("session_log.jsonl", log), ("monitors.jsonl", mons)]:
        (work / "results" / name).write_text("".join(json.dumps(r) + "\n" for r in rows))
    return work


def build(root: Path, seed=b"\x01" * 32, **kw):
    view, secret = root / "health_view.jsonl", root / "health_secret.json"
    summary = hv.build_health_view(root / "WORK", view, secret, run_seed_bytes=seed, **kw)
    rows = [json.loads(line) for line in view.read_text().splitlines()]
    return summary, rows, json.loads(secret.read_text()), view


@pytest.fixture(scope="module")
def work(tmp_path_factory):
    root = tmp_path_factory.mktemp("hv")
    make_work(root)
    return root


@pytest.fixture(scope="module")
def built(work):
    return build(work)


def test_view_rows_have_exact_schema_and_no_forbidden_keys(built):
    _, rows, secret, view = built
    for r in rows:
        assert list(r) == hc.TOP_KEYS
        assert set(r["files"]) == set(hc.FILE_KEYS) | {"monitors"}
        assert set(r["parse"]) == set(hc.PARSE_KEYS)
        assert set(r["scores_shifted"]) == {f"E{i:02d}" for i in range(1, 18)}
        assert hc.row_violations(r) == []
    assert hc.forbidden_keys(rows) == []
    text = view.read_text()
    assert secret["seed_hex"] not in text
    for name in DESIGNERS + KEYS + ["T1_math", "_r0", "rep1"]:
        assert name not in text


def test_counts_per_designer_code_and_total(built):
    summary, rows, _, _ = built
    n_real = len(DESIGNERS) * sum(CELLS.values())
    assert summary == {"n_real": n_real, "n_decoys": 3 * len(DESIGNERS), "n_rows": n_real + 3 * len(DESIGNERS),
                       "n_designers": len(DESIGNERS), "n_cells": 9}
    per = {}
    for r in rows:
        per[r["designer_code"]] = per.get(r["designer_code"], 0) + 1
    assert sorted(per) == [f"D{i:02d}" for i in range(1, len(DESIGNERS) + 1)]
    assert all(n == sum(CELLS.values()) + 3 for n in per.values())
    arm = {}
    for r in rows:
        arm[r["arm_code"]] = arm.get(r["arm_code"], 0) + 1
    assert sorted(arm) == [f"A{i}" for i in range(1, 10)]
    assert sorted(arm.values()) == sorted(len(DESIGNERS) * c + 1 for c in CELLS.values())   # 9 decoys -> 1 per cell
    ident = {(r["arm_code"], r["identity_code"]) for r in rows}
    assert len(ident) == 9 and len({i for _, i in ident}) == 3   # identity code is a function of arm code


def test_decoys_schema_identical_to_real_rows(built):
    _, rows, secret, _ = built
    decoys = {r["view_id"] for r in rows} & set(secret["decoy_view_ids"])
    assert len(decoys) == 3 * len(DESIGNERS)

    def shape(r):
        return json.dumps({k: (type(v).__name__ if not isinstance(v, dict) else {kk: type(vv).__name__ for kk, vv in v.items()})
                           for k, v in r.items()}, sort_keys=True)

    real_shapes = {shape(r) for r in rows if r["view_id"] not in decoys}
    for r in rows:
        if r["view_id"] in decoys:
            assert shape(r) in real_shapes
            assert hc.row_violations(r) == []
            t0, t1 = datetime.fromisoformat(r["started_at"]), datetime.fromisoformat(r["ended_at"])
            assert abs((t1 - t0).total_seconds() - r["wall_s"]) < 1.0
    starts = [datetime.fromisoformat(r["started_at"]) for r in rows]
    real_starts = [datetime.fromisoformat(r["started_at"]) for r in rows if r["view_id"] not in decoys]
    assert min(starts) >= min(real_starts) and max(starts) <= max(real_starts)
    assert len({r["started_at"][-1] for r in rows}) == 1   # same timestamp format (Z) for decoys and real rows


def test_secret_maps_real_rows_and_lists_decoys(work, built):
    _, rows, secret, _ = built
    ids = {r["view_id"] for r in rows}
    mapped = set(secret["view_id_to_session_id"])
    assert mapped.isdisjoint(secret["decoy_view_ids"])
    assert mapped | set(secret["decoy_view_ids"]) == ids
    log = [json.loads(l) for l in (work / "WORK/results/session_log.jsonl").read_text().splitlines()]
    assert sorted(secret["view_id_to_session_id"].values()) == sorted(r["session_id"] for r in log)
    assert set(secret) == {"designer_perm", "cell_perm", "evaluee_perm", "offsets", "decoy_view_ids",
                           "view_id_to_session_id", "seed_hex"}
    assert secret["seed_hex"] == ("01" * 32)
    # structural fields and codes of each real row agree with its session's log row and the secret maps
    by_sid = {r["session_id"]: r for r in log}
    for r in rows:
        sid = secret["view_id_to_session_id"].get(r["view_id"])
        if sid is None:
            continue
        lr = by_sid[sid]
        assert r["designer_code"] == secret["designer_perm"][lr["designer"]]
        cell = secret["cell_perm"][f"{lr['info_arm']}_{lr['identity_arm']}"]
        assert (r["arm_code"], r["identity_code"]) == (cell["arm_code"], cell["identity_code"])
        assert (r["status"], r["valid"], r["exit_code"], r["n_items"], r["api_errors"], r["started_at"], r["ended_at"]) == \
            (lr["status"], lr["valid"], lr["exit_code"], lr["n_items"], lr["api_errors"], lr["started_at"], lr["ended_at"])


def test_scores_shifted_equal_produced_plus_offset_and_codes_permute(work, built):
    _, rows, secret, _ = built
    assert sorted(secret["evaluee_perm"]) == sorted(KEYS)
    assert sorted(secret["evaluee_perm"].values()) == [f"E{i:02d}" for i in range(1, 18)]
    assert all(-0.25 <= v <= 0.25 for v in secret["offsets"].values()) and len(set(secret["offsets"].values())) == 17
    bench = {b["session_id"]: b for b in map(json.loads, (work / "WORK/results/benchmarks.jsonl").read_text().splitlines())}
    n = 0
    for r in rows:
        sid = secret["view_id_to_session_id"].get(r["view_id"])
        if sid is None:
            continue
        for k in KEYS:
            assert r["scores_shifted"][secret["evaluee_perm"][k]] == bench[sid]["produced_scores"][k] + secret["offsets"][k]
        n += 1
    assert n == len(bench)


def test_parse_and_files_flags_come_from_session_files(work, built):
    _, rows, secret, _ = built
    inv = {secret["view_id_to_session_id"][v]: v for v in secret["view_id_to_session_id"]}
    by_vid = {r["view_id"]: r for r in rows}
    log = [json.loads(l) for l in (work / "WORK/results/session_log.jsonl").read_text().splitlines()]
    for i, lr in enumerate(log):
        r = by_vid[inv[lr["session_id"]]]
        assert r["parse"]["actions_ok_rate"] == (0.75 if i % 2 else 1.0)
        assert r["parse"]["monitor_json_rate"] == (0.75 if i == 2 else 1.0)
        assert r["parse"]["item_outcomes_rows"] == 4 * 17
        assert r["files"]["monitors"] == 2 and r["files"]["probes"] == (i != 3)
        assert r["files"]["scores_views"] == (not lr["info_arm"] == "none")


def test_registered_hashes_and_flag_overrides(work, tmp_path):
    log = [json.loads(l) for l in (work / "WORK/results/session_log.jsonl").read_text().splitlines()]
    bench = [json.loads(l) for l in (work / "WORK/results/benchmarks.jsonl").read_text().splitlines()]
    registered = {"sessions": [{"session_id": b["session_id"], "config_hash": b["config_hash"]} for b in bench[1:]]}
    registered["sessions"][0]["config_hash"] = "mismatch"
    _, rows, secret, _ = _build_in(work, tmp_path, registered=registered, code_hash_ok=False,
                                   hash_ok_by_session={bench[2]["session_id"]: False})
    sid_of = secret["view_id_to_session_id"]
    bad = {sid_of[r["view_id"]] for r in rows if r["view_id"] in sid_of and not r["hash_ok"]}
    assert bad == {bench[0]["session_id"], bench[1]["session_id"], bench[2]["session_id"]}   # unregistered, mismatch, override
    assert all(r["code_hash_ok"] is False for r in rows)   # decoys follow the run's code flag too
    assert all(r["hash_ok"] for r in rows if r["view_id"] not in sid_of)
    assert len(log) == len(sid_of)


def _build_in(work: Path, out: Path, **kw):
    view, secret = out / "v.jsonl", out / "s.json"
    hv.build_health_view(work / "WORK", view, secret, run_seed_bytes=b"\x02" * 32, **kw)
    rows = [json.loads(line) for line in view.read_text().splitlines()]
    return None, rows, json.loads(secret.read_text()), view


def test_seed_determinism_and_difference(work, tmp_path):
    a = tmp_path / "a"; b = tmp_path / "b"; c = tmp_path / "c"
    for d in (a, b, c):
        d.mkdir()
    hv.build_health_view(work / "WORK", a / "v.jsonl", a / "s.json", run_seed_bytes=b"\x05" * 32)
    hv.build_health_view(work / "WORK", b / "v.jsonl", b / "s.json", run_seed_bytes=b"\x05" * 32)
    hv.build_health_view(work / "WORK", c / "v.jsonl", c / "s.json", run_seed_bytes=b"\x06" * 32)
    assert (a / "v.jsonl").read_bytes() == (b / "v.jsonl").read_bytes()
    assert (a / "s.json").read_bytes() == (b / "s.json").read_bytes()
    sa, sc = json.loads((a / "s.json").read_text()), json.loads((c / "s.json").read_text())
    assert sa["evaluee_perm"] != sc["evaluee_perm"] and sa["offsets"] != sc["offsets"]
    assert sa["designer_perm"] != sc["designer_perm"] or sa["cell_perm"] != sc["cell_perm"]
    assert (a / "v.jsonl").read_bytes() != (c / "v.jsonl").read_bytes()
    # default seed: os.urandom -> different every time
    d = tmp_path / "d"; d.mkdir()
    hv.build_health_view(work / "WORK", d / "v.jsonl", d / "s.json")
    assert json.loads((d / "s.json").read_text())["seed_hex"] not in (sa["seed_hex"], sc["seed_hex"])


def test_checker_passes_valid_view(built):
    _, rows, _, _ = built
    rep = hc.check(rows, cells=CELLS, n_designers=len(DESIGNERS), decoys_per_designer=3)
    assert rep["refused"] is False and rep["passed"] is True
    assert rep["schema"]["n_violations"] == 0
    assert rep["counts"]["designer_codes_short"] == [] and rep["counts"]["arm_counts_match_registered_multiset"]
    assert rep["validity"]["n_invalid"] == 1 and rep["validity"]["by_exit_code"] == {"0": len(rows) - 1, "1": 1}
    assert rep["api_failures"]["rows_with_api_errors"] == 1 and rep["api_failures"]["api_errors_max"] == 2
    assert rep["hash_flags"] == {"rows_hash_ok_false": 0, "rows_code_hash_ok_false": 0}
    assert rep["parse"]["actions_ok_rate"]["min"] == 0.75 and rep["parse"]["item_outcomes_rows"]["max"] == 68
    assert hc.markdown(rep).startswith("| check | value |")


def test_checker_refuses_forbidden_key(built):
    _, rows, _, _ = built
    for key in FORBIDDEN + ["is_decoy", "seed_hex"]:
        bad = [dict(r) for r in rows]
        bad[0][key] = "x"
        rep = hc.check(bad, cells=CELLS, n_designers=len(DESIGNERS))
        assert rep == {"refused": True, "forbidden_keys": [key]}
    nested = [json.loads(json.dumps(r)) for r in rows]
    nested[1]["files"]["session_id"] = "x"
    assert hc.check(nested, cells=CELLS)["forbidden_keys"] == ["session_id"]


def test_checker_reports_designer_shortfall_and_schema_violation(built):
    _, rows, _, _ = built
    short = [r for r in rows if not (r["designer_code"] == "D02" and r["arm_code"] == "A3")]
    rep = hc.check(short, cells=CELLS, n_designers=len(DESIGNERS), decoys_per_designer=3)
    assert rep["passed"] is False
    assert rep["counts"]["designer_codes_short"] == ["D02"]
    assert rep["counts"]["per_designer_code"]["D02"]["diff"] == -(len(rows) - len(short))
    assert rep["counts"]["arm_counts_match_registered_multiset"] is False
    # a missing designer code shows up with n = 0
    rep12 = hc.check(rows, cells=CELLS, n_designers=12)
    assert rep12["counts"]["per_designer_code"]["D12"] == {"n": 0, "expected_without_replacements": 42, "diff": -42}
    # schema violation: wrong type and an extra key
    broken = [json.loads(json.dumps(r)) for r in rows]
    broken[0]["n_items"] = "100"
    broken[1]["parse"]["extra"] = 1
    rep = hc.check(broken, cells=CELLS, n_designers=len(DESIGNERS))
    assert rep["schema"]["n_violations"] == 2 and rep["passed"] is False


def test_checker_timing_report(built):
    _, rows, _, _ = built
    t = hc.check(rows, cells=CELLS, n_designers=len(DESIGNERS))["timing"]
    assert set(t["per_arm_code"]) == {f"A{i}" for i in range(1, 10)}
    for a in t["per_arm_code"].values():
        assert set(a) == {"n", "start_hour_min", "start_hour_median", "start_hour_max"}
        assert 0 <= a["start_hour_min"] <= a["start_hour_median"] <= a["start_hour_max"] < 24
    assert 0.0 <= t["kruskal_wallis_p_value_start_time"] <= 1.0
    assert 0.0 < t["arm_code_switch_share"] <= 1.0
    # blocked arms (one arm after another) -> tiny p-value and low switch share
    blocked = sorted(rows, key=lambda r: r["arm_code"])
    base = datetime(2026, 11, 2, tzinfo=timezone.utc)
    for i, r in enumerate(blocked):
        r = dict(r); blocked[i] = r
        r["started_at"] = (base + timedelta(minutes=5 * i)).isoformat()
        r["ended_at"] = (base + timedelta(minutes=5 * i + 4)).isoformat()
    tb = hc.check(blocked, cells=CELLS, n_designers=len(DESIGNERS))["timing"]
    assert tb["kruskal_wallis_p_value_start_time"] < 1e-6 and tb["arm_code_switch_share"] < 0.1


def test_checker_output_has_no_score_like_keys(built):
    _, rows, _, _ = built
    rep = hc.check(rows, cells=CELLS, n_designers=len(DESIGNERS))
    names = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                names.append(k); walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(rep)
    # "scores_views" is the per-session FILE name (ARTEFACT_SCHEMA section 1); only its presence count is reported
    assert not [k for k in names if k != "scores_views"
                and any(s in k.lower() for s in ("score", "rank", "tau", "mean_score", "evaluee", "e01"))]
    assert isinstance(rep["parse"]["files_present"]["scores_views"], int)
    assert not [k for k in names if k.startswith("E") and k[1:].isdigit()]


def test_cli_round_trip(work, tmp_path):
    env = {"PYTHONDONTWRITEBYTECODE": "1"}
    view, secret = tmp_path / "hv.jsonl", tmp_path / "hs.json"
    r = subprocess.run([sys.executable, str(ROOT / "scripts_health_view.py"), "--work", str(work / "WORK"), "--view", str(view),
                        "--secret", str(secret)], capture_output=True, text=True, cwd=tmp_path, env=env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["n_decoys"] == 3 * len(DESIGNERS)
    r = subprocess.run([sys.executable, str(ROOT / "scripts_health_check.py"), "--view", str(view), "--n-designers", str(len(DESIGNERS))],
                       capture_output=True, text=True, cwd=tmp_path, env=env)
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert rep["passed"] is True and "| passed | True |" in r.stderr
    # a forbidden key -> exit 2
    bad = tmp_path / "bad.jsonl"
    rows = [json.loads(l) for l in view.read_text().splitlines()]
    rows[0]["session_id"] = "leak"
    bad.write_text("".join(json.dumps(x) + "\n" for x in rows))
    r = subprocess.run([sys.executable, str(ROOT / "scripts_health_check.py"), "--view", str(bad)], capture_output=True, text=True, cwd=tmp_path, env=env)
    assert r.returncode == 2 and json.loads(r.stdout)["forbidden_keys"] == ["session_id"]


def test_decoy_sources_rows(work, tmp_path):
    src = [{"status": "ok", "valid": True, "n_items": 100, "n_llm_calls": 33, "api_errors": 0, "wall_s": 123.0,
            "n_score_requests": 2, "n_edits": 1,
            "files": {k: True for k in hc.FILE_KEYS} | {"monitors": 2},
            "parse": {"actions_ok_rate": 0.9, "monitor_json_rate": 1.0, "item_outcomes_rows": 1700}}]
    _, rows, secret, _ = _build_in(work, tmp_path, decoy_sources=src, decoys_per_designer=2)
    dec = [r for r in rows if r["view_id"] in secret["decoy_view_ids"]]
    assert len(dec) == 2 * len(DESIGNERS)
    assert all(r["n_llm_calls"] == 33 and r["wall_s"] == 123.0 and r["exit_code"] == 0 for r in dec)
    assert all(hc.row_violations(r) == [] for r in dec)
    # scores near reference-like values + offset: within 0.25 + 5 sigma of the real mean per code
    real = [r for r in rows if r["view_id"] not in secret["decoy_view_ids"]]
    for code in dec[0]["scores_shifted"]:
        m = sum(r["scores_shifted"][code] for r in real) / len(real)
        assert all(abs(r["scores_shifted"][code] - m) < 0.1 for r in dec)


def test_synthetic_generator_output(tmp_path):
    try:
        synthetic = importlib.import_module("metabench.synthetic")
    except ImportError:
        pytest.skip("metabench/synthetic.py not present")
    if not hasattr(synthetic, "generate"):
        pytest.skip("metabench.synthetic.generate not present")
    out = tmp_path / "SYN"
    synthetic.generate(out, seed=1)
    view, secret = tmp_path / "v.jsonl", tmp_path / "s.json"
    summary = hv.build_health_view(out, view, secret, run_seed_bytes=b"\x09" * 32)
    rows = [json.loads(l) for l in view.read_text().splitlines()]
    assert summary["n_rows"] == len(rows) == summary["n_real"] + summary["n_decoys"]
    assert hc.forbidden_keys(rows) == []
    rep = hc.check(rows, n_designers=summary["n_designers"])
    assert rep["refused"] is False and rep["schema"]["n_violations"] == 0



def test_checker_accounts_for_declared_replacements(built):
    """A replacement attempt adds one row to its designer and cell: the view passes only when the replacement is
    declared (prereg/confirmatory_replacements_<pool>.json), and fails when it is not."""
    _, rows, _secret, _view = built
    extra = dict(rows[0]); extra["view_id"] = "HV-9999"
    with_rep = rows + [extra]
    # recover the real designer / cell of that row through the secret (the test may; the checker may not)
    inv_d = {v: k for k, v in _secret["designer_perm"].items()}
    inv_c = {(v["arm_code"], v["identity_code"]): k for k, v in _secret["cell_perm"].items()}
    cell = inv_c[(extra["arm_code"], extra["identity_code"])]
    info, ident = cell.rsplit("_", 1)
    decl = [{"designer": inv_d[extra["designer_code"]], "info_arm": info, "identity_arm": ident}]
    rep_ok = hc.check(with_rep, cells=CELLS, n_designers=len(DESIGNERS), decoys_per_designer=3, replacements=decl)
    assert rep_ok["passed"] is True and rep_ok["counts"]["n_replacements_declared"] == 1
    rep_bad = hc.check(with_rep, cells=CELLS, n_designers=len(DESIGNERS), decoys_per_designer=3)
    assert rep_bad["passed"] is False and rep_bad["counts"]["designer_counts_match_multiset"] is False
