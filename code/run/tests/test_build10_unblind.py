"""Builder 10: scripts_unblind.py on synthetic data only.

Three per-pool WORK trees in the runner's layout (metabench.synthetic + the runner's registration / manifest shapes,
prereg files written like Runner.cmd_register, endpoints written by Runner.run_analyses / run_contamination) are merged
into one "unsealed" tree the way the Sealer did: per-pool paths kept, pool-level paths overwritten by each later pool
(factual, math, code), a MANIFEST.json with plaintext_bytes.  The code pool's results rows are shuffled first (the
runner appended rows in completion order).  scripts_unblind.main then rebuilds, checks and analyses each pool.

The equality helper `differences` is also applied to a naive rebuild (every pool takes the pool-level files from
unsealed/) and must report differences there, so these assertions fail on a naive rebuild.
"""
from __future__ import annotations

import hashlib
import json
import random
import shutil
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402
sys.path.insert(0, str(ROOT))
import scripts_runner as R  # noqa: E402
import scripts_unblind as U  # noqa: E402
from metabench import panel, synthetic  # noqa: E402
from metabench.arms import make_session_config  # noqa: E402

SEEDS = {"factual": 1101, "math": 2202, "code": 3303}
CELLS = {"sham_blinded": 2, "none_blinded": 2, "true_named_true": 1, "true_blinded_blinded": 1, "sham_true": 1, "sham_false": 1,
         "inverted_blinded": 1, "narrative_blinded": 1, "instructed_blinded": 1}
SIZE = dict(n_designers=4, n_pool=60, n_items=24, samples_per_item=3, invalid_rate=0.15)
N = "12"                      # --n-perm / --n-boot for every analysis in these tests
IMPLS = ("A_metabench_analysis", "B", "C")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_jsonl(p: Path, rows) -> None:
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))


def synthetic_make_cfg(row, ref, pool_name, n_items, k_rounds, samples, suffix=""):
    """scripts_runner.make_cfg with the synthetic generator's seeds and pool description (the registered master seed is
    refused by the generator)."""
    sid = row["session_id"] + (f"_{suffix}" if suffix else "")
    seed = synthetic.session_seed(SEEDS[pool_name], row["designer"], row["info_arm"], row["identity_arm"], row["replicate"], suffix or None)
    return make_session_config(sid, row["designer"], row["info_arm"], row["identity_arm"], row["replicate"], seed, ref, k_rounds=k_rounds,
                               n_items_required=n_items, samples_per_item=samples, pool_name=pool_name,
                               pool_description=synthetic.POOL_DESCRIPTION, with_monitors=True)


