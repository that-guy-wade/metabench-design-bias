"""PREREG section 12 provenance classifier, EXPLORATORY. Usage: classify.py <pool>  -> classify_<pool>.json

Predict the designer (12 classes) and the developer (4 classes) of a produced T1 benchmark from what it selected.
Unit = one valid session (benchmark). Subsets: all valid sessions, none/blinded, sham/blinded.

Feature sets (all computed from the 100 submitted item ids; edited wording is ignored, pool text is used):
  tfidf      TF-IDF (sublinear tf, unigrams, min_df=2, max_df=0.95) over the concatenated pool `question` text of the
             100 items. The vectorizer is fit on the documents of the subset without labels (unsupervised; IDF only).
  items      binary bag of item ids (2,000 columns).
  mix        category proportions + source proportions.
  difficulty mean reference accuracy of the items (mean over the 12 designer keys of n_correct/n_samples on the full
             pool, as in analysis/reconcile) + category proportions. The prereg-requested 'difficulty-only' baseline.
  diffprof   difficulty distribution (mean, sd, 10-bin histogram of item reference accuracy) + category proportions.
  listpos    browse-depth only: mean, sd and 10-bin histogram of each item's position in the order list_items shows
             (sorted pool ids, which is the interface's listing order); no content at all.
Model: multinomial logistic regression, L2, fixed C (C=10 for the sparse sets tfidf/items, C=1 after standardisation
for the dense sets), prespecified, never tuned on test folds; lbfgs, max_iter 3000.
CV: StratifiedGroupKFold(5, shuffle) stratified by the target, groups = session_id (each session is one row, so no
session is ever in train and test), repeated with seeds 0..4. Per-session score = share of the 5 repeats in which the
out-of-fold prediction was correct; accuracy = mean of that.
Uncertainty: 95% CI from 2,000 bootstrap resamples of sessions stratified by designer (test-sample uncertainty only);
permutation test with N_PERM label permutations (labels shuffled across sessions, one CV repeat each, full refit):
p = (1 + #{null >= observed}) / (1 + N_PERM). Developer accuracy: (i) 12-class predictions collapsed to developer,
(ii) a direct 4-class classifier.
"""
from __future__ import annotations

import json
import sys
import warnings

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from common import DESIGNERS, DEV, K13, OUT, bench_rows, cell, load_pool, reference_matrix

warnings.filterwarnings("ignore")
N_REP, N_BOOT, N_PERM = 5, 2000, 100
SUBSETS = {"all": lambda r: True, "none_blinded": lambda r: cell(r) == "none/blinded",
           "sham_blinded": lambda r: cell(r) == "sham/blinded"}
FSETS = ["tfidf", "items", "mix", "difficulty", "diffprof", "listpos"]
DEVS = ["Anthropic", "OpenAI", "Google", "xAI"]


def features(pool, R):
    P = load_pool(pool)
    ids = sorted(P)
    pos = {i: k for k, i in enumerate(ids)}
    items, ii, A = reference_matrix(pool, K13)
    acc = {i: float(np.nanmean(A[ii[i], :12])) for i in items}
    cats = sorted({it["category"] for it in P.values()})
    srcs = sorted({it["source"] for it in P.values()})
    F = {}
    F["tfidf"] = TfidfVectorizer(sublinear_tf=True, min_df=2, max_df=0.95).fit_transform(
        ["\n".join(P[i]["question"] for i in r["items"]) for r in R])
    rows, cols = [], []
    for a, r in enumerate(R):
        for i in r["items"]:
            rows.append(a); cols.append(pos[i])
    F["items"] = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(R), len(ids)))
    catm = np.array([[sum(P[i]["category"] == c for i in r["items"]) / len(r["items"]) for c in cats] for r in R])
    srcm = np.array([[sum(P[i]["source"] == s for i in r["items"]) / len(r["items"]) for s in srcs] for r in R])
    F["mix"] = np.hstack([catm, srcm])
    a_ = [np.array([acc[i] for i in r["items"]]) for r in R]
    F["difficulty"] = np.hstack([np.array([[x.mean()] for x in a_]), catm])
    F["diffprof"] = np.hstack([np.array([[x.mean(), x.std()] + list(np.histogram(x, bins=10, range=(0, 1))[0] / len(x)) for x in a_]), catm])
    p_ = [np.array([pos[i] / len(ids) for i in r["items"]]) for r in R]
    F["listpos"] = np.array([[x.mean(), x.std()] + list(np.histogram(x, bins=10, range=(0, 1))[0] / len(x)) for x in p_])
    return F


def model(fs):
    if fs in ("tfidf", "items"):
        return LogisticRegression(C=10, max_iter=3000)
    return make_pipeline(StandardScaler(), LogisticRegression(C=1, max_iter=3000))


