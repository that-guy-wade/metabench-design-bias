#!/usr/bin/env python
"""Analysis implementation C: pre-registered endpoints from a runner working directory.

    python run.py --results DIR --out DIR [--n-perm 10000] [--n-boot 10000] [--seed 20261028] [--skip-measurement]

Writes OUT/endpoints.json. See DECISIONS.md for every choice on ambiguous points.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

# OpenBLAS with many threads makes LAPACK's Cholesky pathologically slow on this box (13 s vs 0.2 s at n = 2700);
# pin the BLAS thread pool before numpy is imported. Results do not depend on the thread count.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", "2")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cimpl.endpoints import Table, exploratory_rankings, primary, secondary   # noqa: E402
from cimpl.irt import measurement_model                                        # noqa: E402
from cimpl.load import load                                                    # noqa: E402

DEFAULT_SEED = 20261025 + 3


def _json_default(o):
    import numpy as np
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.bool_,)):
        return bool(o)
    raise TypeError(str(type(o)))


def _sanitise(o):
    """NaN/inf -> null so the JSON is strict."""
    import math
    if isinstance(o, dict):
        return {k: _sanitise(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_sanitise(v) for v in o]
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


def analyse(results: Path, n_perm: int, n_boot: int, seed: int, skip_measurement: bool = False, log=print) -> dict:
    t0 = time.time()
    ds = load(results)
    tab = Table(ds)
    valid = ds.valid
    by_status: dict[str, int] = {}
    for b in ds.benches:
        if not b.valid:
            by_status[b.status] = by_status.get(b.status, 0) + 1
    cells: dict[str, int] = {}
    for b in valid:
        cells[b.cell] = cells.get(b.cell, 0) + 1
    out: dict = {
        "implementation": "C",
        "inputs": {"results_dir": str(results), "n_perm": n_perm, "n_boot": n_boot, "seed": seed,
                   "decisions_sha256": hashlib.sha256((Path(__file__).parent / "DECISIONS.md").read_bytes()).hexdigest()},
        "data": {"n_sessions": len(ds.benches), "n_valid": len(valid), "n_invalid": len(ds.benches) - len(valid),
                 "invalid_by_status": by_status, "n_replacements": sum(1 for b in ds.benches if b.replacement_of),
                 "n_designers_valid": len({b.designer for b in valid}), "designer_keys": ds.designer_keys,
                 "valid_sessions_by_cell": dict(sorted(cells.items())),
                 "invalid_session_ids": sorted(b.session_id for b in ds.benches if not b.valid)},
        "warnings": list(ds.warnings),
    }
    log(f"[C] loaded {len(ds.benches)} sessions, {len(valid)} valid ({time.time() - t0:.1f}s)")
    out["primary"] = primary(tab, n_perm, n_boot, seed)
    log(f"[C] primary tanh(psi)={out['primary'].get('estimate_tanh_psi'):.4f} p={out['primary'].get('randomisation', {}).get('p_one_sided')} ({time.time() - t0:.1f}s)")
    out["secondary"] = secondary(tab, n_perm, n_boot, seed)
    log(f"[C] secondary done ({time.time() - t0:.1f}s)")
    out["exploratory"] = exploratory_rankings(tab, n_perm, n_boot, seed)
    log(f"[C] exploratory rankings done ({time.time() - t0:.1f}s)")
    if skip_measurement:
        out["measurement_model"] = {"skipped": True}
    else:
        out["measurement_model"] = measurement_model(ds, n_boot=min(n_boot, 2000), seed=seed)
        mm = out["measurement_model"].get("mixed", {}).get("gamma_pooled", {})
        log(f"[C] measurement model gamma={mm.get('log_odds')} se={mm.get('se')} ({time.time() - t0:.1f}s)")
    out["warnings"] += out["secondary"].pop("warnings", [])
    return _sanitise(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-perm", type=int, default=10000)
    ap.add_argument("--n-boot", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--skip-measurement", action="store_true")
    a = ap.parse_args(argv)
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    res = analyse(Path(a.results), a.n_perm, a.n_boot, a.seed, a.skip_measurement)
    (out_dir / "endpoints.json").write_text(json.dumps(res, indent=1, sort_keys=True, default=_json_default) + "\n")
    print(f"[C] wrote {out_dir / 'endpoints.json'}")


if __name__ == "__main__":
    main()
