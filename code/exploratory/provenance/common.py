"""Shared loaders for the provenance / kept-vs-viewed analysis (EXPLORATORY, post-unblinding, 2026-10-30).

Run with PYTHONPATH=/path/to/metabench/run. Reads only /path/to/metabench/unblinded/ and
run/pools/; writes only inside analysis/provenance/.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from metabench import panel
panel.set_active("confirmatory")

ROOT = Path("/path/to/metabench")
UNB = ROOT / "unblinded"
OUT = ROOT / "analysis" / "provenance"
POOLS = {"factual": "factual_qa", "math": "math", "code": "code"}

DESIGNERS = list(panel.DISPLAYED_KEYS)                     # 12 designer keys
K13 = DESIGNERS + ["placebo_sonnet55"]                    # fixed 13-key rank set (12 designers + placebo)
DEV = {k: panel.CONFIRMATORY_DESIGNER_IDENTITY[k][1] for k in DESIGNERS}


def read_jsonl(p):
    with open(p) as f:
        return [json.loads(l) for l in f if l.strip()]


def bench_rows(pool: str) -> list[dict]:
    return [r for r in read_jsonl(UNB / f"WORK_{pool}" / "results" / "benchmarks.jsonl") if r.get("valid")]


def load_pool(pool: str) -> dict[str, dict]:
    return {it["id"]: it for it in read_jsonl(ROOT / "run" / "pools" / POOLS[pool] / "pool.jsonl")}


def reference_matrix(pool: str, keys: list[str]):
    """A[item, key] = n_correct / n_samples over the full pool (reference_item_outcomes.jsonl); NaN if no samples."""
    rows = read_jsonl(UNB / f"WORK_{pool}" / "results" / "reference_item_outcomes.jsonl")
    items = sorted({r["item_id"] for r in rows})
    ii = {x: i for i, x in enumerate(items)}
    kk = {k: j for j, k in enumerate(keys)}
    A = np.full((len(items), len(keys)), np.nan)
    for r in rows:
        if r["model_key"] in kk and r["n_samples"] > 0:
            A[ii[r["item_id"]], kk[r["model_key"]]] = r["n_correct"] / r["n_samples"]
    return items, ii, A


def cell(r: dict) -> str:
    return f"{r['info_arm']}/{r['identity_arm']}"