def runner_layout(work: Path, pool: str, prereg: Path, pools_dir: Path, n_perm: str) -> Path:
    """Turn a synthetic tree into the runner's WORK just before finish(), write the prereg files, run the analyses the way
    Runner.finish does (endpoints/ inside WORK).  Returns the pool file path."""
    pool_file = pools_dir / f"{pool}.jsonl"       # + the contamination fields of the real pools (pools/SCHEMA.md)
    items = U.read_jsonl(work / "pool" / f"{pool}.jsonl")
    for n, it in enumerate(items):
        it["source_date"] = f"{2019 + n % 7}-0{1 + n % 9}-15"
        it["post_cutoff_by_developer"] = {d: n % 7 >= 5 for d in panel.DEVELOPERS}
    write_jsonl(pool_file, items)
    shutil.rmtree(work / "pool")                                  # the real run hashes the pool instead
    syn = json.loads((work / "registration_full.json").read_text())
    bench = U.read_jsonl(work / "results" / "benchmarks.jsonl")
    sessions = syn["registration"]["sessions"]
    reg = {"written_at": "2026-11-01T00:00:00Z", "master_seed": SEEDS[pool], "pool_name": pool, "pool_sha256": sha(pool_file),
           "panel_correctness_sha256": sha(work / "precompute" / f"{pool}.jsonl"), "samples_per_item": SIZE["samples_per_item"],
           "k_rounds": 4, "n_items": SIZE["n_items"], "cells": CELLS, "designers": syn["registration"]["designers"]}
    if pool == "code":
        reg["live_rescore_wait_s"] = 900.0
    reg.update({"frozen_code_sha256": "synthetic", "frozen_code_verified": True,
                "panel": [{"key": s.key, "provider": s.provider, "model_id": s.model_id, "effort": s.effort} for s in panel.PANEL],
                "sessions": sessions})
    reg["sessions_sha256"] = hashlib.sha256(json.dumps(reg["sessions"], sort_keys=True).encode()).hexdigest()
    (prereg / f"confirmatory_hashes_{pool}.json").write_text(json.dumps(reg, indent=1))
    by_id = {b["session_id"]: b for b in bench}
    repl = [{"original": b["replacement_of"], "replacement": b["session_id"], "designer": b["designer"], "info_arm": b["info_arm"],
             "identity_arm": b["identity_arm"], "reason": by_id[b["replacement_of"]]["status"], "config_hash": b["config_hash"]}
            for b in bench if b.get("replacement_of")]
    assert repl, "the fixture needs replacements"
    (prereg / f"confirmatory_replacements_{pool}.json").write_text(json.dumps({"written_at": "x", "pool_name": pool, "replacements": repl}, indent=1))
    registered = {s["session_id"] for s in sessions}
    full = {"registration": reg, "configs": {k: v for k, v in syn["configs"].items() if k in registered},
            "reference_scores": syn["reference_scores"], "coverage": syn["coverage"]}
    (work / "registration_full.json").write_text(json.dumps(full, indent=1))
    # monitors only for status ok with items (Runner.run_many); the generator writes one for every session
    keep = {b["session_id"] for b in bench if b["status"] == "ok" and b["items"]}
    for p in (work / "monitors").iterdir():
        if p.stem not in keep:
            p.unlink()
    write_jsonl(work / "results" / "monitors.jsonl", [m for m in U.read_jsonl(work / "results" / "monitors.jsonl") if m["session_id"] in keep])
    pan = {"name": "confirmatory", "keys": [s.key for s in panel.PANEL], "displayed_keys": list(panel.DISPLAYED_KEYS),
           "placebo_keys": list(panel.PLACEBO_KEYS), "heldout_keys": list(panel.HELDOUT_KEYS)}
    manifest = {"run_id": f"{pool}-2026-11-01T00:00:00Z", "started_at": "2026-11-01T00:00:00Z", "frozen_code_sha256": "synthetic",
                "registration_sha256": reg["sessions_sha256"], "pool_sha256": reg["pool_sha256"], "n_registered": len(sessions),
                "designers": reg["designers"], "cells": CELLS, "concurrency": 16, "live_rescore_wait_s": reg.get("live_rescore_wait_s"),
                "panel": pan["keys"] if pool == "factual" else pan,     # the factual manifest predates BUILD4: a plain list
                "substitutes": {}, "ended_at": "2026-11-02T00:00:00Z", "n_rows": len(bench), "n_valid": sum(b["valid"] for b in bench),
                "api_errors_total": 7}
    (work / "run_manifest.json").write_text(json.dumps(manifest, indent=1))
    if pool == "code":            # completion order: every results file in one shuffled session order (same lock block)
        rnd = random.Random(7)
        perm = [b["session_id"] for b in bench]
        rnd.shuffle(perm)
        rank = {s: i for i, s in enumerate(perm)}
        for name in ("benchmarks.jsonl", "item_outcomes.jsonl", "monitors.jsonl", "session_log.jsonl"):
            rows = U.read_jsonl(work / "results" / name)
            write_jsonl(work / "results" / name, sorted(rows, key=lambda r: rank[r["session_id"]]))
    a = R.build_parser().parse_args(["run", "--pool", str(pool_file), "--pool-name", pool, "--samples", str(SIZE["samples_per_item"]),
                                     "--work-dir", str(work), "--allow-non-tmpfs", "--n-perm", n_perm, "--n-boot", n_perm,
                                     "--designers", ",".join(reg["designers"])])
    r = R.Runner(a)
    r.run_analyses()
    r.run_contamination()
    return pool_file


