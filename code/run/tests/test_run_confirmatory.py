"""scripts_run_confirmatory.sh: refuses without a frozen-code file, on a frozen-code mismatch or without a gcloud
access token (exit 3, refusal row, no logs), and in --dry-run lists the per-pool commands in the registered order
(factual, math, code) with the frozen-size defaults and writes only plaintext progress rows (no percentages, no
decimals).  Always runs on a temp root with a stubbed `gcloud` first on PATH; never on the real root."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scripts_freeze as F  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts_run_confirmatory.sh"
POOL_PATHS = {"math": "pools/math/pool.jsonl", "code": "pools/code/pool.jsonl", "factual": "pools/factual_qa/pool.jsonl"}


def _root(tmp_path: Path) -> Path:
    """Temp root with the frozen file set, metabench/, the sealing keyring (sockets skipped) and dummy pools."""
    root = tmp_path / "root"
    for rel in F.FROZEN_FILES:
        src = ROOT / rel
        if src.exists():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, root / rel)
    shutil.copytree(ROOT / "metabench", root / "metabench", ignore=shutil.ignore_patterns("__pycache__"), dirs_exist_ok=True)
    shutil.copytree(ROOT / "sealing", root / "sealing", ignore=shutil.ignore_patterns("S.gpg-agent*", "*~", "random_seed"))
    for rel in POOL_PATHS.values():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text('{"id": "P0001", "prompt": "dummy", "answer": "1"}\n')
    return root


def _stub_gcloud(root: Path, script: str = 'echo stub-token') -> str:
    """A fake `gcloud` first on PATH (the real one must never be consulted by a test); returns the PATH to use."""
    d = root.parent / "stubbin"
    d.mkdir(exist_ok=True)
    g = d / "gcloud"
    g.write_text("#!/usr/bin/env bash\n" + script + "\n")
    g.chmod(0o755)
    return f"{d}:{os.environ['PATH']}"


def _run(root: Path, *args: str, pools: str = "factual math code", gcloud: str = "echo stub-token") -> subprocess.CompletedProcess:
    env = {"PATH": _stub_gcloud(root, gcloud), "MB_RUN_ROOT": str(root)}
    if pools:
        env["MB_POOLS"] = pools
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=root.parent, env=env, capture_output=True, text=True)


def _progress(root: Path) -> str:
    return (root / "docs/RUN_PROGRESS.md").read_text()


def _log_files(root: Path) -> list[str]:
    return sorted(p.name for p in (root / "logs").glob("*")) if (root / "logs").exists() else []


def test_refuses_without_frozen_code(tmp_path):
    root = _root(tmp_path)
    r = _run(root, "--dry-run")
    assert r.returncode == 3, r.stdout + r.stderr
    assert "REFUSED" in _progress(root) and "frozen_code.json missing" in _progress(root)
    assert _log_files(root) == []
    assert "DRY " not in r.stdout


def test_refuses_without_sealing_keyring(tmp_path):
    root = _root(tmp_path)
    F.freeze(root, "test")
    shutil.rmtree(root / "sealing/gnupg")
    r = _run(root, "--dry-run")
    assert r.returncode == 3
    assert "sealing/gnupg missing" in _progress(root)
    assert _log_files(root) == []


def test_refuses_on_frozen_code_mismatch(tmp_path):
    root = _root(tmp_path)
    F.freeze(root, "test")
    p = root / "metabench/arms.py"
    p.write_text(p.read_text() + "\n# tampered\n")
    r = _run(root, "--dry-run")
    assert r.returncode == 3, r.stdout + r.stderr
    rows = [ln for ln in _progress(root).splitlines() if "REFUSED" in ln]
    assert len(rows) == 1 and "mismatch" in rows[0] and "metabench/arms.py" in rows[0]
    assert _log_files(root) == ["run_confirmatory_phase0_verify.log"]
    assert "DRY " not in r.stdout


@pytest.mark.parametrize("gcloud", ["exit 1", "echo -n ''", "echo 'ERROR: no credential' >&2; exit 1"])
def test_refuses_without_gcloud_token(tmp_path, gcloud):
    root = _root(tmp_path)
    F.freeze(root, "test")
    r = _run(root, "--dry-run", gcloud=gcloud)
    assert r.returncode == 3, r.stdout + r.stderr
    rows = [ln for ln in _progress(root).splitlines() if "REFUSED" in ln]
    assert len(rows) == 1 and "gcloud auth print-access-token returned no token" in rows[0]
    assert _log_files(root) == []           # refused before the freeze verify
    assert "DRY " not in r.stdout


def test_gcloud_token_never_reaches_progress_or_stdout(dry_run):
    root, r = dry_run
    assert "stub-token" not in r.stdout + r.stderr + _progress(root)


@pytest.fixture
def dry_run(tmp_path):
    root = _root(tmp_path)
    F.freeze(root, "test")
    r = _run(root, "--dry-run", pools="")   # MB_POOLS unset: the script's own default order is under test
    assert r.returncode == 0, r.stdout + r.stderr
    return root, r


def test_dry_run_lists_pool_commands_in_order(dry_run):
    root, r = dry_run
    dry = [ln[4:] for ln in r.stdout.splitlines() if ln.startswith("DRY ")]
    assert len(dry) == 15 and r.stdout.strip().endswith("ALL POOLS DONE")
    phases = ["scripts_freeze.py verify", "scripts_runner.py precompute", "scripts_runner.py register", "scripts_runner.py run", "scripts_health_check.py"]
    for i, name in enumerate(["factual", "math", "code"]):   # registered order: shortest pool first
        block = dry[5 * i: 5 * i + 5]
        assert [ph in cmd for ph, cmd in zip(phases, block)] == [True] * 5, block
        for cmd in block[1:4]:
            assert f"--pool {POOL_PATHS[name]} --pool-name {name} --samples 5" in cmd
        assert f"--view health/health_view_{name}.jsonl --registered prereg/confirmatory_hashes_{name}.json" in block[4]
        assert "--replacements" not in block[4]          # no replacements file exists in the temp root
    assert "--panel-concurrency 96" in dry[1] and "--concurrency 16" in dry[3]
    for flag in ("--cells", "--designers", "--n-items", "--k-rounds", "--allow-non-tmpfs", "--substitute", "--allow-partial-precompute", "--keep-work"):
        assert not any(flag in cmd for cmd in dry), flag
    rows = [ln for ln in _progress(root).splitlines() if "exit=dry" in ln]
    assert len(rows) == 15
    assert [ln.split("|")[2].strip() for ln in rows[::5]] == ["factual", "math", "code"]
    for name in ("factual", "math", "code"):
        assert [ln.split("|")[3].strip() for ln in rows if f"| {name} |" in ln] == ["verify", "precompute", "register", "run", "health"]
    assert _progress(root).startswith("# Confirmatory run progress (plaintext: ids, counts, timings, exit codes only)")
    assert "| - | phase0 | exit=0 |" in _progress(root)
    assert _log_files(root) == ["run_confirmatory_phase0_verify.log"]   # dry run executes nothing but phase 0


def test_progress_file_carries_no_scores(dry_run):
    root, _ = dry_run
    text = _progress(root)
    assert "%" not in text
    assert not re.search(r"\b0\.\d{3}", text), text


def test_unknown_pool_name_refuses(tmp_path):
    root = _root(tmp_path)
    F.freeze(root, "test")
    r = _run(root, "--dry-run", pools="math bogus")
    assert r.returncode == 3 and "unknown pool name bogus" in _progress(root)
    assert "DRY " not in r.stdout
