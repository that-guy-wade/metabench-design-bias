"""Part 3 (EXPLORATORY): held-out model redistribution statistic (run/OUTSIDE_CHECKS.md section 3).

Usage: python p3_heldout.py  ->  p3_results.json

Ranking set (primary): the 12 designer models + the 4 held-outs = 16 distinct panel configurations.  The placebo is left
out because it is an identical copy of sonnet55 (it would count one configuration twice); OUTSIDE_CHECKS ranks the
held-outs "among all 12 models" of the pilot panel, i.e. among every distinct displayed configuration plus the
held-outs.  Sensitivity: 17 keys (placebo included).  Rank 1 = best, ties averaged.

Per benchmark: H = mean rank of the 4 held-outs.  Statistic: for each designer, mean H over its valid benchmarks in the
test cell minus mean H over its valid none/blinded benchmarks (same pool); averaged over designers.  Positive = held-outs
pushed DOWN (predicted sign under steering).  CI: designer-cluster bootstrap (designers resampled; test and none
benchmarks resampled separately within designer; pooled = designer across pools, each pool's benchmarks against its own
pool's none baseline, resampled within designer x pool), 10,000 draws.

Cells: sham/blinded (the pre-specified one), all sham (three identity arms), inverted, true_blinded, narrative.
Displayed-leader rank gain in the same 16-key set is reported alongside (designer's none-arm mean rank of the leader
minus its rank in the cell; placebo leader -> placebo takes sonnet55's slot), because the pre-registered prediction is
that the held-out shift has the same sign as the leader gain.
Instructed arm: same statistic split by the judge label in analysis/controls/q1_sessions.jsonl ('judge' = the labels
behind the +1.44 complier gain; 'judge_corrected' = with the analyst's manual corrections), plus the target's 16-key rank
gain and the shift a pure redistribution would imply for the held-outs: if the target gains g ranks and the loss is
spread evenly over the other 15 configurations, each held-out falls g/15.
"""
from __future__ import annotations

import json
from collections import defaultdict

import numpy as np

from scommon import OUT, POOLS, DESIGNERS, HELDOUT, PLACEBO, ROOT, bench_rows, avg_rank, dump

NB = 10000
K16 = DESIGNERS + HELDOUT
K17 = DESIGNERS + [PLACEBO] + HELDOUT


def keyset(keys, target=None):
    """Rank set with the placebo standing in for sonnet55 when the target is the placebo."""
    if target == PLACEBO and PLACEBO not in keys:
        return [PLACEBO if k == "sonnet55" else k for k in keys]
    return keys


def H(r, keys):
    v = np.array([r["produced_scores"][k] for k in keys])
    return float(np.mean([avg_rank(v, keys.index(h)) for h in HELDOUT]))


def rank_of(r, keys, t):
    v = np.array([r["produced_scores"][k] for k in keys])
    return avg_rank(v, keys.index(t))


def boot_diff(test, base, n_boot=NB, seed=0):
    """test/base: designer -> list of (pool, value). Designer-averaged mean(test) - mean(base) per designer."""
    rng = np.random.default_rng(seed)
    ds = [d for d in test if test[d] and base.get(d)]

    def designer_value(d, resample):
        bt = defaultdict(list); bb = defaultdict(list)
        for p, v in test[d]:
            bt[p].append(v)
        for p, v in base[d]:
            bb[p].append(v)
        diffs, wts = [], []
        for p in bt:
            if p not in bb:
                continue
            t = np.asarray(bt[p]); b = np.asarray(bb[p])
            if resample:
                t = t[rng.integers(0, len(t), len(t))]; b = b[rng.integers(0, len(b), len(b))]
            diffs.append(t.mean() - b.mean()); wts.append(len(bt[p]))
        return float(np.average(diffs, weights=wts))

    est = float(np.mean([designer_value(d, False) for d in ds]))
    bs = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.choice(ds, size=len(ds), replace=True)
        bs[b] = np.mean([designer_value(d, True) for d in pick])
    return {"est": est, "ci95": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
            "n_test": int(sum(len(test[d]) for d in ds)), "n_base": int(sum(len(base[d]) for d in ds)), "D": len(ds),
            "per_designer": {d: designer_value(d, False) for d in ds}}


def boot_mean(by_d, n_boot=NB, seed=0):
    rng = np.random.default_rng(seed)
    ds = [d for d in by_d if by_d[d]]
    arr = {d: np.asarray(by_d[d], float) for d in ds}
    est = float(np.mean([arr[d].mean() for d in ds]))
    bs = [np.mean([arr[d][rng.integers(0, len(arr[d]), len(arr[d]))].mean() for d in rng.choice(ds, len(ds))])
          for _ in range(n_boot)]
    return {"est": est, "ci95": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
            "n": int(sum(len(arr[d]) for d in ds)), "D": len(ds)}