def merge_like_sealer(trees: dict[str, Path], unsealed: Path) -> None:
    """Every file of each pool's WORK at its relative path, later pools overwriting earlier ones; MANIFEST.json."""
    files = {}
    for pool in ("factual", "math", "code"):
        for p in sorted(trees[pool].rglob("*")):
            if p.is_file():
                rel = str(p.relative_to(trees[pool]))
                dst = unsealed / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, dst)
                files[rel] = {"ciphertext_sha256": "0" * 64, "plaintext_bytes": dst.stat().st_size, "sealed_at": "2026-11-01T00:00:00Z"}
    (unsealed / "MANIFEST.json").write_text(json.dumps({"files": files, "recipient_fingerprint": "SYNTHETIC"}, indent=1, sort_keys=True))


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    # one analysis environment for the originals and the rebuilt trees: A's intervals depend on the string-hash seed
    # (scripts_unblind.child_env) and multi-threaded BLAS reductions are not bit-reproducible
    env = pytest.MonkeyPatch()
    for k, v in (("PYTHONHASHSEED", "0"), ("OPENBLAS_NUM_THREADS", "1"), ("OMP_NUM_THREADS", "1"), ("MKL_NUM_THREADS", "1")):
        env.setenv(k, v)
    base = tmp_path_factory.mktemp("b10")
    prereg, pools_dir = base / "prereg", base / "pools"
    prereg.mkdir(); pools_dir.mkdir()
    shutil.copy(ROOT / "prereg" / "sealing_key.json", prereg / "sealing_key.json")
    trees, pool_files = {}, {}
    for pool in ("factual", "math", "code"):
        w = base / "orig" / pool
        synthetic.generate(w, seed=SEEDS[pool], pool_name=pool, sessions_per_designer=CELLS, **SIZE)
        pool_files[pool] = runner_layout(w, pool, prereg, pools_dir, N)
        trees[pool] = w
    unsealed = base / "unsealed"
    merge_like_sealer(trees, unsealed)
    yield {"base": base, "prereg": prereg, "pool_files": pool_files, "trees": trees, "unsealed": unsealed}
    env.undo()


def argv(world, unsealed: Path, out: Path, *extra: str) -> list[str]:
    return ["--unsealed", str(unsealed), "--prereg", str(world["prereg"]), "--out", str(out), "--n-perm", N, "--n-boot", N,
            *[x for p, f in world["pool_files"].items() for x in ("--pool-file", f"{p}={f}")], *extra]


@pytest.fixture(scope="module")
def unblinded(world):
    mp = pytest.MonkeyPatch()
    mp.setattr(R, "make_cfg", synthetic_make_cfg)
    mp.chdir(ROOT)
    out = world["base"] / "out"
    try:
        rc = U.main(argv(world, world["unsealed"], out, "--jobs", "6"))
    finally:
        mp.undo()
    return {"rc": rc, "out": out, "summary": json.loads((out / "unblind_summary.json").read_text())}


# ------------------------------------------------------------------------------------------------- equality helper

def _rows(p: Path) -> Counter:
    return Counter(U.canon(r) for r in U.read_jsonl(p))


def differences(rebuilt: Path, original: Path) -> list[str]:
    """Every file the analyses read (ARTEFACT_SCHEMA section 1 / analysis_impls loaders): results/*.jsonl as row multisets
    (A reads its rows in file order; row order is tested separately), the reference outcomes in both places, the
    sessions/ tree byte for byte, registration_full.json, the manifest's displayed keys, monitors and precompute."""
    out = []
    for name in U.RESULTS_FILES:
        if _rows(rebuilt / "results" / name) != _rows(original / "results" / name):
            out.append(f"results/{name}")
    if (rebuilt / "reference_item_outcomes.jsonl").read_bytes() != (original / "reference_item_outcomes.jsonl").read_bytes():
        out.append("reference_item_outcomes.jsonl")
    for sub in ("sessions", "monitors", "precompute"):
        a = {str(p.relative_to(rebuilt)): p.read_bytes() for p in (rebuilt / sub).rglob("*") if p.is_file()}
        b = {str(p.relative_to(original)): p.read_bytes() for p in (original / sub).rglob("*") if p.is_file()}
        if a != b:
            out.append(sub)
    ra, rb = (json.loads((t / "registration_full.json").read_text()) for t in (rebuilt, original))
    if ra != rb:
        out.append("registration_full.json")
    ma, mb = (json.loads((t / "run_manifest.json").read_text())["panel"] for t in (rebuilt, original))
    if ma != mb:                    # C reads the panel (its shape decides C's designer-key order)
        out.append("run_manifest.json panel")
    return out


def naive_rebuild(unsealed: Path, pool: str, dest: Path) -> Path:
    """What the sealing defect invites: the pool's own sessions/monitors/precompute plus the pool-level files as found."""
    dest.mkdir(parents=True)
    for rel in ["registration_full.json", "run_manifest.json", "reference_item_outcomes.jsonl", "results"]:
        src = unsealed / rel
        (shutil.copytree if src.is_dir() else shutil.copy)(src, dest / rel)
    for sub, pat in (("sessions", f"T1_{pool}_*"), ("monitors", f"T1_{pool}_*"), ("precompute", f"{pool}.jsonl")):
        (dest / sub).mkdir(parents=True, exist_ok=True)
        for p in (unsealed / sub).glob(pat):
            (shutil.copytree if p.is_dir() else shutil.copy)(p, dest / sub / p.name)
    return dest


# ------------------------------------------------------------------------------------------------- tests

