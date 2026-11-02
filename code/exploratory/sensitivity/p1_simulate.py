"""Part 1 (EXPLORATORY): designer-independent positive control for the primary Psi -- simulated 'partial followers'.

Usage: python p1_simulate.py <pool>  ->  p1_paths_<pool>.npz

Starting points: every valid sham/blinded benchmark (exactly the primary's rows: n 60/55/60, 12 designers per pool),
with its real items, real weights (weighted_accuracy sessions) and its real per-item panel outcomes
(results/item_outcomes.jsonl: edited items carry their live re-score).  At k = 0 the recomputed scores reproduce
produced_scores (checked; max abs error printed and saved).

Each session then follows three swap paths of up to KMAX single swaps (one item out, one pool item in, weight 1;
pool item outcomes = reference_item_outcomes.jsonl, i.e. the same 5 precomputed samples that score every benchmark;
candidates are pool items not in the current draft with a sample for all 13 displayed keys):

  greedy  : best-improvement swap on tau-b(produced, displayed order) over the 13 displayed keys; ties in tau (tau is
            discrete) broken by a smooth surrogate mean_p tanh(margin_p / 0.01) over the 78 display-ordered pairs,
            objective = tau + 0.002 * surrogate (lexicographic in practice).  All 100 out-items x the 300 in-candidates
            with the highest priority sum_p sech^2(margin_p / 0.02) * (a_c,hi - a_c,lo) are evaluated exactly each step.
            Stops early (state held) if no swap improves the objective.  This is an efficient follower: per swap it is
            close to the best a steering designer could do, so it gives a LOWER bound on the k needed.
  naive   : static item-level follower: per-item concordance c_i = mean over display-ordered pairs of
            sign(a_i,hi - a_i,lo); swap k removes the k-th least concordant original item and adds the k-th most
            concordant pool item.  A less efficient but plausible 'prefer items that agree with the scoreboard' rule.
  random  : remove a uniformly random current item, add a uniformly random candidate (R = 20 independent paths;
            replicate 0 is the one given full inference).

Saved per session and k (0..KMAX): the 13 displayed-key scores in display order.
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict

import numpy as np

from scommon import K13, OUT, UNB, bench_rows, read_jsonl, sham_blinded

KMAX = 50
R_RANDOM = 20
N_CAND = 300


def main(pool):
    t0 = time.time()
    rows = sham_blinded(bench_rows(pool))
    sids = {r["session_id"] for r in rows}
    # reference per-item accuracy over K13
    ref = read_jsonl(UNB / f"WORK_{pool}" / "results" / "reference_item_outcomes.jsonl")
    items = sorted({r["item_id"] for r in ref})
    ii = {x: i for i, x in enumerate(items)}
    kk = {k: j for j, k in enumerate(K13)}
    A = np.full((len(items), 13), np.nan)
    for r in ref:
        if r["model_key"] in kk and r["n_samples"] > 0:
            A[ii[r["item_id"]], kk[r["model_key"]]] = r["n_correct"] / r["n_samples"]
    cand_ok = ~np.isnan(A).any(1)
    # session item outcomes
    io = defaultdict(dict)
    with open(UNB / f"WORK_{pool}" / "results" / "item_outcomes.jsonl") as f:
        for line in f:
            if '"session_id"' not in line:
                continue
            o = __import__("json").loads(line)
            if o["session_id"] in sids and o["model_key"] in kk:
                io[o["session_id"]][(o["item_id"], o["model_key"])] = (o["n_correct"], o["n_samples"])
    iu, ju = np.triu_indices(13, 1)
    rng = np.random.default_rng({"factual": 101, "math": 202, "code": 303}[pool])
    out_g, out_n, out_r, meta, repro = [], [], [], [], []
    for s_i, r in enumerate(rows):
        disp = list(r["displayed_order"])
        assert sorted(disp) == sorted(K13)
        col = np.array([kk[k] for k in disp])            # display position -> K13 column
        Ad = A[:, col]                                   # pool accuracies in display order
        its = list(r["items"])
        w0 = np.array([float(r["weights"].get(x, 1.0)) if r["scoring_rule"] == "weighted_accuracy" else 1.0 for x in its])
        B = np.full((len(its), 13), np.nan)
        for a, x in enumerate(its):
            for p, k in enumerate(disp):
                c, n = io[r["session_id"]].get((x, k), (0, 0))
                if n > 0:
                    B[a, p] = c / n
        def scores_of(Bm, w):
            m = ~np.isnan(Bm)
            return np.nansum(Bm * w[:, None], 0) / (m * w[:, None]).sum(0)
        s0 = scores_of(B, w0)
        repro.append(float(np.max(np.abs(s0 - np.array([r["produced_scores"][k] for k in disp])))))
        in_bench0 = np.zeros(len(items), bool)
        for x in its:
            if x in ii:
                in_bench0[ii[x]] = True

        # ---------------- greedy tau follower ----------------
        Bg, wg, inb = B.copy(), w0.copy(), in_bench0.copy()
        traj = [s0]
        cur_obj = None
        for k in range(KMAX):
            m = ~np.isnan(Bg)
            num = np.nansum(Bg * wg[:, None], 0); den = (m * wg[:, None]).sum(0)
            s = num / den
            marg = s[iu] - s[ju]
            if cur_obj is None:
                sg = np.sign(marg); nt = np.sum(sg == 0)
                cur_obj = sg.sum() / np.sqrt((78 - nt) * 78) + 0.002 * np.mean(np.tanh(marg / 0.01))
            need = 1.0 / np.cosh(marg / 0.02) ** 2
            cidx = np.flatnonzero(cand_ok & ~inb)
            pri = (Ad[cidx][:, iu] - Ad[cidx][:, ju]) @ need
            cidx = cidx[np.argsort(-pri)[:N_CAND]]
            wa_out = np.where(m, Bg, 0.0) * wg[:, None]              # (100, 13)
            wm_out = m * wg[:, None]
            numn = num[None, None, :] - wa_out[:, None, :] + Ad[cidx][None, :, :]
            denn = den[None, None, :] - wm_out[:, None, :] + 1.0
            sn = (numn / denn).astype(np.float64)
            dn = sn[..., iu] - sn[..., ju]                           # (100, C, 78)
            sgn = np.sign(dn)
            nt = np.sum(sgn == 0, axis=-1)
            tau = sgn.sum(-1) / np.sqrt((78 - nt) * 78.0)
            obj = tau + 0.002 * np.tanh(dn / 0.01).mean(-1)
            j, c = np.unravel_index(np.argmax(obj), obj.shape)
            if obj[j, c] <= cur_obj + 1e-12:
                traj.append(traj[-1]); continue
            cur_obj = obj[j, c]
            # apply swap
            Bg[j] = Ad[cidx[c]]; wg[j] = 1.0
            inb[cidx[c]] = True
            # removed item returns to the pool only if it is a pool item (edited items keep their id: allow re-entry
            # of the unedited pool version)
            traj.append(scores_of(Bg, wg))
        # track removed ids for re-entry: simpler rule -- removed items are NOT re-admitted (inb stays True); the
        # greedy path never re-adds an item it just judged worst, so this only removes a degenerate option.
        out_g.append(np.array(traj))

        # ---------------- naive static concordance follower ----------------
        def conc(M):
            d = M[:, iu] - M[:, ju]
            return np.nanmean(np.sign(d), axis=1)
        c_b = conc(B)
        c_b = np.where(np.isnan(c_b), 0.0, c_b)
        rem = np.argsort(c_b, kind="stable")
        cidx = np.flatnonzero(cand_ok & ~in_bench0)
        add = cidx[np.argsort(-conc(Ad[cidx]), kind="stable")]
        Bn, wn = B.copy(), w0.copy()
        traj = [s0]
        for k in range(KMAX):
            Bn[rem[k]] = Ad[add[k]]; wn[rem[k]] = 1.0
            traj.append(scores_of(Bn, wn))
        out_n.append(np.array(traj))

        # ---------------- random swaps ----------------
        reps = []
        for rep in range(R_RANDOM):
            Br, wr, inr = B.copy(), w0.copy(), in_bench0.copy()
            traj = [s0]
            for k in range(KMAX):
                j = rng.integers(0, len(its))
                pool_c = np.flatnonzero(cand_ok & ~inr)
                c = pool_c[rng.integers(0, len(pool_c))]
                Br[j] = Ad[c]; wr[j] = 1.0; inr[c] = True
                traj.append(scores_of(Br, wr))
            reps.append(np.array(traj))
        out_r.append(np.array(reps))
        meta.append((r["session_id"], r["designer"], "|".join(disp)))
        if s_i % 10 == 0:
            print(pool, s_i, f"{time.time()-t0:.0f}s", "repro", repro[-1], flush=True)
    np.savez_compressed(OUT / f"p1_paths_{pool}.npz", greedy=np.array(out_g), naive=np.array(out_n),
                        random=np.array(out_r), session_id=np.array([m[0] for m in meta]),
                        designer=np.array([m[1] for m in meta]), display=np.array([m[2] for m in meta]),
                        repro_max_abs=np.array(repro))
    print(pool, "done", f"{time.time()-t0:.0f}s", "max repro err", max(repro))


if __name__ == "__main__":
    main(sys.argv[1])