def main():
    q1 = {}
    with open(ROOT / "analysis" / "controls" / "q1_sessions.jsonl") as f:
        for l in f:
            s = json.loads(l)
            q1[s["session_id"]] = s
    rows = {p: bench_rows(p) for p in POOLS}
    out = {"n_boot": NB, "rank_set_primary": K16, "rank_set_sensitivity": K17}
    cells = {"sham_blinded": lambda r: r["info_arm"] == "sham" and r["identity_arm"] == "blinded",
             "sham_all_identity": lambda r: r["info_arm"] == "sham",
             "inverted": lambda r: r["info_arm"] == "inverted",
             "true_blinded": lambda r: r["info_arm"] == "true_blinded",
             "narrative": lambda r: r["info_arm"] == "narrative"}
    for kname, keys in (("16", K16), ("17", K17)):
        o = {}
        for scope in POOLS + ["pooled"]:
            pools = POOLS if scope == "pooled" else [scope]
            base = defaultdict(list)
            base_rank = defaultdict(lambda: defaultdict(list))
            for p in pools:
                for r in rows[p]:
                    if r["info_arm"] == "none" and r["identity_arm"] == "blinded":
                        base[r["designer"]].append((p, H(r, keys)))
                        for t in DESIGNERS + [PLACEBO]:
                            ks = keyset(keys, t)
                            base_rank[(r["designer"], p)][t].append(rank_of(r, ks, t))
            oc = {}
            for cname, f in cells.items():
                test = defaultdict(list)
                lg = defaultdict(list)
                for p in pools:
                    for r in rows[p]:
                        if not f(r):
                            continue
                        test[r["designer"]].append((p, H(r, keys)))
                        L = r.get("displayed_leader")
                        if L:
                            ks = keyset(keys, L)
                            lg[r["designer"]].append(np.mean(base_rank[(r["designer"], p)][L]) - rank_of(r, ks, L))
                oc[cname] = {"heldout_mean_rank_minus_none": boot_diff(test, base, seed=1),
                             "displayed_leader_rank_gain": boot_mean(lg, seed=2) if lg else None}
            # per held-out model, sham/blinded
            per_h = {}
            for h in HELDOUT:
                test = defaultdict(list); bh = defaultdict(list)
                for p in pools:
                    for r in rows[p]:
                        v = np.array([r["produced_scores"][k] for k in keys])
                        x = avg_rank(v, keys.index(h))
                        if r["info_arm"] == "none" and r["identity_arm"] == "blinded":
                            bh[r["designer"]].append((p, x))
                        elif cells["sham_blinded"](r):
                            test[r["designer"]].append((p, x))
                per_h[h] = boot_diff(test, bh, n_boot=2000, seed=3)
                per_h[h].pop("per_designer")
            oc["sham_blinded_per_heldout"] = per_h
            # instructed
            ins = {}
            for lab_field in ("judge", "judge_corrected"):
                for lab in ("COMPLIED", "REFUSED", "PARTIAL_AMBIGUOUS", "ALL"):
                    test = defaultdict(list); tg = defaultdict(list)
                    for p in pools:
                        for r in rows[p]:
                            if r["info_arm"] != "instructed":
                                continue
                            s = q1[r["session_id"]]
                            if lab != "ALL" and s[lab_field] != lab:
                                continue
                            t = r["target_model"]
                            ks = keyset(keys, t)
                            test[r["designer"]].append((p, H(r, ks)))
                            tg[r["designer"]].append(np.mean(base_rank[(r["designer"], p)][t]) - rank_of(r, ks, t))
                    if not test:
                        continue
                    hd = boot_diff(test, base, seed=4)
                    tgs = boot_mean(tg, seed=5)
                    n_other = len(keys) - 1
                    ins[f"{lab_field}:{lab}"] = {"heldout_mean_rank_minus_none": hd, "target_rank_gain": tgs,
                                                 "pure_redistribution_expected_heldout_shift": tgs["est"] / n_other}
            oc["instructed"] = ins
            o[scope] = oc
            sb = oc["sham_blinded"]
            print(kname, scope, "sham/blinded H", round(sb["heldout_mean_rank_minus_none"]["est"], 3),
                  sb["heldout_mean_rank_minus_none"]["ci95"], "leader", round(sb["displayed_leader_rank_gain"]["est"], 3),
                  "| complied H", round(ins["judge:COMPLIED"]["heldout_mean_rank_minus_none"]["est"], 3),
                  ins["judge:COMPLIED"]["heldout_mean_rank_minus_none"]["ci95"],
                  "target", round(ins["judge:COMPLIED"]["target_rank_gain"]["est"], 3), flush=True)
        out[f"keys{kname}"] = o
    dump(out, OUT / "p3_results.json")


if __name__ == "__main__":
    main()
