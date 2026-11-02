"""Contamination check on the reference item outcomes (docs/CONTAMINATION_SPEC.md).

    .venv/bin/python scripts_contamination.py --reference WORK/results/reference_item_outcomes.jsonl \
        --pool pools/<domain>/pool.jsonl --out DIR [--n-boot 10000] [--seed 20261025]

Writes DIR/contamination.json (an outcome: sealed by the runner).  Prints exactly one status line to stdout
(counts, elapsed seconds, exit code); never an accuracy or a flag.  Tracebacks go to stderr.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metabench.contamination import run_check  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reference", required=True, type=Path)
    ap.add_argument("--pool", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--n-boot", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=20261025)
    a = ap.parse_args(argv)
    t0 = time.time()
    code, n_items, n_entries = 0, 0, 0
    try:
        rep = run_check(a.reference, a.pool, n_boot=a.n_boot, seed=a.seed)
        n_items, n_entries = rep["inputs"]["n_items"], rep["inputs"]["n_entries"]
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "contamination.json").write_text(json.dumps(rep, indent=1))
    except Exception:
        traceback.print_exc(file=sys.stderr)
        code = 1
    print(f"contamination_check entries={n_entries} items={n_items} n_boot={a.n_boot} elapsed_s={time.time() - t0:.0f} exit={code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