def cv_pred(X, y, groups, seed, fs):
    pred = np.empty(len(y), dtype=object)
    for tr, te in StratifiedGroupKFold(5, shuffle=True, random_state=seed).split(X, y, groups):
        m = model(fs).fit(X[tr], y[tr])
        pred[te] = m.predict(X[te])
    return pred


def boot_ci(score, strat, rng):
    idx_by = {s: np.where(strat == s)[0] for s in np.unique(strat)}
    bs = np.empty(N_BOOT)
    for b in range(N_BOOT):
        idx = np.concatenate([rng.choice(v, len(v)) for v in idx_by.values()])
        bs[b] = score[idx].mean()
    return [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]


def run(X, y, groups, strat, fs, rng, labels):
    preds = [cv_pred(X, y, groups, s, fs) for s in range(N_REP)]
    corr = np.mean([p == y for p in preds], axis=0)
    out = {"acc": float(corr.mean()), "ci": boot_ci(corr, strat, rng), "n": int(len(y)),
           "per_session_correct": corr.tolist(), "pred_rep0": [str(x) for x in preds[0]],
           "confusion_sum5": confusion_matrix(np.concatenate([y] * N_REP), np.concatenate(preds), labels=labels).tolist(),
           "labels": labels, "majority_rate": float(max(np.mean(y == l) for l in labels))}
    null = []
    for k in range(N_PERM):
        yp = rng.permutation(y)
        null.append(float(np.mean(cv_pred(X, yp, groups, 1000 + k, fs) == yp)))
    null = np.array(null)
    out.update(null_mean=float(null.mean()), null_p95=float(np.percentile(null, 95)),
               perm_p=float((1 + np.sum(null >= out["acc"])) / (1 + N_PERM)), null=null.tolist())
    if labels == DESIGNERS or set(labels) <= set(DESIGNERS):
        dev_corr = np.mean([[DEV[a] == DEV[b] for a, b in zip(p, y)] for p in preds], axis=0)
        out["collapsed_dev_acc"] = float(dev_corr.mean())
        out["collapsed_dev_ci"] = boot_ci(dev_corr, strat, rng)
        out["collapsed_dev_per_session"] = dev_corr.tolist()
    return out


def main(pool, subsets=None, fsets=None, part=None):
    """subsets/fsets/part: optional split of the work across processes (code pool); merge with merge_parts()."""
    rng = np.random.default_rng({"factual": 1, "math": 2, "code": 3}[pool] + (0 if part is None else 100 * (part + 1)))
    allR = bench_rows(pool)
    res = {}
    for sname, f in SUBSETS.items():
        if subsets and sname not in subsets:
            continue
        R = [r for r in allR if f(r)]
        F = features(pool, R)
        y = np.array([r["designer"] for r in R])
        yd = np.array([DEV[d] for d in y])
        groups = np.array([r["session_id"] for r in R])
        labs = [d for d in DESIGNERS if d in set(y)]
        res[sname] = {"session_ids": groups.tolist(), "designers": y.tolist(),
                      "n_per_designer": {d: int(np.sum(y == d)) for d in labs}}
        for fs in FSETS:
            if fsets and fs not in fsets:
                continue
            X = F[fs]
            res[sname][f"{fs}|designer"] = run(X, y, groups, y, fs, rng, labs)
            res[sname][f"{fs}|developer"] = run(X, yd, groups, y, fs, rng, [d for d in DEVS if d in set(yd)])
            print(pool, sname, fs, round(res[sname][f"{fs}|designer"]["acc"], 3),
                  round(res[sname][f"{fs}|developer"]["acc"], 3), flush=True)
    (OUT / (f"classify_{pool}.json" if part is None else f"classify_{pool}.part{part}.json")).write_text(json.dumps(res))


def merge_parts(pool, n):
    res = {}
    for k in range(n):
        for sname, d in json.loads((OUT / f"classify_{pool}.part{k}.json").read_text()).items():
            res.setdefault(sname, {}).update(d)
    (OUT / f"classify_{pool}.json").write_text(json.dumps(res))


if __name__ == "__main__":
    # classify.py <pool>                                    (whole pool, one process)
    # classify.py <pool> <part> <subsets,..|*> <fsets,..|*> (one part);  classify.py <pool> merge <n_parts>
    if len(sys.argv) == 2:
        main(sys.argv[1])
    elif sys.argv[2] == "merge":
        merge_parts(sys.argv[1], int(sys.argv[3]))
    else:
        sp = lambda a: None if a == "*" else a.split(",")
        main(sys.argv[1], sp(sys.argv[3]), sp(sys.argv[4]), int(sys.argv[2]))