def test_rebuilt_trees_equal_the_originals(world, unblinded):
    assert unblinded["rc"] == 0
    for pool in ("factual", "math", "code"):
        assert differences(unblinded["out"] / f"WORK_{pool}", world["trees"][pool]) == [], pool
    for pool in ("factual", "math"):     # registered list then replacements: the generator's (and the runner's plan) order, byte for byte
        for name in U.RESULTS_FILES:
            assert (unblinded["out"] / f"WORK_{pool}" / "results" / name).read_bytes() == (world["trees"][pool] / "results" / name).read_bytes(), (pool, name)
    m = json.loads((unblinded["out"] / "WORK_code" / "run_manifest.json").read_text())
    assert m["live_rescore_wait_s"] == 900.0 and isinstance(m["panel"], dict)
    assert json.loads((unblinded["out"] / "WORK_factual" / "run_manifest.json").read_text())["panel"] == [s.key for s in panel.PANEL]
    assert json.loads((unblinded["out"] / "WORK_math" / "run_manifest.json").read_text())["live_rescore_wait_s"] is None
    facts = unblinded["summary"]["facts"]
    for pool, f in facts.items():
        assert f["warnings"] == [], (pool, f["warnings"])
        assert f["declared_replacements"] > 0 and f["rows"] == f["registered"] + f["declared_replacements"]


def test_naive_rebuild_fails_the_same_assertions(world, tmp_path):
    for pool in ("factual", "math"):
        d = differences(naive_rebuild(world["unsealed"], pool, tmp_path / pool), world["trees"][pool])
        assert {"results/benchmarks.jsonl", "results/item_outcomes.jsonl", "registration_full.json"} <= set(d), (pool, d)
    # and the naive code tree passes only because code was sealed last
    assert differences(naive_rebuild(world["unsealed"], "code", tmp_path / "code"), world["trees"]["code"]) == []


def test_code_control_reports_identical(unblinded):
    ctrl = unblinded["summary"]["control"]
    assert set(ctrl) == {f"results/{n}" for n in U.RESULTS_FILES} | {"reference_item_outcomes.jsonl", "registration_full.json", "run_manifest.json"}
    assert all(v["identical"] for v in ctrl.values()), {k: v for k, v in ctrl.items() if not v["identical"]}
    assert not ctrl["results/benchmarks.jsonl"]["same_order"]          # the shuffle is seen, and does not matter to the multiset check


def test_endpoints_identical_on_rebuilt_and_original_trees(world, unblinded):
    out = unblinded["out"]
    for pool in ("factual", "math"):
        for name in IMPLS:
            x = json.loads((out / pool / "endpoints" / name / "endpoints.json").read_text())
            y = json.loads((world["trees"][pool] / "endpoints" / name / "endpoints.json").read_text())
            c = U.compare_json(x, y, U.ENV_KEYS)
            assert c["differing_beyond_rel_tol"] == 0, (pool, name, c)     # float-level only (BLAS/statsmodels reductions)
    ep = unblinded["summary"]["endpoint_control"]
    for name in (*IMPLS, "contamination"):
        assert "status" not in ep["registered row order"][name], name
    for name in IMPLS:            # code: the sealed-row-order copy reproduces the sealed endpoints
        assert ep["sealed row order"][name]["differing_beyond_rel_tol"] == 0, (name, ep["sealed row order"][name])
    assert ep["registered row order"]["contamination"]["differing_beyond_rel_tol"] == 0
    assert ep["registered row order"]["A_metabench_analysis"]["differing_beyond_rel_tol"] > 0   # A's draws follow the row order
    rep = (out / "REPORT_CONFIRMATORY.md").read_text()
    assert "recomputed at unblinding from the per-session sealed files (DEVIATIONS 2026-10-29 17:45)" in rep
    assert rep.index("## Pool: factual") < rep.index("## Pool: math") < rep.index("## Pool: code")
    assert rep.count("# MetaBench endpoints") == 4                  # A's endpoints.md: three recomputed pools + the sealed code copy
    assert all(v["rc"] == 0 for v in unblinded["summary"]["runs"].values())


def test_integrity_catches_a_truncated_file(world, tmp_path):
    u = tmp_path / "unsealed"
    shutil.copytree(world["unsealed"], u)
    victim = next((u / "sessions").glob("T1_math_*/transcript.jsonl"))
    victim.write_bytes(victim.read_bytes()[:-10])
    with pytest.raises(SystemExit, match="1 size mismatches"):
        U.main(argv(world, u, tmp_path / "out", "--skip-analyses"))
    assert not (tmp_path / "out" / "WORK_factual").exists()


