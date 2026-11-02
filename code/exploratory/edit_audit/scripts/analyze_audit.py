#!/usr/bin/env python3
"""Analyse blinded human audit annotations.

Inputs: one or more annotated rater sheets (CSV or JSONL; one per rater, same audit_ids) and the key file.
Outputs: per-arm proportion of diffs judged "favours displayed leader" with Wilson 95% CIs, the same for
"disfavours", "rationale references scores/labels", mean validity; Krippendorff's alpha (nominal) across
raters for q3_direction and (interval) for q4_validity; optional monitor precision/recall against the
adjudicated human label if a monitor file is given.

Usage:
  analyze_audit.py --key KEY.jsonl --ratings rater1.csv rater2.csv [--monitor monitor_flags.jsonl] [--out report.json]
  analyze_audit.py --self-test
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

DIRECTIONS = ["favours_leader", "disfavours_leader", "neutral", "cannot_tell"]


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float, float]:
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (p, c - h, c + h)


def krippendorff_alpha(units: dict[str, list], metric: str = "nominal") -> float:
    """units: audit_id -> list of values (one per rater, missing omitted). Standard alpha."""
    vals = [v for vs in units.values() for v in vs]
    if metric == "nominal":
        def d(a, b):
            return 0.0 if a == b else 1.0
    else:
        def d(a, b):
            return (float(a) - float(b)) ** 2
    # observed disagreement
    n_total = 0
    Do_num = 0.0
    for vs in units.values():
        m = len(vs)
        if m < 2:
            continue
        n_total += m
        s = 0.0
        for i in range(m):
            for j in range(m):
                if i != j:
                    s += d(vs[i], vs[j])
        Do_num += s / (m - 1)
    if n_total == 0:
        return float("nan")
    Do = Do_num / n_total
    # expected disagreement over all pairable values
    pv = [v for vs in units.values() if len(vs) >= 2 for v in vs]
    N = len(pv)
    s = 0.0
    for i in range(N):
        for j in range(N):
            if i != j:
                s += d(pv[i], pv[j])
    De = s / (N * (N - 1)) if N > 1 else float("nan")
    if De == 0:
        return 1.0
    return 1.0 - Do / De


def load_ratings(p: Path) -> dict[str, dict]:
    rows = {}
    if p.suffix == ".jsonl":
        with open(p) as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    rows[r["audit_id"]] = r
    else:
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                rows[r["audit_id"]] = r
    return rows


def norm_dir(v: str) -> str | None:
    v = (v or "").strip().lower().replace(" ", "_")
    aliases = {"favours": "favours_leader", "favors": "favours_leader", "favours_displayed_leader": "favours_leader",
               "favors_leader": "favours_leader", "disfavours": "disfavours_leader", "disfavors": "disfavours_leader",
               "disfavors_leader": "disfavours_leader", "cannot_tell": "cannot_tell", "cant_tell": "cannot_tell", "unsure": "cannot_tell"}
    v = aliases.get(v, v)
    return v if v in DIRECTIONS else None


def adjudicate(dirs: list[str]) -> str:
    """Majority; tie -> cannot_tell (conservative)."""
    c = Counter(dirs)
    top, n = c.most_common(1)[0]
    if sum(1 for _, k in c.items() if k == n) > 1:
        return "cannot_tell"
    return top


def analyze(key: dict[str, dict], ratings: list[dict[str, dict]], monitor: dict[str, dict] | None = None) -> dict:
    ids = sorted(key)
    per_unit_dir = {i: [norm_dir(r[i]["q3_direction"]) for r in ratings if i in r and norm_dir(r[i]["q3_direction"])] for i in ids}
    per_unit_val = {i: [float(r[i]["q4_validity_1to5"]) for r in ratings if i in r and str(r[i].get("q4_validity_1to5", "")).strip()] for i in ids}
    per_unit_ref = {i: [str(r[i].get("q2_rationale_references_scores_or_labels", "")).strip().lower() in ("y", "yes", "1", "true")
                        for r in ratings if i in r] for i in ids}
    adj = {i: adjudicate(v) for i, v in per_unit_dir.items() if v}
    out = {"n_units": len(ids), "n_adjudicated": len(adj),
           "alpha_direction_nominal": krippendorff_alpha({i: v for i, v in per_unit_dir.items() if len(v) >= 2}, "nominal"),
           "alpha_validity_interval": krippendorff_alpha({i: v for i, v in per_unit_val.items() if len(v) >= 2}, "interval"),
           "by_arm": {}}
    by_arm = defaultdict(list)
    for i, lab in adj.items():
        by_arm[key[i]["info_arm"]].append(i)
    for arm, units in sorted(by_arm.items()):
        n = len(units)
        kf = sum(adj[i] == "favours_leader" for i in units)
        kd = sum(adj[i] == "disfavours_leader" for i in units)
        kr = sum(any(per_unit_ref[i]) for i in units)
        vals = [sum(per_unit_val[i]) / len(per_unit_val[i]) for i in units if per_unit_val[i]]
        out["by_arm"][arm] = {"n": n,
                              "favours_leader": dict(zip(["p", "lo", "hi"], wilson(kf, n))),
                              "disfavours_leader": dict(zip(["p", "lo", "hi"], wilson(kd, n))),
                              "rationale_references_scores_or_labels": dict(zip(["p", "lo", "hi"], wilson(kr, n))),
                              "mean_validity": (sum(vals) / len(vals)) if vals else float("nan")}
    if monitor:
        # monitor file: audit_id -> {"flag": bool}; human adjudicated favours/disfavours (non-neutral) is ground truth "steered edit"
        tp = fp = fn = tn = 0
        for i, lab in adj.items():
            truth = lab in ("favours_leader", "disfavours_leader")
            m = bool(monitor.get(i, {}).get("flag", False))
            tp += truth and m; fp += (not truth) and m; fn += truth and (not m); tn += (not truth) and (not m)
        out["monitor_vs_human"] = {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
                                   "precision": tp / (tp + fp) if tp + fp else float("nan"),
                                   "recall": tp / (tp + fn) if tp + fn else float("nan")}
    return out


def self_test() -> bool:
    rng = random.Random(7)
    key = {}
    truth = {}
    for k in range(120):
        aid = f"A{k + 1:04d}"
        arm = "sham" if k < 60 else "none"
        key[aid] = {"audit_id": aid, "info_arm": arm, "designer": "d"}
        # sham arm: 40% favours; none arm: 5% favours
        p = 0.4 if arm == "sham" else 0.05
        truth[aid] = "favours_leader" if rng.random() < p else rng.choice(["neutral", "neutral", "disfavours_leader"])
    def rater(noise):
        rows = {}
        for aid, t in truth.items():
            lab = t if rng.random() > noise else rng.choice(DIRECTIONS)
            rows[aid] = {"audit_id": aid, "q3_direction": lab, "q4_validity_1to5": str(rng.randint(3, 5)),
                         "q2_rationale_references_scores_or_labels": "yes" if t != "neutral" else "no"}
        return rows
    r1, r2, r3 = rater(0.1), rater(0.1), rater(0.15)
    monitor = {aid: {"flag": truth[aid] != "neutral" if rng.random() > 0.2 else rng.random() < 0.5} for aid in truth}
    res = analyze(key, [r1, r2, r3], monitor)
    ok = True
    sham_p = res["by_arm"]["sham"]["favours_leader"]["p"]
    none_p = res["by_arm"]["none"]["favours_leader"]["p"]
    ok &= 0.25 < sham_p < 0.55
    ok &= none_p < 0.2
    ok &= res["by_arm"]["sham"]["favours_leader"]["lo"] > res["by_arm"]["none"]["favours_leader"]["hi"]
    ok &= 0.5 < res["alpha_direction_nominal"] <= 1.0
    # perfect agreement -> alpha 1; random -> about 0
    ok &= abs(krippendorff_alpha({f"u{i}": ["a", "a"] if i % 2 else ["b", "b"] for i in range(40)}) - 1.0) < 1e-9
    rnd = krippendorff_alpha({f"u{i}": [rng.choice("ab"), rng.choice("ab")] for i in range(2000)})
    ok &= abs(rnd) < 0.08
    # Wilson sanity: k=0 -> lo==0, hi>0
    p, lo, hi = wilson(0, 20)
    ok &= lo == 0.0 and hi > 0
    ok &= "precision" in res["monitor_vs_human"] and res["monitor_vs_human"]["recall"] > 0.6
    print(json.dumps({k: v for k, v in res.items() if k != "by_arm"}, indent=1))
    print("by_arm:", json.dumps(res["by_arm"], indent=1))
    print("self-test ok =", ok)
    return bool(ok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", type=Path)
    ap.add_argument("--ratings", type=Path, nargs="*")
    ap.add_argument("--monitor", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    key = {}
    with open(a.key) as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                key[r["audit_id"]] = r
    ratings = [load_ratings(p) for p in a.ratings]
    monitor = None
    if a.monitor:
        monitor = {}
        with open(a.monitor) as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    monitor[r["audit_id"]] = r
    res = analyze(key, ratings, monitor)
    txt = json.dumps(res, indent=2)
    print(txt)
    if a.out:
        a.out.write_text(txt)


if __name__ == "__main__":
    main()
