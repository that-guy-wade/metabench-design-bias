"""All three analysis implementations through the runner's own invocation path (Runner.run_analyses: same argv, cwd,
environment, timeout and address-space cap as the confirmatory finish step) on synthetic trees in the runner's real
layout (metabench.synthetic writes it since BUILD4).  The fast variant uses a 4-designer, 150-item tree; the slow variant
the frozen confirmatory size (12 designers, 468 sessions + replacements, 2,000 items, 5 samples) with the registered
n_perm / n_boot (run with `-m slow`; about an hour).  Also the BUILD4 regression tests, each failing on the pre-BUILD4 code:
the results path handed to B and C, C's reader on the runner's run_manifest.json / registration_full.json shapes, the
runner's exception row, the analysis timeout and memory cap, and the memory of A's DIF design."""
from __future__ import annotations

import importlib.util
import json
import os
import resource
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import scripts_runner as R  # noqa: E402
from metabench import panel, synthetic  # noqa: E402
from metabench.arms import make_session_config  # noqa: E402

POOL = "pools/factual_qa/pool.jsonl"           # the confirmatory invocation (scripts_run_confirmatory.sh); registered name "factual"
IMPLS = ("A_metabench_analysis", "B", "C")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                      # dataclasses resolve the defining module through sys.modules
    spec.loader.exec_module(mod)
    return mod


def _runner(work: Path, n_perm: int, n_boot: int, timeout: float = 4 * 3600, memory_mib: int = 20480) -> R.Runner:
    """The confirmatory `run` arguments (BUILD_REPORT section 2 / scripts_run_confirmatory.sh) on an existing working directory."""
    a = R.build_parser().parse_args(["run", "--pool", POOL, "--pool-name", "factual", "--samples", "5", "--concurrency", "16",
                                     "--work-dir", str(work), "--allow-non-tmpfs", "--n-perm", str(n_perm), "--n-boot", str(n_boot),
                                     "--analysis-timeout", str(timeout), "--analysis-memory-mib", str(memory_mib)])
    return R.Runner(a)


def _rc(work: Path, name: str):
    first = (work / "endpoints" / name / "log.txt").read_text().splitlines()[0]
    assert first.startswith("rc="), first
    v = first[3:]
    return int(v) if v.lstrip("-").isdigit() else v


def _every_estimate_has_interval(name: str, ep: dict) -> list[str]:
    """Paths of estimates without an interval, per implementation's own output schema."""
    missing: list[str] = []

    def has_ci(node, ci_prefix):
        cb = node.get("cluster_bootstrap")
        return any(k.startswith(ci_prefix) for k in node) or (isinstance(cb, dict) and any(k.startswith(ci_prefix) for k in cb))

    def walk(node, path, est_keys, ci_prefix):
        if isinstance(node, dict):
            if any(k in node for k in est_keys) and not has_ci(node, ci_prefix) and "/per_arm/" not in path:
                missing.append(path)          # B's S4 per_arm split is a descriptive point estimate (its REPORT); exempt
            for k, v in node.items():
                walk(v, f"{path}/{k}", est_keys, ci_prefix)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]", est_keys, ci_prefix)

    if name == "A_metabench_analysis":
        walk(ep["primary"], "primary", ("psi",), "ci95")
        walk(ep["secondary"], "secondary", ("gain", "diff_z"), "ci95")        # leader_rank_gain[arm], self_rank_identity, tau contrasts
        walk(ep["dif"]["effects"], "dif/effects", ("log_odds",), "ci95")
    elif name == "B":
        if "ci95_tanh" not in ep["primary"]["cluster_bootstrap"]:
            missing.append("primary/cluster_bootstrap")
        for k, v in ep["secondary"].items():
            if k.startswith("S") and isinstance(v, dict):
                walk(v, f"secondary/{k}", ("estimate",), "ci95")
        walk(ep["measurement_model"].get("fallback_glm", {}), "measurement_model/fallback_glm", ("log_odds",), "ci95")
    else:
        for sec in ("primary", "secondary", "exploratory"):
            walk(ep[sec], sec, ("estimate",), "ci95")
        if "ci95_tanh" not in ep["primary"]["cluster_bootstrap"]:
            missing.append("primary/cluster_bootstrap")
    return missing


def _check_all(work: Path):
    for name in IMPLS:
        assert _rc(work, name) == 0, (name, (work / "endpoints" / name / "log.txt").read_text()[-3000:])
        ep = json.loads((work / "endpoints" / name / "endpoints.json").read_text())
        assert _every_estimate_has_interval(name, ep) == [], name


