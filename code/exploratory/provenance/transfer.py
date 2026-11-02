"""Cross-arm transfer of the provenance classifier (EXPLORATORY): is the designer signature the same with and
without score access?  Train on one set of sessions, test on a disjoint set:
  none->sham_blinded      train none/blinded, test sham/blinded
  rest->sham_blinded      train every valid session except sham/blinded, test sham/blinded
Feature sets and models as in classify.py (TF-IDF fit unsupervised on the union of train and test documents).
CI: 2,000 bootstrap resamples of test sessions stratified by designer; p: exact one-sided binomial test vs 1/12
(each test session is an independent prediction from a fixed trained model).
"""
from __future__ import annotations

import json

import numpy as np
from scipy.stats import binomtest

from classify import FSETS, features, model
from common import DEV, OUT, POOLS, bench_rows, cell

rng = np.random.default_rng(11)


def boot(v, strat, n=2000):
    groups = [np.where(strat == s)[0] for s in np.unique(strat)]
    bs = [np.mean(v[np.concatenate([rng.choice(g, len(g)) for g in groups])]) for _ in range(n)]
    return [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]


def main():
    res = {}
    for pool in POOLS:
        allR = bench_rows(pool)
        for name, trf in {"none->sham_blinded": lambda r: cell(r) == "none/blinded",
                          "rest->sham_blinded": lambda r: cell(r) != "sham/blinded"}.items():
            tr = [r for r in allR if trf(r)]
            te = [r for r in allR if cell(r) == "sham/blinded"]
            F = features(pool, tr + te)
            y = np.array([r["designer"] for r in tr + te])
            itr, ite = np.arange(len(tr)), np.arange(len(tr), len(tr) + len(te))
            for fs in FSETS:
                X = F[fs]
                pred = model(fs).fit(X[itr], y[itr]).predict(X[ite])
                c = (pred == y[ite]).astype(float)
                cd = np.array([DEV[a] == DEV[b] for a, b in zip(pred, y[ite])], float)
                res[f"{pool}|{name}|{fs}"] = {"acc": float(c.mean()), "ci": boot(c, y[ite]), "n_test": int(len(te)), "n_train": int(len(tr)),
                                              "binom_p_vs_1_12": float(binomtest(int(c.sum()), len(c), 1 / 12, alternative="greater").pvalue),
                                              "collapsed_dev_acc": float(cd.mean()), "collapsed_dev_ci": boot(cd, y[ite])}
                print(pool, name, fs, round(c.mean(), 3), round(cd.mean(), 3), flush=True)
    (OUT / "transfer_results.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