def test_registration_check_catches_a_missing_session(world, tmp_path, monkeypatch):
    monkeypatch.setattr(R, "make_cfg", synthetic_make_cfg)
    u = tmp_path / "unsealed"
    shutil.copytree(world["unsealed"], u)
    gone = next(p for p in sorted((u / "sessions").glob("T1_math_*")) if not p.name.endswith("_rep1"))
    shutil.rmtree(gone)
    man = json.loads((u / "MANIFEST.json").read_text())
    man["files"] = {k: v for k, v in man["files"].items() if not k.startswith(f"sessions/{gone.name}/")}
    (u / "MANIFEST.json").write_text(json.dumps(man))
    with pytest.raises(SystemExit, match="math: registration check failed: 1 registered/declared sessions without"):
        U.main(argv(world, u, tmp_path / "out", "--skip-analyses"))


def test_registration_check_catches_a_config_hash_mismatch(world, tmp_path, monkeypatch):
    monkeypatch.setattr(R, "make_cfg", synthetic_make_cfg)
    u = tmp_path / "unsealed"
    shutil.copytree(world["unsealed"], u)
    cfgp = next((u / "sessions").glob("T1_factual_*_r0/config.json"))
    cfg = json.loads(cfgp.read_text()); cfg["config_hash"] = "0" * 64
    txt = json.dumps(cfg, sort_keys=True)
    cfgp.write_text(txt)
    man = json.loads((u / "MANIFEST.json").read_text())
    man["files"][str(cfgp.relative_to(u))]["plaintext_bytes"] = len(txt.encode())
    (u / "MANIFEST.json").write_text(json.dumps(man))
    with pytest.raises(SystemExit, match="factual: registration check failed: 1 config hash mismatches"):
        U.main(argv(world, u, tmp_path / "out", "--skip-analyses"))


def test_control_catches_a_changed_code_row(world, tmp_path, monkeypatch):
    monkeypatch.setattr(R, "make_cfg", synthetic_make_cfg)
    u = tmp_path / "unsealed"
    shutil.copytree(world["unsealed"], u)
    p = u / "results" / "item_outcomes.jsonl"
    rows = U.read_jsonl(p)
    rows[3]["n_correct"] = rows[3]["n_samples"] - rows[3]["n_correct"] + 7
    write_jsonl(p, rows)
    man = json.loads((u / "MANIFEST.json").read_text())
    man["files"]["results/item_outcomes.jsonl"]["plaintext_bytes"] = p.stat().st_size
    (u / "MANIFEST.json").write_text(json.dumps(man))
    with pytest.raises(SystemExit, match="control failed for 1 files: results/item_outcomes.jsonl"):
        U.main(argv(world, u, tmp_path / "out", "--skip-analyses"))


def _plant_reference(world, u: Path, rows_from: Path) -> None:
    """Both sealed reference-outcome paths replaced by another file, as Sealer.seal_tree leaves them when it skips a
    same-size re-seal for a later pool; MANIFEST byte counts updated so integrity passes."""
    man = json.loads((u / "MANIFEST.json").read_text())
    for rel in ("results/reference_item_outcomes.jsonl", "reference_item_outcomes.jsonl"):
        shutil.copy(rows_from, u / rel)
        man["files"][rel]["plaintext_bytes"] = (u / rel).stat().st_size
    (u / "MANIFEST.json").write_text(json.dumps(man))


def test_control_accepts_an_earlier_pools_same_size_reference_copy(world, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(R, "make_cfg", synthetic_make_cfg)
    u = tmp_path / "unsealed"
    shutil.copytree(world["unsealed"], u)
    _plant_reference(world, u, world["trees"]["factual"] / "results" / "reference_item_outcomes.jsonl")
    assert U.main(argv(world, u, tmp_path / "out", "--skip-analyses")) == 0
    out = capsys.readouterr().out
    assert out.count("sealed copy is the factual pool's") == 2


def test_control_rejects_a_reference_copy_matching_no_pool(world, tmp_path, monkeypatch):
    monkeypatch.setattr(R, "make_cfg", synthetic_make_cfg)
    u = tmp_path / "unsealed"
    shutil.copytree(world["unsealed"], u)
    rows = U.read_jsonl(world["trees"]["factual"] / "results" / "reference_item_outcomes.jsonl")
    rows[5]["n_correct"] = rows[5]["n_samples"] - rows[5]["n_correct"] + 7
    bad = tmp_path / "bad_ref.jsonl"
    write_jsonl(bad, rows)
    _plant_reference(world, u, bad)
    with pytest.raises(SystemExit, match="control failed for 2 files"):
        U.main(argv(world, u, tmp_path / "out", "--skip-analyses"))
