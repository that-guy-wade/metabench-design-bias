"""PREREGISTRATION section 8: concurrent explanatory-IRT / crossed mixed-effects logistic model (implementation B).

logit P(y_{b,i,m}=1) = theta_m + beta_i + gamma*Target_{b,m} + sum_c delta_c*Target_{b,m}*Cond_{b,c} + u_b
with binomial counts over samples, maximal random slopes of Target and Target x Cond by designer and by evaluee.

Two fitters (DECISIONS D17-D21):
  * mixed:   statsmodels BinomialBayesMixedGLM (mean-field variational Bayes), subclassed so that each (b,i,m) row enters
             with its binomial trial count instead of being expanded to Bernoulli rows; beta_i as random item effects.
  * fallback: pooled binomial logistic GLM with item fixed effects (sparse IRLS) and session-cluster-robust SEs.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core  # noqa: E402

ETS_FACTOR = 2.35


# ----------------------------------------------------------------------------------------------------- design

def build_design(tree: dict, df: pd.DataFrame, item_outcomes: pd.DataFrame, reference: pd.DataFrame | None) -> dict:
    """Rows = (benchmark, item, evaluee) with binomial counts, plus the anchor set.  Target and condition coding per D17/D18."""
    valid_ids = set(df.session_id)
    io = item_outcomes[item_outcomes.session_id.isin(valid_ids)].copy()
    meta = df.set_index("session_id")
    io["designer"] = io.session_id.map(meta.designer)
    io["info_arm"] = io.session_id.map(meta.info_arm)
    leader = {sid: (r.target_model if isinstance(r.target_model, str) else r.displayed_leader) for sid, r in meta.iterrows()}
    io["target"] = (io.model_key == io.session_id.map(leader)).astype(float)
    io.loc[~io.info_arm.isin(core.LEADER_ARMS), "target"] = 0.0
    if reference is not None and len(reference):
        ref = reference.copy()
        ref["session_id"] = "REFERENCE"
        ref["designer"] = "REFERENCE"
        ref["info_arm"] = "anchor"
        ref["target"] = 0.0
        io = pd.concat([io, ref[io.columns]], ignore_index=True)
    io = io[io.n_samples > 0].reset_index(drop=True)
    arms = [a for a in core.LEADER_ARMS if (io.info_arm == a).any()]
    k = len(arms)
    cond = np.zeros((len(io), max(k - 1, 0)))
    if k >= 2:
        arm_idx = io.info_arm.map({a: i for i, a in enumerate(arms)}).to_numpy()
        for c in range(k - 1):
            cond[:, c] = np.where(arm_idx == c, 1.0, np.where(arm_idx == k - 1, -1.0, 0.0))
        cond[np.isnan(arm_idx.astype(float))] = 0.0
    cond *= io.target.to_numpy()[:, None]
    codes = {name: pd.Categorical(io[name]) for name in ("model_key", "item_id", "session_id", "designer")}
    return {"io": io, "arms": arms, "cond": cond, "codes": codes,
            "y": io.n_correct.to_numpy(dtype=float), "n": io.n_samples.to_numpy(dtype=float), "target": io.target.to_numpy(dtype=float)}


def _onehot(cat: pd.Categorical, weight: np.ndarray | None = None) -> sp.csr_matrix:
    codes = np.asarray(cat.codes)
    w = np.ones(len(codes)) if weight is None else weight
    return sp.csr_matrix((w, (np.arange(len(codes)), codes)), shape=(len(codes), len(cat.categories)))


def _report_effects(names: list[str], est: np.ndarray, cov: np.ndarray, arms: list[str], ix_gamma: int, ix_delta: list[int]) -> dict:
    """gamma, each delta_c (incl. the implied last one), per-arm gamma+delta_c, on log-odds / OR / ETS delta scales with CIs."""
    k = len(arms)

    def combo(w: np.ndarray) -> dict:
        e = float(w @ est)
        se = float(math.sqrt(max(w @ cov @ w, 0.0)))
        lo, hi = e - 1.96 * se, e + 1.96 * se
        d = ETS_FACTOR * e
        cls = "A" if abs(d) < 1.0 else ("B" if abs(d) < 1.5 else "C")
        return {"log_odds": e, "se": se, "ci95_log_odds": [lo, hi], "odds_ratio": math.exp(e), "ci95_odds_ratio": [math.exp(lo), math.exp(hi)],
                "ets_delta": d, "ci95_ets_delta": [ETS_FACTOR * lo, ETS_FACTOR * hi], "ets_class_point": cls,
                "ets_class_rule": "|delta| < 1.0 A, 1.0-1.5 B, >= 1.5 C (point estimate)"}

    p = len(est)
    out = {"gamma_pooled_home_advantage": combo(np.eye(p)[ix_gamma])}
    deltas, per_arm = {}, {}
    for c, arm in enumerate(arms):
        w = np.zeros(p)
        if c < k - 1:
            w[ix_delta[c]] = 1.0
        else:
            for j in ix_delta:
                w[j] = -1.0
        deltas[arm] = combo(w)
        w2 = w.copy()
        w2[ix_gamma] = 1.0
        per_arm[arm] = combo(w2)
    out["delta_by_arm"] = deltas
    out["home_advantage_by_arm_gamma_plus_delta"] = per_arm
    out["theta_evaluee"] = {n: float(est[i]) for i, n in enumerate(names) if n.startswith("theta:")}
    out["coding"] = "Cond deviation-coded over the leader-bearing arms present; gamma = average home advantage over arms; delta_c = arm deviation"
    return out


# ----------------------------------------------------------------------------------------------------- fallback GLM (sparse IRLS)

def fit_glm_fe(design: dict, ridge: float = 1e-4, max_iter: int = 50, tol: float = 1e-8) -> dict:
    io, cond, arms = design["io"], design["cond"], design["arms"]
    y, n, target = design["y"], design["n"], design["target"]
    Xm = _onehot(design["codes"]["model_key"])
    Xi = _onehot(design["codes"]["item_id"])[:, 1:]           # one item constrained to 0
    Xt = sp.csr_matrix(target[:, None])
    Xc = sp.csr_matrix(cond)
    X = sp.hstack([Xm, Xi, Xt, Xc], format="csr")
    names = [f"theta:{m}" for m in design["codes"]["model_key"].categories] + \
            [f"beta:{i}" for i in list(design["codes"]["item_id"].categories)[1:]] + ["gamma"] + [f"delta:{a}" for a in arms[:-1]]
    p = X.shape[1]
    ix_gamma = Xm.shape[1] + Xi.shape[1]
    ix_delta = list(range(ix_gamma + 1, p))
    beta = np.zeros(p)
    eta = X @ beta
    dev_old = np.inf
    converged = False
    t0 = time.time()
    for it in range(max_iter):
        mu = 1 / (1 + np.exp(-eta))
        w = n * mu * (1 - mu)
        w = np.maximum(w, 1e-10)
        z = eta + (y - n * mu) / w
        XtW = X.T.multiply(w)
        H = (XtW @ X).toarray() + ridge * np.eye(p)
        rhs = np.asarray(XtW @ z).ravel()
        beta_new = np.linalg.solve(H, rhs)
        eta = X @ beta_new
        mu = 1 / (1 + np.exp(-eta))
        with np.errstate(divide="ignore", invalid="ignore"):
            dev = -2 * np.sum(np.where(y > 0, y * np.log(mu), 0) + np.where(n - y > 0, (n - y) * np.log(1 - mu), 0))
        beta = beta_new
        if abs(dev_old - dev) < tol * (abs(dev) + 1):
            converged = True
            break
        dev_old = dev
    mu = 1 / (1 + np.exp(-eta))
    w = np.maximum(n * mu * (1 - mu), 1e-10)
    H = (X.T.multiply(w) @ X).toarray() + ridge * np.eye(p)
    bread = np.linalg.inv(H)
    resid = y - n * mu
    G = _onehot(design["codes"]["session_id"])                  # clusters = sessions (anchor set is its own cluster)
    S = np.asarray((G.T @ X.multiply(resid[:, None])).todense())   # (clusters, p) score sums
    g = S.shape[0]
    meat = S.T @ S
    adj = g / (g - 1) if g > 1 else 1.0
    cov_cl = adj * bread @ meat @ bread
    cov_model = bread
    rep = _report_effects(names, beta, cov_cl, arms, ix_gamma, ix_delta)
    rep.update({"fitter": "pooled binomial logistic GLM, item fixed effects (sparse IRLS, ridge %.0e), session-cluster-robust SEs" % ridge,
                "converged": converged, "iterations": it + 1, "deviance": float(dev), "n_rows": int(X.shape[0]), "n_params": int(p),
                "n_clusters": int(g), "n_items": int(Xi.shape[1] + 1), "n_evaluees": int(Xm.shape[1]), "arms": arms,
                "gamma_se_model_based": float(math.sqrt(cov_model[ix_gamma, ix_gamma])), "fit_seconds": round(time.time() - t0, 1)})
    return rep


# ----------------------------------------------------------------------------------------------------- mixed model (VB)

def fit_mixed(design: dict, maxiter: int = 400, seed: int = 7, verbose: bool = False, method: str = "map") -> dict:
    """method: "map" = posterior mode with Laplace covariance (lme4-style Laplace approximation, fixed-effect SEs from the
    Hessian); "vb" = mean-field variational Bayes (posterior sd intervals)."""
    from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM

    class _Binomial(BinomialBayesMixedGLM):
        """Each row contributes y*eta + n*E[-log(1+exp(eta))] (binomial counts); the base class assumes n = 1."""

        def vb_elbo(self, vb_mean, vb_sd):
            fep_mean, vcp_mean, vc_mean = self._unpack(vb_mean)
            fep_sd, vcp_sd, vc_sd = self._unpack(vb_sd)
            tm, tv = self._lp_stats(fep_mean, fep_sd, vc_mean, vc_sd)
            ntr = self.ntrials

            def h(z):
                u = tm + np.sqrt(tv) * z
                return -ntr * np.logaddexp(0.0, u)

            return self.vb_elbo_base(h, tm, fep_mean, vcp_mean, vc_mean, fep_sd, vcp_sd, vc_sd)

        def vb_elbo_grad(self, vb_mean, vb_sd):
            fep_mean, vcp_mean, vc_mean = self._unpack(vb_mean)
            fep_sd, vcp_sd, vc_sd = self._unpack(vb_sd)
            tm, tv = self._lp_stats(fep_mean, fep_sd, vc_mean, vc_sd)
            ntr = self.ntrials

            def h(z):
                u = tm + np.sqrt(tv) * z
                return -ntr / (1 + np.exp(-u))

            return self.vb_elbo_grad_base(h, tm, tv, fep_mean, vcp_mean, vc_mean, fep_sd, vcp_sd, vc_sd)

        # posterior mode (Laplace) path: binomial log-likelihood with trial counts
        def _lp(self, params):
            fep, vcp, vc = self._unpack(params)
            lp = np.dot(self.exog, fep) + self.exog_vc.dot(vc)
            return fep, vcp, vc, lp

        def logposterior(self, params):
            fep, vcp, vc, lp = self._lp(params)
            ll = float(np.sum(self.endog * lp - self.ntrials * np.logaddexp(0.0, lp)))
            vcp0 = vcp[self.ident]
            s = np.exp(vcp0)
            ll -= 0.5 * np.sum(vc ** 2 / s ** 2) + np.sum(vcp0)
            ll -= 0.5 * np.sum(vcp ** 2 / self.vcp_p ** 2)
            ll -= 0.5 * np.sum(fep ** 2 / self.fe_p ** 2)
            return ll

        def logposterior_grad(self, params):
            fep, vcp, vc, lp = self._lp(params)
            score = self.endog - self.ntrials / (1 + np.exp(-lp))
            g_fep = np.dot(score, self.exog) - fep / self.fe_p ** 2
            g_vc = self.exog_vc.transpose().dot(score)
            vcp0 = vcp[self.ident]
            s = np.exp(vcp0)
            g_vcp = np.bincount(self.ident, weights=vc ** 2 / s ** 2 - 1, minlength=self.k_vcp) - vcp / self.vcp_p ** 2
            g_vc = g_vc - vc / s ** 2
            return np.concatenate([g_fep, g_vcp, g_vc])

    io, cond, arms, codes = design["io"], design["cond"], design["arms"], design["codes"]
    y, n, target = design["y"], design["n"], design["target"]
    Xm = _onehot(codes["model_key"]).toarray()
    exog = np.hstack([Xm, target[:, None], cond])
    fep_names = [f"theta:{m}" for m in codes["model_key"].categories] + ["gamma"] + [f"delta:{a}" for a in arms[:-1]]
    ix_gamma = Xm.shape[1]
    ix_delta = list(range(ix_gamma + 1, exog.shape[1]))
    # variance components (Barr 2013 maximal): item, benchmark, Target|designer, Target|evaluee, Target x Cond|designer, Target x Cond|evaluee
    is_bench = (io.session_id != "REFERENCE").to_numpy().astype(float)
    bench_cat = pd.Categorical(io.session_id)
    des_cat = codes["designer"]
    blocks, ident, vcp_names = [], [], []

    def add(mat: sp.csr_matrix, name: str):
        keep = np.asarray(abs(mat).sum(axis=0)).ravel() > 0
        mat = mat[:, keep]
        if mat.shape[1] == 0:
            return
        blocks.append(mat)
        ident.extend([len(vcp_names)] * mat.shape[1])
        vcp_names.append(name)

    add(_onehot(codes["item_id"]), "item")
    add(_onehot(bench_cat, is_bench), "benchmark")
    add(_onehot(des_cat, target), "target|designer")
    add(_onehot(codes["model_key"], target), "target|evaluee")
    if cond.shape[1]:
        add(sp.hstack([_onehot(des_cat, cond[:, c]) for c in range(cond.shape[1])], format="csr"), "target_x_cond|designer")
        add(sp.hstack([_onehot(codes["model_key"], cond[:, c]) for c in range(cond.shape[1])], format="csr"), "target_x_cond|evaluee")
    exog_vc = sp.hstack(blocks, format="csr")
    ident = np.array(ident)
    endog_bin = (y > 0).astype(float)
    model = _Binomial(endog_bin, exog, exog_vc, ident, fep_names=fep_names, vcp_names=vcp_names)
    model.endog = y.astype(float)
    model.ntrials = n.astype(float)
    t0 = time.time()
    if method == "vb":
        res = model.fit_vb(minim_opts={"maxiter": maxiter}, verbose=verbose, rng=seed)
        fe_mean, fe_sd = np.asarray(res.fe_mean), np.asarray(res.fe_sd)
        cov = np.diag(fe_sd ** 2)                   # mean-field: independent Gaussians
        fitter = "BinomialBayesMixedGLM mean-field variational Bayes"
        interval = "posterior mean +/- 1.96 posterior sd (mean-field; covariances between fixed effects are not estimated)"
    else:
        import warnings
        from statsmodels.tools.sm_exceptions import ConvergenceWarning
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ConvergenceWarning)
            res = model.fit_map(minim_opts={"maxiter": maxiter})
        map_converged = not any(issubclass(w.category, ConvergenceWarning) for w in caught)
        fe_mean = np.asarray(res.params[: len(fep_names)])
        cov = np.asarray(res.cov_params())[: len(fep_names), : len(fep_names)]
        fitter = "BinomialBayesMixedGLM posterior mode with Laplace covariance (joint mode over fixed effects, log-sd parameters and random effects)"
        interval = "mode +/- 1.96 * sqrt(diag of the inverse Hessian at the mode) (Laplace)"
    vc_sd = {nm: float(math.exp(v)) for nm, v in zip(vcp_names, np.asarray(res.vcp_mean))}
    # pre-specified sanity gate (DECISIONS A9): a fit whose variance-component sds or fixed effects are implausibly large has not
    # found a usable optimum and is not reported as the pre-registered estimate
    degenerate = (max(vc_sd.values()) > 3.0) or (float(np.max(np.abs(fe_mean))) > 10.0) or not np.all(np.isfinite(cov))
    rep = _report_effects(fep_names, fe_mean, cov, arms, ix_gamma, ix_delta)
    rep.update({"fitter": fitter + "; binomial counts, random item effects, random intercept by benchmark, random Target and "
                          "Target x Cond slopes by designer and by evaluee", "method": method,
                "interval": interval,
                "n_rows": int(exog.shape[0]), "n_fixed": int(exog.shape[1]), "n_random": int(exog_vc.shape[1]),
                "variance_component_sd": vc_sd, "degenerate": bool(degenerate),
                "fit_seconds": round(time.time() - t0, 1), "maxiter": maxiter,
                "converged": bool((map_converged if method != "vb" else bool(getattr(getattr(res, "optim_retvals", None), "success", False)))
                                  and not degenerate),
                "optimizer": (dict(nit=int(res.optim_retvals.nit), success=bool(res.optim_retvals.success), message=str(res.optim_retvals.message))
                              if getattr(res, "optim_retvals", None) is not None else None), "arms": arms})
    return rep




# ----------------------------------------------------------------------------------------------------- Laplace GLMM (own implementation)

def _random_design(design: dict):
    """Sparse random-effects design Z and the variance-component group index of each column (D19 structure)."""
    io, cond, codes = design["io"], design["cond"], design["codes"]
    target = design["target"]
    is_bench = (io.session_id != "REFERENCE").to_numpy().astype(float)
    bench_cat = pd.Categorical(io.session_id)
    des_cat = codes["designer"]
    blocks, ident, names = [], [], []

    def add(mat, name):
        keep = np.asarray(abs(mat).sum(axis=0)).ravel() > 0
        mat = mat[:, keep]
        if mat.shape[1] == 0:
            return
        blocks.append(mat)
        ident.extend([len(names)] * mat.shape[1])
        names.append(name)

    add(_onehot(codes["item_id"]), "item")
    add(_onehot(bench_cat, is_bench), "benchmark")
    add(_onehot(des_cat, target), "target|designer")
    add(_onehot(codes["model_key"], target), "target|evaluee")
    if cond.shape[1]:
        add(sp.hstack([_onehot(des_cat, cond[:, c]) for c in range(cond.shape[1])], format="csr"), "target_x_cond|designer")
        add(sp.hstack([_onehot(codes["model_key"], cond[:, c]) for c in range(cond.shape[1])], format="csr"), "target_x_cond|evaluee")
    return sp.hstack(blocks, format="csr"), np.array(ident), names


def fit_mixed_laplace(design: dict, maxiter: int = 60, ridge_fe: float = 1e-6, verbose: bool = False) -> dict:
    """Crossed binomial GLMM by the Laplace approximation (as in lme4's glmer, nAGQ = 1):
    for fixed log-sds theta, (beta, u) is the joint mode from penalised IRLS; the Laplace marginal log-likelihood
      l(theta) = log p(y | beta, u) - u'D^-1 u / 2 - log|D| / 2 - log|Z'WZ + D^-1| / 2
    is maximised over theta with Nelder-Mead (6 parameters); fixed-effect SEs are the beta block of the inverse penalised
    Hessian at the optimum (conditional on theta, the usual Wald SEs)."""
    from scipy.optimize import minimize
    y, n, target, cond, arms = design["y"], design["n"], design["target"], design["cond"], design["arms"]
    Xm = _onehot(design["codes"]["model_key"])
    X = sp.hstack([Xm, sp.csr_matrix(target[:, None]), sp.csr_matrix(cond)], format="csr")
    fep_names = [f"theta:{m}" for m in design["codes"]["model_key"].categories] + ["gamma"] + [f"delta:{a}" for a in arms[:-1]]
    Z, ident, vcp_names = _random_design(design)
    p, q = X.shape[1], Z.shape[1]
    ix_gamma = Xm.shape[1]
    ix_delta = list(range(ix_gamma + 1, p))
    XZ = sp.hstack([X, Z], format="csr")
    XZt = XZ.T.tocsr()
    state = {"coef": np.zeros(p + q), "evals": 0}
    t0 = time.time()

    def inner(log_sd: np.ndarray, coef0: np.ndarray, iters: int = 25):
        prec = np.concatenate([np.full(p, ridge_fe), 1.0 / np.exp(2 * log_sd[ident])])
        coef = coef0.copy()
        eta = XZ @ coef
        dev_old = np.inf
        for _ in range(iters):
            mu = 1 / (1 + np.exp(-eta))
            w = np.maximum(n * mu * (1 - mu), 1e-10)
            z = eta + (y - n * mu) / w
            H = (XZt.multiply(w) @ XZ).toarray()
            H[np.diag_indices_from(H)] += prec
            rhs = np.asarray(XZt @ (w * z)).ravel()
            coef = np.linalg.solve(H, rhs)
            eta = XZ @ coef
            mu = 1 / (1 + np.exp(-eta))
            pen = 0.5 * float(np.sum(prec * coef ** 2))
            with np.errstate(divide="ignore", invalid="ignore"):
                dev = -2 * float(np.sum(np.where(y > 0, y * np.log(mu), 0) + np.where(n - y > 0, (n - y) * np.log(1 - mu), 0))) + 2 * pen
            if abs(dev_old - dev) < 1e-7 * (abs(dev) + 1):
                break
            dev_old = dev
        return coef, eta, H, prec

    def neg_laplace(log_sd: np.ndarray) -> float:
        coef, eta, H, prec = inner(log_sd, state["coef"])
        state["coef"], state["evals"] = coef, state["evals"] + 1
        mu = 1 / (1 + np.exp(-eta))
        with np.errstate(divide="ignore", invalid="ignore"):
            ll = float(np.sum(np.where(y > 0, y * np.log(mu), 0) + np.where(n - y > 0, (n - y) * np.log(1 - mu), 0)))
        u = coef[p:]
        ll -= 0.5 * float(np.sum(u ** 2 * prec[p:])) + float(np.sum(log_sd[ident]))
        Hu = H[p:, p:]
        sign, logdet = np.linalg.slogdet(Hu)
        ll -= 0.5 * logdet
        if verbose:
            print(f"eval {state['evals']} log_sd={np.round(log_sd, 3)} -l={-ll:.3f} t={time.time() - t0:.0f}s", file=sys.stderr)
        return -ll

    # 1) two coordinate sweeps over a log-sd grid (deterministic, finds the basin), 2) Nelder-Mead polish with a small simplex
    grid = np.array([-4.0, -3.0, -2.0, -1.0, -0.5, 0.0, 0.5, 1.0])
    x = np.full(len(vcp_names), -1.0)
    best = neg_laplace(x)
    for _sweep in range(2):
        for j in range(len(x)):
            vals = []
            for gv in grid:
                xx = x.copy()
                xx[j] = gv
                vals.append(neg_laplace(xx) if gv != x[j] else best)
            k = int(np.argmin(vals))
            x[j], best = grid[k], vals[k]
    simplex = np.vstack([x] + [x + 0.3 * np.eye(len(x))[j] for j in range(len(x))])
    res = minimize(neg_laplace, x, method="Nelder-Mead",
                   options={"maxiter": maxiter, "maxfev": maxiter, "xatol": 0.05, "fatol": 0.25, "initial_simplex": simplex})
    log_sd = res.x if res.fun <= best else x
    grid_evals = 1 + 2 * len(x) * (len(grid) - 1)
    coef, eta, H, prec = inner(log_sd, state["coef"], iters=50)
    cov_full = np.linalg.inv(H)
    cov = cov_full[:p, :p]
    est = coef[:p]
    vc_sd = {nm: float(math.exp(v)) for nm, v in zip(vcp_names, log_sd)}
    degenerate = (max(vc_sd.values()) > 3.0) or (float(np.max(np.abs(est))) > 10.0) or not np.all(np.isfinite(cov))
    rep = _report_effects(fep_names, est, cov, arms, ix_gamma, ix_delta)
    rep.update({"fitter": "Laplace-approximation crossed binomial GLMM (own implementation: penalised sparse IRLS for the joint mode, "
                          "Nelder-Mead over the 6 log-sd variance components); random item effects, random benchmark intercept, random "
                          "Target and Target x Cond slopes by designer and by evaluee", "method": "laplace",
                "interval": "Wald: estimate +/- 1.96 * sqrt(diag of the beta block of the inverse penalised Hessian at the Laplace optimum)",
                "n_rows": int(X.shape[0]), "n_fixed": int(p), "n_random": int(q), "variance_component_sd": vc_sd, "degenerate": bool(degenerate),
                "optimizer": {"grid_evals": int(grid_evals), "polish_nfev": int(res.nfev), "polish_nit": int(res.nit),
                              "polish_success": bool(res.success), "message": str(res.message),
                              "neg_laplace_loglik": float(min(res.fun, best)), "log_sd": [float(v) for v in log_sd]},
                "singular": bool(np.any(log_sd < -3.5)),     # a variance component at (numerically) zero, as lme4's "singular fit"; reported, not a failure
                "converged": bool(not degenerate), "fit_seconds": round(time.time() - t0, 1), "maxiter": maxiter, "arms": arms})
    return rep


# ----------------------------------------------------------------------------------------------------- orchestration

def measurement_model(tree: dict, df: pd.DataFrame, item_outcomes: pd.DataFrame, reference: pd.DataFrame | None,
                      mixed_timeout: float, results_dir: str, maxiter: int, seed: int, method: str = "laplace") -> dict:
    """Fit the fallback in-process; run the mixed model in a subprocess bounded by `mixed_timeout` seconds (D19)."""
    import subprocess
    design = build_design(tree, df, item_outcomes, reference)
    out: dict = {"model": "logit P(y_bim=1) = theta_m + beta_i + gamma*Target_bm + sum_c delta_c*Target_bm*Cond_bc + u_b, binomial over samples",
                 "n_rows": int(len(design["io"])), "n_anchor_rows": int((design["io"].session_id == "REFERENCE").sum()),
                 "n_target_rows": int(design["target"].sum()), "arms_with_target": design["arms"]}
    out["fallback_glm"] = fit_glm_fe(design)
    Path(results_dir).mkdir(parents=True, exist_ok=True)
    mixed_path = Path(results_dir) / "_B_mixed.json"
    cmd = [sys.executable, str(Path(__file__).resolve()), "--results", str(tree["root"]), "--out", str(mixed_path),
           "--maxiter", str(maxiter), "--seed", str(seed), "--method", method]
    try:
        t0 = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=mixed_timeout)
        if proc.returncode == 0 and mixed_path.exists():
            out["mixed"] = json.load(open(mixed_path))
            out["mixed"]["status"] = "ok"
            out["mixed"]["wall_seconds"] = round(time.time() - t0, 1)
        else:
            out["mixed"] = {"status": "failed", "returncode": proc.returncode, "stderr_tail": proc.stderr[-2000:]}
    except subprocess.TimeoutExpired:
        out["mixed"] = {"status": f"timeout after {mixed_timeout}s"}
    finally:
        if mixed_path.exists():
            mixed_path.unlink()
    mixed_ok = out["mixed"].get("status") == "ok" and out["mixed"].get("converged", True)
    out["reported"] = "mixed" if mixed_ok else "fallback_glm"
    out["reported_note"] = ("pre-registered mixed model" if mixed_ok else
                            "pre-registered FALLBACK (pooled GLM with item fixed effects and session-cluster-robust SEs); "
                            "the mixed model did not converge or was unavailable: " + str(out["mixed"].get("status")))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="fit the mixed model only (used as a subprocess by run.py)")
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--maxiter", type=int, default=400)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--method", default="laplace", choices=["laplace", "map", "vb"])
    a = ap.parse_args(argv)
    tree = core.load_tree(a.results)
    df = core.session_table(tree["benchmarks"], tree["configs"])
    io = core.load_item_outcomes(tree, set(df.session_id))
    ref = core.load_reference_outcomes(tree)
    design = build_design(tree, df, io, ref)
    if a.method == "laplace":
        rep = fit_mixed_laplace(design, maxiter=a.maxiter, verbose=a.verbose)
    else:
        rep = fit_mixed(design, maxiter=a.maxiter, seed=a.seed, verbose=a.verbose, method=a.method)
    Path(a.out).write_text(json.dumps(rep, indent=1, default=float))


if __name__ == "__main__":
    main()