@pytest.fixture(scope="session")
def small_tree(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("b4") / "small"
    synthetic.generate(out, seed=4402, pool_name="factual", n_designers=4, n_pool=150, invalid_rate=0.05)
    return out


def test_fast_all_three_through_runner_path(small_tree):
    """Pre-BUILD4: B rc=1 (empty session table), C rc=1 (WORK/results/results/benchmarks.jsonl) in about a second."""
    r = _runner(small_tree, n_perm=200, n_boot=200)
    cmds = dict(r.analysis_commands())
    assert cmds["A_metabench_analysis"][cmds["A_metabench_analysis"].index("--results") + 1] == str(small_tree / "results")
    for name in ("B", "C"):
        assert cmds[name][cmds[name].index("--results") + 1] == str(small_tree)
    r.run_analyses()
    _check_all(small_tree)


@pytest.mark.slow
def test_slow_full_size_through_runner_path(tmp_path_factory):
    """The frozen confirmatory size with the registered n_perm / n_boot; pre-BUILD4 A exceeded the box's memory (SIGTERM at
    29.8 GB after 1,718 s) and B / C failed in seconds.  Runtimes go to endpoints/<impl>/log.txt and stdout."""
    out = tmp_path_factory.mktemp("b4") / "full"
    synthetic.generate(out, seed=4401, pool_name="factual", n_designers=12, n_pool=2000, invalid_rate=0.01)
    r = _runner(out, n_perm=10000, n_boot=10000)
    r.run_analyses()
    _check_all(out)


# ---------------------------------------------------------------------------------------------- regression tests

C_LOAD = _load("c_load", ROOT / "analysis_impls" / "C" / "cimpl" / "load.py")


def test_c_reader_accepts_runner_manifest_and_registration_shapes(small_tree, tmp_path):
    """The runner writes run_manifest.json `panel` as a list of keys (pre-BUILD4) and registration_full.json with the configs
    under "configs"; C read `panel.displayed_keys` (AttributeError on a list) and the flat registration (no false identities)."""
    work = tmp_path / "w"
    work.mkdir()
    for p in ("results", "sessions", "reference_item_outcomes.jsonl"):
        os.symlink(small_tree / p, work / p)
    m = json.loads((small_tree / "run_manifest.json").read_text())
    m["panel"] = [s.key for s in panel.PANEL]
    (work / "run_manifest.json").write_text(json.dumps(m))
    (work / "registration_full.json").write_text((small_tree / "registration_full.json").read_text())
    ds = C_LOAD.load(work)
    assert set(ds.designer_keys) == set(panel.DISPLAYED_KEYS)        # D3: the 12 displayed designer keys (intersection fallback)
    false_rows = [b for b in ds.benches if b.identity_arm == "false"]
    assert false_rows and all(b.false_identity for b in false_rows)
    assert all(b.false_identity == json.loads((small_tree / "sessions" / b.session_id / "config.json").read_text())["false_identity"] for b in false_rows)


def test_exception_row_has_the_full_benchmark_schema(small_tree, tmp_path):
    """A session whose writer raised got a 14-field row (no displayed_keys / panel_keys / label_map); B and C index those."""
    panel.set_active("confirmatory")
    ref = json.loads((small_tree / "registration_full.json").read_text())["reference_scores"]
    cfg = make_session_config("T1_factual_fable51_sham_false_r9", "fable51", "sham", "false", 9, 123456, ref, pool_name="factual",
                              pool_description="x", with_monitors=True)
    row = R.exception_row(cfg, RuntimeError("boom"), {}, {}, ref, tmp_path / "s", 1.5)
    assert set(synthetic.BENCHMARK_FIELDS) <= set(row) | {"api_errors", "started_at", "ended_at", "replacement_of"}
    assert row["valid"] is False and row["status"] == "exception:RuntimeError" and row["displayed_keys"] == cfg.displayed_keys
    b_core = _load("b_core", ROOT / "analysis_impls" / "B" / "core.py")
    assert set(b_core.rank_panel([row])) == set(cfg.displayed_keys)
    assert C_LOAD._bench_from_json(row).valid is False


def test_analysis_timeout_and_memory_cap(tmp_path, monkeypatch):
    """A hung implementation gets rc=timeout (the raw artefacts still seal); one that outgrows --analysis-memory-mib fails with
    MemoryError inside its own process instead of the box's memory manager terminating it."""
    fake_root = tmp_path / "root"
    for name, body in {"sleeper": "import time; time.sleep(30)",
                       "hog": "x = bytearray(400 * 1024 * 1024); print(len(x))",
                       "fine": "import sys, json, pathlib; o = pathlib.Path(sys.argv[sys.argv.index('--out') + 1]); o.mkdir(parents=True, exist_ok=True); (o / 'endpoints.json').write_text('{}')"}.items():
        (fake_root / "analysis_impls" / name).mkdir(parents=True)
        (fake_root / "analysis_impls" / name / "run.py").write_text(body + "\n")
    monkeypatch.setattr(R, "ROOT", fake_root)
    work = tmp_path / "work"
    (work / "results").mkdir(parents=True)
    r = _runner(work, n_perm=10, n_boot=10, timeout=2, memory_mib=256)
    r.run_analyses()
    assert _rc(work, "sleeper") == "timeout"
    assert _rc(work, "hog") == 1 and "MemoryError" in (work / "endpoints" / "hog" / "log.txt").read_text()
    assert _rc(work, "fine") == 0


def test_dif_design_memory_is_bounded(small_tree):
    """A's stage-2 GLM on a 4-designer tree (271k rows x 168 columns, 0.35 GB design): the pre-BUILD4 pandas dummies, concat,
    constant check and IRLS pinv copies peaked at 6.3 GB of address space (4.6 GB resident); the in-place design + Newton fit
    peaks at 3.1 GB (1.7 GB resident) with identical estimates to 1e-15 (measured 2026-10-25, BUILD4_REPORT).  Fails on the old
    code with MemoryError under a 4.5 GB cap."""
    code = textwrap.dedent(f"""
        import resource, sys
        cap = 4500 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
        sys.path.insert(0, {str(ROOT)!r})
        from pathlib import Path
        from metabench import analysis as A
        res = Path({str(small_tree)!r}) / "results"
        d = A.dif_model(A.read_jsonl(res / "item_outcomes.jsonl"), A.read_jsonl(res / "benchmarks.jsonl"),
                        A.read_jsonl(res / "reference_item_outcomes.jsonl"), fit_mixed=False)
        assert "error" not in d and d["effects"]["gamma_Target"]["se"] > 0, d
        print("ok", d["n_rows"], len(d["effects"]))
    """)
    env = {**os.environ, "OPENBLAS_NUM_THREADS": "2", "OMP_NUM_THREADS": "2"}
    p = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, env=env)
    assert p.returncode == 0 and p.stdout.startswith("ok"), p.stderr[-3000:]
