"""Measurement model of PREREGISTRATION section 8 (DECISIONS D18-D25, D27).

logit P(y_{b,i,m}) = theta_m + beta_i + gamma*Target_{b,m} + sum_c delta_c*Target_{b,m}*Cond_{b,c} + u_b
with random slopes of Target and Target x Cond by designer and by evaluee. Fitted by a Laplace approximation with an
EM-type fixed point for the variance components (own implementation, sparse design matrices). The pre-registered
fallback (pooled GLM with item fixed effects and session-clustered sandwich SEs) is always fitted alongside.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp
from scipy.linalg import cho_factor, cho_solve
from scipy.stats import norm

from .load import Dataset
from .stats import bh_reject, percentile_ci

ETS = 2.35
RIDGE = 1e-8          # negligible ridge on fixed effects for numerical stability (D22)
COMP_NAMES = ["benchmark", "designer_x_target", "designer_x_target_x_cond", "evaluee_x_target", "evaluee_x_target_x_cond"]


@dataclass
class ModelData:
    y: np.ndarray
    n: np.ndarray
    X: sp.csr_matrix
    Z: sp.csr_matrix
    comp: np.ndarray                 # variance component index per Z column
    cluster: np.ndarray              # session cluster per row (anchor = its own cluster)
    fixed_names: list[str]
    conds: list[str]
    i_gamma: int
    i_delta: list[int]               # columns of the C-1 deviation-coded delta terms
    n_items: int
    n_models: int
    n_bench: int
    dropped_items: int
    target_rows: np.ndarray          # row indices with Target = 1
    target_bench: np.ndarray         # benchmark index for those rows
    target_cond: np.ndarray          # condition index for those rows
    target_item: np.ndarray
    bench_info: list[dict]


def build(ds: Dataset, max_rows: int | None = None) -> ModelData:
    benches = sorted(ds.valid, key=lambda b: b.session_id)
    b_index = {b.session_id: i for i, b in enumerate(benches)}
    conds = sorted({b.info_arm for b in benches if b.target})
    c_index = {c: i for i, c in enumerate(conds)}
    designers = sorted({b.designer for b in benches})
    d_index = {d: i for i, d in enumerate(designers)}
    models = list(ds.panel_keys)
    m_index = {m: i for i, m in enumerate(models)}

    sid_l, item_l, model_l, y_l, n_l = [], [], [], [], []
    for sid, iid, mk, yc, ns in list(ds.reference_outcomes()) + list(ds.item_outcomes()):
        if ns <= 0 or mk not in m_index:
            continue
        sid_l.append(sid); item_l.append(iid); model_l.append(m_index[mk]); y_l.append(yc); n_l.append(ns)
    y = np.array(y_l, float); n = np.array(n_l, float); model = np.array(model_l, int)
    items = sorted(set(item_l))
    it_index = {k: i for i, k in enumerate(items)}
    item = np.array([it_index[k] for k in item_l], int)
    # drop items with no information under item fixed effects (all correct or all wrong everywhere) (D22)
    tot_y = np.bincount(item, weights=y, minlength=len(items)); tot_n = np.bincount(item, weights=n, minlength=len(items))
    keep_item = (tot_y > 0) & (tot_y < tot_n)
    keep = keep_item[item]
    dropped = int((~keep_item).sum())
    y, n, model, item = y[keep], n[keep], model[keep], item[keep]
    sid_arr = np.array(sid_l)[keep]
    kept_items = [k for k in items if keep_item[it_index[k]]]
    re_index = {it_index[k]: j for j, k in enumerate(kept_items)}
    item = np.array([re_index[i] for i in item], int)
    I, M, B, C, D = len(kept_items), len(models), len(benches), len(conds), len(designers)
    R = len(y)
    bench = np.array([b_index.get(s, -1) for s in sid_arr], int)
    is_b = bench >= 0
    target_flag = np.zeros(R)
    cond_of_row = np.full(R, -1, int)
    designer_of_row = np.full(R, -1, int)
    for i, b in enumerate(benches):
        rows = np.nonzero(bench == i)[0]
        designer_of_row[rows] = d_index[b.designer]
        t = b.target
        if t and t in m_index:
            tr = rows[model[rows] == m_index[t]]
            target_flag[tr] = 1.0
            cond_of_row[tr] = c_index[b.info_arm]
    rows_idx = np.arange(R)
    # ---- fixed design: intercept, model dummies (drop first), item dummies (drop first), Target, Target x Cond (deviation)
    cols, vals, names = [np.zeros(R, int)], [np.ones(R)], ["intercept"]
    off = 1
    mm = model > 0
    cols.append(off + model[mm] - 1); vals.append(np.ones(mm.sum())); names += [f"theta[{m}]" for m in models[1:]]
    r_parts = [rows_idx, rows_idx[mm]]
    off += M - 1
    im = item > 0
    cols.append(off + item[im] - 1); vals.append(np.ones(im.sum())); names += [f"beta[{k}]" for k in kept_items[1:]]
    r_parts.append(rows_idx[im])
    off += I - 1
    i_gamma = off
    tm = target_flag > 0
    cols.append(np.full(tm.sum(), i_gamma)); vals.append(np.ones(tm.sum())); names.append("gamma"); r_parts.append(rows_idx[tm])
    off += 1
    i_delta = []
    for k in range(C - 1):
        v = np.where(cond_of_row[tm] == k, 1.0, np.where(cond_of_row[tm] == C - 1, -1.0, 0.0))
        nz = v != 0
        cols.append(np.full(nz.sum(), off)); vals.append(v[nz]); r_parts.append(rows_idx[tm][nz])
        names.append(f"delta[{conds[k]}]"); i_delta.append(off); off += 1
    X = sp.csr_matrix((np.concatenate(vals), (np.concatenate(r_parts), np.concatenate(cols))), shape=(R, off))
    # ---- random design
    zc, zv, zr, comp = [], [], [], []
    zoff = 0
    zc.append(zoff + bench[is_b]); zv.append(np.ones(is_b.sum())); zr.append(rows_idx[is_b]); comp += [0] * B; zoff += B
    tr = rows_idx[tm]
    zc.append(zoff + designer_of_row[tr]); zv.append(np.ones(len(tr))); zr.append(tr); comp += [1] * D; zoff += D
    zc.append(zoff + designer_of_row[tr] * C + cond_of_row[tr]); zv.append(np.ones(len(tr))); zr.append(tr); comp += [2] * (D * C); zoff += D * C
    zc.append(zoff + model[tr]); zv.append(np.ones(len(tr))); zr.append(tr); comp += [3] * M; zoff += M
    zc.append(zoff + model[tr] * C + cond_of_row[tr]); zv.append(np.ones(len(tr))); zr.append(tr); comp += [4] * (M * C); zoff += M * C
    Z = sp.csr_matrix((np.concatenate(zv), (np.concatenate(zr), np.concatenate(zc))), shape=(R, zoff))
    clusters = {s: i for i, s in enumerate(sorted(set(sid_arr)))}
    cluster = np.array([clusters[s] for s in sid_arr], int)
    info = [{"session_id": b.session_id, "info_arm": b.info_arm, "designer": b.designer, "target": b.target} for b in benches]
    return ModelData(y=y, n=n, X=X, Z=Z, comp=np.array(comp, int), cluster=cluster, fixed_names=names, conds=conds, i_gamma=i_gamma,
                     i_delta=i_delta, n_items=I, n_models=M, n_bench=B, dropped_items=dropped, target_rows=tr, target_bench=bench[tr],
                     target_cond=cond_of_row[tr], target_item=item[tr], bench_info=info)


# ----------------------------------------------------------------------------------------------- fitting

def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _penalised_newton(A: sp.csr_matrix, y: np.ndarray, n: np.ndarray, v0: np.ndarray, prec: np.ndarray, max_iter: int = 50, tol: float = 1e-8):
    """Maximise sum[y*eta - n*log(1+e^eta)] - 0.5*sum(prec*v^2); returns v, Cholesky of the Hessian, objective."""
    v = v0.copy()
    AT = A.T.tocsr()

    def objective(v):
        eta = A @ v
        return float(np.sum(y * eta - n * np.logaddexp(0.0, eta)) - 0.5 * np.sum(prec * v * v))

    f = objective(v)
    chol = None
    for it in range(max_iter):
        eta = A @ v
        p = _sigmoid(eta)
        g = AT @ (y - n * p) - prec * v
        w = n * p * (1 - p)
        H = (AT @ A.multiply(w[:, None]).tocsr()).toarray()
        H[np.diag_indices_from(H)] += prec
        chol = cho_factor(H, lower=True, check_finite=False)
        step = cho_solve(chol, g, check_finite=False)
        t = 1.0
        while True:
            v_new = v + t * step
            f_new = objective(v_new)
            if f_new >= f - 1e-10 or t < 1e-6:
                break
            t *= 0.5
        converged = abs(f_new - f) < tol * (1 + abs(f)) and np.max(np.abs(t * step)) < 1e-6
        v, f = v_new, f_new
        if converged:
            break
    eta = A @ v
    p = _sigmoid(eta)
    w = n * p * (1 - p)
    H = (AT @ A.multiply(w[:, None]).tocsr()).toarray()
    H[np.diag_indices_from(H)] += prec
    chol = cho_factor(H, lower=True, check_finite=False)
    return v, chol, f, H


def fit_mixed(md: ModelData, max_outer: int = 150, tol: float = 1e-2, min_var: float = 1e-8, scale_floor: float = 1e-2) -> dict:
    """Laplace fit with EM-type variance updates (D22). Each outer iteration takes one warm-started Newton step on
    (fixed effects, random effects) and then updates the variance components (a generalised-EM scheme with the same
    fixed point); a full Newton solve follows at the end. Convergence: max_c |new - old| / max(old, scale_floor) < tol,
    so components shrinking toward zero (below scale_floor = 0.01 on the variance scale, an SD of 0.1 log-odds) count
    as converged once their absolute change is below tol * scale_floor."""
    A = sp.hstack([md.X, md.Z]).tocsr()
    p, q = md.X.shape[1], md.Z.shape[1]
    n_comp = len(COMP_NAMES)
    q_c = np.bincount(md.comp, minlength=n_comp).astype(float)
    sigma2 = np.full(n_comp, 0.1)
    v = np.zeros(p + q)
    history = []
    converged = False
    for outer in range(max_outer):
        prec = np.concatenate([np.full(p, RIDGE), 1.0 / np.maximum(sigma2[md.comp], min_var)])
        v, chol, f, H = _penalised_newton(A, md.y, md.n, v, prec, max_iter=1 if outer > 0 else 50)
        Hinv = cho_solve(chol, np.eye(p + q), check_finite=False)
        dH = np.diag(Hinv)
        b = v[p:]
        new = np.zeros(n_comp)
        for c in range(n_comp):
            sel = md.comp == c
            new[c] = (np.sum(b[sel] ** 2) + np.sum(dH[p:][sel])) / max(q_c[c], 1.0) if q_c[c] > 0 else 0.0
        new = np.maximum(new, min_var)
        rel = float(np.max(np.abs(new - sigma2) / np.maximum(sigma2, scale_floor)))
        history.append({"iter": outer, "sigma2": [float(x) for x in new], "penalised_loglik": f, "rel_change": rel})
        sigma2 = new
        if rel < tol:
            converged = True
            break
    prec = np.concatenate([np.full(p, RIDGE), 1.0 / np.maximum(sigma2[md.comp], min_var)])
    v, chol, f, H = _penalised_newton(A, md.y, md.n, v, prec)
    Hinv = cho_solve(chol, np.eye(p + q), check_finite=False)
    cov_fixed = Hinv[:p, :p]
    return {"beta": v[:p], "cov": cov_fixed, "sigma2": {COMP_NAMES[c]: float(sigma2[c]) for c in range(n_comp)},
            "converged": converged, "n_outer": len(history), "history_tail": history[-3:], "penalised_loglik": f,
            "n_rows": int(len(md.y)), "n_fixed": p, "n_random": q}


def fit_glm_cluster(md: ModelData) -> dict:
    """Pre-registered fallback: pooled binomial GLM, item and evaluee fixed effects, session-clustered sandwich SEs (D23)."""
    p = md.X.shape[1]
    v, chol, f, H = _penalised_newton(md.X, md.y, md.n, np.zeros(p), np.full(p, RIDGE))
    Hinv = cho_solve(chol, np.eye(p), check_finite=False)
    eta = md.X @ v
    resid = md.y - md.n * _sigmoid(eta)
    G = int(md.cluster.max()) + 1
    Cmat = sp.csr_matrix((np.ones(len(md.cluster)), (md.cluster, np.arange(len(md.cluster)))), shape=(G, len(md.cluster)))
    S = (Cmat @ md.X.multiply(resid[:, None]).tocsr()).toarray()          # G x p cluster score sums
    meat = S.T @ S
    cov = Hinv @ meat @ Hinv * (G / max(G - 1, 1))
    return {"beta": v, "cov": cov, "cov_model_based": Hinv, "n_clusters": G, "loglik": f, "n_rows": int(len(md.y)), "n_fixed": p}


def fit_glm_no_dif(md: ModelData) -> np.ndarray:
    """No-DIF Rasch fit (gamma, delta = 0) for the item-level screen (D27); returns fitted probabilities."""
    keep = np.ones(md.X.shape[1], bool)
    keep[md.i_gamma] = False
    keep[md.i_delta] = False
    X0 = md.X[:, np.nonzero(keep)[0]]
    v, *_ = _penalised_newton(X0, md.y, md.n, np.zeros(X0.shape[1]), np.full(X0.shape[1], RIDGE))
    return _sigmoid(X0 @ v)


# ----------------------------------------------------------------------------------------------- reporting

def _coef_report(est: float, se: float) -> dict:
    lo, hi = est - 1.96 * se, est + 1.96 * se
    delta = ETS * est
    cat = "A" if abs(delta) < 1.0 else ("B" if abs(delta) < 1.5 else "C")
    return {"log_odds": float(est), "se": float(se), "ci95_log_odds": [float(lo), float(hi)], "z": float(est / se) if se > 0 else None,
            "p_two_sided": float(2 * norm.sf(abs(est / se))) if se > 0 else None,
            "odds_ratio": float(np.exp(est)), "ci95_odds_ratio": [float(np.exp(lo)), float(np.exp(hi))],
            "ets_delta": float(delta), "ci95_ets_delta": [float(ETS * lo), float(ETS * hi)], "ets_category": cat}


def summarise_fit(md: ModelData, fit: dict) -> dict:
    beta, cov = fit["beta"], fit["cov"]
    C = len(md.conds)
    out = {"gamma_pooled": _coef_report(beta[md.i_gamma], np.sqrt(cov[md.i_gamma, md.i_gamma]))}
    deltas, per_cond = {}, {}
    for c, name in enumerate(md.conds):
        L = np.zeros(len(beta))
        if c < C - 1:
            L[md.i_delta[c]] = 1.0
        else:
            for k in md.i_delta:
                L[k] = -1.0
        var = float(L @ cov @ L)
        deltas[name] = _coef_report(float(L @ beta), np.sqrt(max(var, 0.0)))
        L[md.i_gamma] = 1.0
        var = float(L @ cov @ L)
        per_cond[name] = _coef_report(float(L @ beta), np.sqrt(max(var, 0.0)))
    out["delta_by_condition_deviation_from_pooled"] = deltas
    out["gamma_by_condition"] = per_cond
    out["conditions"] = md.conds
    out["sizes"] = {"n_rows": int(len(md.y)), "n_items_kept": md.n_items, "n_items_dropped_no_information": md.dropped_items,
                    "n_evaluees": md.n_models, "n_benchmarks": md.n_bench, "n_target_rows": int(len(md.target_rows))}
    return out


def measurement_model(ds: Dataset, n_boot: int = 2000, seed: int = 0) -> dict:
    md = build(ds)
    out: dict = {"definition": "crossed mixed-effects logistic / explanatory IRT of PREREGISTRATION section 8 (D18-D25)",
                 "coding": "Target x Cond deviation-coded over the arms with a target; gamma = pooled (unweighted over conditions) home advantage",
                 "ets_scale": "delta = 2.35 x log-odds; A < 1.0 <= B < 1.5 <= C"}
    if len(md.target_rows) == 0:
        out["warning"] = "no Target rows; gamma not identified"
        return out
    mixed = fit_mixed(md)
    out["mixed"] = {**summarise_fit(md, mixed), "variance_components": mixed["sigma2"], "converged": mixed["converged"],
                    "n_outer_iterations": mixed["n_outer"], "history_tail": mixed["history_tail"],
                    "random_effects": "u_b; Target by designer; Target x Cond by designer; Target by evaluee; Target x Cond by evaluee (independent, one variance per component, D21)",
                    "estimation": "Laplace approximation, EM-type variance fixed point, Wald CIs from the joint Hessian (D22)"}
    glm = fit_glm_cluster(md)
    out["fallback_glm_cluster_robust"] = {**summarise_fit(md, glm), "n_clusters": glm["n_clusters"],
                                          "estimation": "pooled binomial GLM, item + evaluee fixed effects, session-clustered sandwich (D23)"}
    out["reported_model"] = "mixed" if mixed["converged"] else "fallback_glm_cluster_robust (mixed model did not converge)"
    out["item_level_dif_screen"] = dif_screen(md, n_boot=n_boot, seed=seed)
    return out


def dif_screen(md: ModelData, n_boot: int = 2000, seed: int = 0) -> dict:
    """Item-level screen (D27): standardised residual of the Target evaluee under the no-DIF fit, per Target row."""
    p0 = fit_glm_no_dif(md)
    tr = md.target_rows
    y, n, ph = md.y[tr], md.n[tr], p0[tr]
    z = (y - n * ph) / np.sqrt(np.maximum(n * ph * (1 - ph), 1e-12))
    pv = 2 * norm.sf(np.abs(z))
    rej = bh_reject(pv, 0.05)
    delta_item = ETS * (y / n - ph) / np.maximum(ph * (1 - ph), 1e-6)
    out = {"definition": "per (benchmark, item) Target row: z = (y - n p0)/sqrt(n p0 (1-p0)) under the no-DIF fit; delta = 2.35 (y/n - p0)/(p0 (1-p0)); BH q=0.05 over all Target rows (descriptive, rows sharing an item are not independent)",
           "n_target_rows": int(len(tr)), "n_flagged_bh_0.05": int(rej.sum()), "fraction_flagged": float(rej.mean()) if len(rej) else None,
           "n_flagged_positive": int(np.sum(rej & (z > 0))), "n_flagged_negative": int(np.sum(rej & (z < 0))),
           "by_condition": {}}
    rng = np.random.default_rng([seed, 71])
    for c, name in enumerate(md.conds):
        sel = md.target_cond == c
        if not sel.any():
            continue
        bidx = md.target_bench[sel]
        b_list = np.unique(bidx)
        bi = np.searchsorted(b_list, bidx)
        per_b = np.bincount(bi, weights=delta_item[sel]) / np.bincount(bi)
        bs = np.array([per_b[rng.integers(0, len(per_b), size=len(per_b))].mean() for _ in range(n_boot)])
        out["by_condition"][name] = {"mean_delta": float(per_b.mean()), "ci95_benchmark_bootstrap": percentile_ci(bs), "n_benchmarks": int(len(b_list)),
                                     "mean_z": float(z[sel].mean()), "fraction_flagged": float(rej[sel].mean())}
    return out
