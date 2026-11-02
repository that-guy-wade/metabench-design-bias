"""Shared fixtures: synthetic trees from metabench.synthetic (the only allowed test-data source)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", "2")

import pytest  # noqa: E402

HERE = Path(__file__).resolve().parent
IMPL = HERE.parent
RUN = IMPL.parents[1]                      # .../run
sys.path.insert(0, str(IMPL))
PY = str(RUN / ".venv" / "bin" / "python")
SMALL = ["--n-designers", "4", "--n-pool", "150"]


def generate(out: Path, seed: int, *extra: str) -> Path:
    if not (out / "results" / "benchmarks.jsonl").exists():
        subprocess.run([PY, "-m", "metabench.synthetic", "--out", str(out), "--seed", str(seed), *extra],
                       cwd=RUN, check=True, capture_output=True)
    return out


@pytest.fixture(scope="session")
def trees(tmp_path_factory) -> dict[str, Path]:
    base = Path(os.environ.get("MBC_TREE_CACHE", tmp_path_factory.mktemp("trees")))
    base.mkdir(parents=True, exist_ok=True)
    return {
        "null": generate(base / "null", 9001, *SMALL),
        "tracking": generate(base / "tracking", 9002, *SMALL, "--tracking", "0.3"),
        "rank_gain": generate(base / "rank_gain", 9003, *SMALL, "--rank-gain", "2"),
        "identity": generate(base / "identity", 9004, *SMALL, "--identity-effect", "2"),
    }
