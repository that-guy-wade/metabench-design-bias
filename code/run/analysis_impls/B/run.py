"""Implementation B: compute every pre-registered endpoint from a runner working directory (ARTEFACT_SCHEMA layout).

    python run.py --results DIR --out DIR [--n-perm 10000] [--n-boot 10000] [--seed 7] [--mixed-timeout 1800] [--no-mixed]

Writes OUT/endpoints.json (and OUT/session_table.csv).  Deterministic for fixed inputs and seed (DECISIONS D26).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core  # noqa: E402
import measurement  # noqa: E402

REGISTERED_MASTER_SEED = 20261025


def _clean(o):
    """JSON-safe copy: numpy scalars to python, nan to None-preserving floats (json emits NaN by default; we keep floats)."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return [_clean(v) for v in o.tolist()]
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def run(results: str, out: str, n_perm: int, n_boot: int, seed: int, mixed_timeout: float, do_mixed: bool, maxiter: int,
        mixed_method: str = "laplace") -> dict:
    if seed == REGISTERED_MASTER_SEED:
        raise SystemExit("seed 20261025 is the run's master seed; choose another analysis seed")
    t0 = time.time()
    rng = np.random.default_rng(seed)
    tree = core.load_tree(results)
    bench = tree["benchmarks"]
    valid = core.valid_rows(bench)
    df = core.session_table(bench, tree["configs"])
    status_counts: dict[str, int] = {}
    for b in bench:
        status_counts[b.get("status", "?")] = status_counts.get(b.get("status", "?"), 0) + 1
    cell_counts = df.cell.value_counts().sort_index().to_dict()
    report: dict = {
        "implementation": "B", "inputs": {"results_dir": str(Path(results).resolve()), "n_rows": len(bench), "n_valid": len(valid),
                                          "n_invalid": len(bench) - len(valid), "status_counts": status_counts,
                                          "n_replacements": sum(1 for b in bench if b.get("replacement_of")),
                                          "invalid_sessions": [{"session_id": b["session_id"], "status": b.get("status"), "n_items": b.get("n_items")}
                                                               for b in bench if not b.get("valid")],
                                          "valid_cell_counts": {str(k): int(v) for k, v in cell_counts.items()},
                                          "designers": sorted(df.designer.unique().tolist()), "rank_panel_13": df.attrs["panel13"]},
        "settings": {"n_perm": n_perm, "n_boot": n_boot, "seed": seed, "mixed_timeout_s": mixed_timeout, "mixed_enabled": do_mixed, "mixed_method": mixed_method},
    }
    report["primary"] = core.primary_endpoint(df, n_perm, n_boot, rng)
    report["secondary"] = core.secondary_endpoints(df, n_perm, n_boot, rng)
    io = core.load_item_outcomes(tree, set(df.session_id))
    ref = core.load_reference_outcomes(tree)
    report["exploratory"] = core.exploratory(df, tree, n_perm, n_boot, rng, io)
    if len(io):
        if do_mixed:
            report["measurement_model"] = measurement.measurement_model(tree, df, io, ref, mixed_timeout, out, maxiter, seed, mixed_method)
        else:
            design = measurement.build_design(tree, df, io, ref)
            report["measurement_model"] = {"fallback_glm": measurement.fit_glm_fe(design), "mixed": {"status": "disabled"},
                                           "reported": "fallback_glm", "reported_note": "mixed model disabled by --no-mixed"}
    else:
        report["measurement_model"] = {"status": "no item outcomes found"}
    elapsed = round(time.time() - t0, 1)
    outp = Path(out)
    outp.mkdir(parents=True, exist_ok=True)
    timing = {"elapsed_seconds": elapsed}
    mm = report.get("measurement_model", {})
    for key in ("fallback_glm", "mixed"):
        if isinstance(mm.get(key), dict):
            for tk in ("fit_seconds", "wall_seconds"):
                if tk in mm[key]:
                    timing[f"{key}_{tk}"] = mm[key].pop(tk)
    (outp / "timing.json").write_text(json.dumps(timing, indent=1))
    report["elapsed_seconds"] = elapsed
    cols = ["session_id", "designer", "info_arm", "identity_arm", "n_displayed", "displayed_leader", "told_identity", "n_score_requests",
            "tau_disp", "tau_ref", "tau_ref_rev", "rbo_disp"]
    df[cols].to_csv(outp / "session_table.csv", index=False)
    text = json.dumps(_clean({k: v for k, v in report.items() if k != "elapsed_seconds"}), indent=1, sort_keys=True)
    (outp / "endpoints.json").write_text(text)
    report["endpoints_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-perm", type=int, default=10000)
    ap.add_argument("--n-boot", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--mixed-timeout", type=float, default=1800.0)
    ap.add_argument("--mixed-maxiter", type=int, default=60, help="outer iterations of the variance-component optimiser")
    ap.add_argument("--mixed-method", default="laplace", choices=["laplace", "map", "vb"],
                    help="own Laplace GLMM (default), statsmodels posterior mode, or variational Bayes")
    ap.add_argument("--no-mixed", action="store_true", help="skip the mixed model (fallback GLM only)")
    a = ap.parse_args(argv)
    rep = run(a.results, a.out, a.n_perm, a.n_boot, a.seed, a.mixed_timeout, not a.no_mixed, a.mixed_maxiter, a.mixed_method)
    p = rep["primary"]
    print(json.dumps({"n_valid": rep["inputs"]["n_valid"], "primary_tanh": p.get("estimate_tanh"),
                      "primary_p": p.get("randomisation", {}).get("p_one_sided"), "primary_ci_tanh": p.get("cluster_bootstrap", {}).get("ci95_tanh"),
                      "holm": {k: v["p_holm"] for k, v in rep["secondary"]["holm"].items()},
                      "measurement_reported": rep["measurement_model"].get("reported"), "elapsed_s": rep["elapsed_seconds"],
                      "sha256": rep["endpoints_sha256"]}, indent=1))


if __name__ == "__main__":
    main()
