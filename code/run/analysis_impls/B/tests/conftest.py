"""Fixtures: synthetic artefact trees from metabench.synthetic with fixed seeds (regenerated into a tmp dir unless MBB_TREES
points at a directory that already holds them)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

B_DIR = Path(__file__).resolve().parents[1]
RUN_DIR = B_DIR.parents[1]                       # .../run
PY = str(RUN_DIR / ".venv" / "bin" / "python") if (RUN_DIR / ".venv" / "bin" / "python").exists() else sys.executable
sys.path.insert(0, str(B_DIR))

TREE_SPECS = {
    "null": (11, []),
    "track": (12, ["--tracking", "0.3"]),
    "gain": (13, ["--rank-gain", "2.0"]),
    "ident": (14, ["--identity-effect", "2.0"]),
    "small": (15, ["--n-designers", "4"]),
    "invalid": (16, ["--n-designers", "4", "--invalid-rate", "0.15"]),
}


@pytest.fixture(scope="session")
def trees(tmp_path_factory) -> dict[str, Path]:
    base = Path(os.environ.get("MBB_TREES", "")) if os.environ.get("MBB_TREES") else tmp_path_factory.mktemp("trees")
    base.mkdir(parents=True, exist_ok=True)
    procs = {}
    for name, (seed, extra) in TREE_SPECS.items():
        out = base / name
        if (out / "results" / "benchmarks.jsonl").exists():
            continue
        procs[name] = subprocess.Popen([PY, "-m", "metabench.synthetic", "--out", str(out), "--seed", str(seed), *extra],
                                       cwd=str(RUN_DIR), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    for name, p in procs.items():
        _, err = p.communicate()
        assert p.returncode == 0, f"generator failed for {name}: {err[-2000:]}"
    return {name: base / name for name in TREE_SPECS}
