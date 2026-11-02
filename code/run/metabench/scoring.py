"""Scoring produced benchmarks from precomputed per-item correctness (plus live scores for edited items)."""
from __future__ import annotations

import hashlib
import json
from typing import Optional


def content_hash(item: dict) -> str:
    return hashlib.sha256(json.dumps({"q": item["question"], "o": item["options"]}, sort_keys=True).encode()).hexdigest()[:16]


def item_mean(correctness: dict[tuple[str, str], list[int]], item_id: str, model: str) -> Optional[float]:
    v = correctness.get((item_id, model))
    if not v:
        return None
    return sum(v) / len(v)


def benchmark_scores(items: list[str], weights: dict[str, float], models: list[str],
                     correctness: dict[tuple[str, str], list[int]],
                     live: Optional[dict[tuple[str, str], list[int]]] = None) -> dict[str, float]:
    """Weighted mean accuracy per model. `live` holds correctness for edited items keyed by (item_id, model)
    and overrides the precomputed table when present."""
    out = {}
    for m in models:
        num = 0.0
        den = 0.0
        for it in items:
            w = float(weights.get(it, 1.0))
            v = None
            if live and (it, m) in live:
                v = live[(it, m)]
                v = sum(v) / len(v) if v else None
            if v is None:
                v = item_mean(correctness, it, m)
            if v is None:
                continue
            num += w * v
            den += w
        out[m] = num / den if den > 0 else float("nan")
    return out


def reference_scores(pool_ids: list[str], models: list[str], correctness) -> dict[str, float]:
    return benchmark_scores(pool_ids, {}, models, correctness)


def ranking(scores: dict[str, float]) -> list[str]:
    return sorted(scores, key=lambda k: (-scores[k], k))
