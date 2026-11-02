"""Q3: DIF home-advantage reconciliation (A two-stage anchor-offset GLM vs B/C pooled fallback GLM) and difficulty
artefact checks. EXPLORATORY. Own sparse Newton-Raphson binomial GLM with session-clustered sandwich SEs.
Usage: python dif.py <pool>  -> ../dif_<pool>.json"""
import sys
import numpy as np, pandas as pd, scipy.sparse as sp
from common import *

pool = sys.argv[1]
ARMS = ["sham", "inverted", "narrative", "true_named", "true_blinded", "instructed"]


def sig(x):
    return 1 / (1 + np.exp(-x))


def fit(X, y, n, off=None, ridge=1e-6, cluster=None, maxit=100):
    X = sp.csr_matrix(X); p = X.shape[1]
    off = np.zeros(len(y)) if off is None else off
    b = np.zeros(p); R = np.full(p, ridge)
    def ll(b):
        eta = X @ b + off
        return float(np.sum(y * eta - n * np.logaddexp(0, eta)) - 0.5 * np.sum(R * b * b))
    cur = ll(b)
    for it in range(maxit):
        eta = X @ b + off; mu = sig(eta)
        g = X.T @ (y - n * mu) - R * b
        W = n * mu * (1 - mu)
        H = (X.T @ sp.diags(W) @ X).toarray() + np.diag(R)
        step = np.linalg.solve(H, g)
        t = 1.0
        while True:
            nb = b + t * step; new = ll(nb)
            if new >= cur - 1e-9 or t < 1e-6:
                break
            t /= 2
        b, old, cur = nb, cur, new
        if np.max(np.abs(t * step)) < 1e-7 or abs(cur - old) < 1e-9:
            break
    eta = X @ b + off; mu = sig(eta); W = n * mu * (1 - mu)
    H = (X.T @ sp.diags(W) @ X).toarray() + np.diag(R)
    Hinv = np.linalg.inv(H)
    out = {"b": b, "Hinv": Hinv, "iters": it + 1}
    if cluster is not None:
        resid = y - n * mu
        G = int(cluster.max()) + 1
        C = sp.csr_matrix((np.ones(len(cluster)), (cluster, np.arange(len(cluster)))), shape=(G, len(cluster)))
        S = C @ sp.csr_matrix(X.multiply(resid[:, None]))
        S = S.toarray()
        out["cov"] = Hinv @ (S.T @ S) @ Hinv * G / (G - 1)
    return out


def coef(res, L):
    L = np.asarray(L, float); est = float(L @ res["b"]); se = float(np.sqrt(L @ res["cov"] @ L))
    return {"log_odds": est, "se": se, "ci95": [est - 1.96 * se, est + 1.96 * se], "ets_delta": 2.35 * est}


# ---------------------------------------------------------------- data
allb = {r["session_id"]: r for r in bench(pool, False)}
valid = {k for k, r in allb.items() if r.get("valid")}
io = pd.read_json(f"{UNB}/WORK_{pool}/results/item_outcomes.jsonl", lines=True)
io = io[io.n_samples > 0].reset_index(drop=True)
ref = pd.read_json(f"{UNB}/WORK_{pool}/results/reference_item_outcomes.jsonl", lines=True)
ref = ref[ref.n_samples > 0].reset_index(drop=True)
models = sorted(ref.model_key.unique()); items = sorted(ref.item_id.unique())
mi = {m: i for i, m in enumerate(models)}; ii = {k: i for i, k in enumerate(items)}
r0 = next(iter(allb.values()))["reference_scores"]
top_model = max(DKEYS, key=lambda k: r0[k])

# ---------------------------------------------------------------- stage 1 anchors
def anchor_rasch():
    rm = ref.model_key.map(mi).values; ri = ref.item_id.map(ii).values; N = len(ref)
    X = sp.hstack([sp.csr_matrix((np.ones(N), (np.arange(N), rm)), shape=(N, len(models))),
                   sp.csr_matrix((np.ones(N), (np.arange(N), ri)), shape=(N, len(items)))[:, 1:]]).tocsr()
    f = fit(X, ref.n_correct.values.astype(float), ref.n_samples.values.astype(float), ridge=1e-4)
    th = f["b"][:len(models)]; be = np.r_[0.0, f["b"][len(models):]]
    return th, be

theta, beta = anchor_rasch()
# item easiness on the anchor: beta (higher = easier); reference mean accuracy over the 12 designer keys
refacc = ref[ref.model_key.isin(DKEYS)].assign(a=lambda d: d.n_correct / d.n_samples).groupby("item_id").a.mean()

def anchor_2pl():
    """per-model slope on Rasch item easiness: logit = c_m + s_m * beta_i, fitted on the anchor per model."""
    c = np.zeros(len(models)); s = np.ones(len(models))
    for m, k in mi.items():
        d = ref[ref.model_key == m]; bi = beta[d.item_id.map(ii).values]
        X = np.column_stack([np.ones(len(d)), bi])
        f = fit(sp.csr_matrix(X), d.n_correct.values.astype(float), d.n_samples.values.astype(float), ridge=1e-4)
        c[k], s[k] = f["b"]
    return c, s

c2, s2 = anchor_2pl()

def anchor_binned(nb=10):
    """item FE + model x difficulty-decile FE on the anchor (non-parametric model-specific item characteristic)."""
    q = np.quantile(beta, np.linspace(0, 1, nb + 1)[1:-1]); binof = np.searchsorted(q, beta)
    rm = ref.model_key.map(mi).values; ri = ref.item_id.map(ii).values; N = len(ref)
    mb = rm * nb + binof[ri]
    X = sp.hstack([sp.csr_matrix((np.ones(N), (np.arange(N), mb)), shape=(N, len(models) * nb)),
                   sp.csr_matrix((np.ones(N), (np.arange(N), ri)), shape=(N, len(items)))[:, 1:]]).tocsr()
    f = fit(X, ref.n_correct.values.astype(float), ref.n_samples.values.astype(float), ridge=1e-4)
    phi = f["b"][:len(models) * nb].reshape(len(models), nb); be = np.r_[0.0, f["b"][len(models) * nb:]]
    return phi, be, binof

phi, beb, binof = anchor_binned()

# ---------------------------------------------------------------- produced rows
io["arm"] = io.session_id.map(lambda s: allb[s]["info_arm"])
io["ident"] = io.session_id.map(lambda s: allb[s]["identity_arm"])
io["valid"] = io.session_id.isin(valid)
def tgt(s):
    b = allb[s]; return b.get("target_model") or b.get("displayed_leader")
io["target"] = (io.model_key == io.session_id.map(tgt)).astype(float)
io["is_top"] = (io.model_key == top_model).astype(float)
io["m"] = io.model_key.map(mi).values; io["i"] = io.item_id.map(ii).values
io["off_rasch"] = theta[io.m] + beta[io.i]
io["off_2pl"] = c2[io.m] + s2[io.m] * beta[io.i]
io["off_bin"] = phi[io.m, binof[io.i]] + beb[io.i]
# benchmark difficulty: mean anchor easiness (beta) of the selected items, centred over valid sessions
sess_beta = io.drop_duplicates(["session_id", "item_id"]).groupby("session_id").i.apply(lambda x: float(np.mean(beta[x.values])))
io["bench_beta"] = io.session_id.map(sess_beta)
io["item_beta"] = beta[io.i]


def stage2(df, offcol, tcol="target", fe=True, extra=None, arms=ARMS, baseline=None, addmats=None):
    """Target x arm (cell-means coding: one coefficient per arm = total home advantage in that arm).
    baseline given -> A's treatment coding (gamma = baseline arm, deltas for others); totals are reported either way."""
    df = df.reset_index(drop=True)
    N = len(df); arms = [a for a in arms if ((df.arm == a) & (df[tcol] > 0)).any()]
    cols = []
    for a in arms:
        cols.append(sp.csr_matrix((df[tcol].values * (df.arm.values == a)).reshape(-1, 1)))
    names = [f"T[{a}]" for a in arms]
    if extra:
        for nm, v in extra.items():
            cols.append(sp.csr_matrix(v(df).reshape(-1, 1))); names.append(nm)
    if addmats:
        cols += addmats(df)
    g, sess = pd.factorize(df.session_id, sort=True)
    if fe:
        cols.append(sp.csr_matrix((np.ones(N), (np.arange(N), g)), shape=(N, len(sess))))
    else:
        cols.append(sp.csr_matrix(np.ones((N, 1))))
    X = sp.hstack(cols).tocsr()
    off = df[offcol].values if offcol else None
    f = fit(X, df.n_correct.values.astype(float), df.n_samples.values.astype(float), off=off, ridge=1e-8, cluster=g)
    out = {"n_rows": int(N), "n_sessions": int(len(sess)), "iters": f["iters"]}
    for j, nm in enumerate(names):
        L = np.zeros(X.shape[1]); L[j] = 1; out[nm] = coef(f, L)
    return out


def joint_bc(df, tcol="target", fe=False):
    """B/C fallback: anchor rows + produced rows, intercept + theta_m + beta_i + Target x arm, no offset.
    fe=True adds session fixed effects for produced rows (anchor = its own session)."""
    a = ref.assign(arm="anchor", session_id="REFERENCE", **{tcol: 0.0})
    a["m"] = a.model_key.map(mi).values; a["i"] = a.item_id.map(ii).values
    d = pd.concat([a[["session_id", "m", "i", "n_correct", "n_samples", "arm", tcol]],
                   df[["session_id", "m", "i", "n_correct", "n_samples", "arm", tcol]]], ignore_index=True)
    N = len(d); arms = [x for x in ARMS if ((d.arm == x) & (d[tcol] > 0)).any()]
    cols = [sp.csr_matrix((d[tcol].values * (d.arm.values == x)).reshape(-1, 1)) for x in arms]
    cols.append(sp.csr_matrix((np.ones(N), (np.arange(N), d.m.values)), shape=(N, len(models))))  # theta (no intercept)
    cols.append(sp.csr_matrix((np.ones(N), (np.arange(N), d.i.values)), shape=(N, len(items)))[:, 1:])
    g, sess = pd.factorize(d.session_id, sort=True)
    if fe:
        ref_idx = list(sess).index("REFERENCE")
        cols.append(sp.csr_matrix((np.ones(N), (np.arange(N), g)), shape=(N, len(sess)))[:, [k for k in range(len(sess)) if k != ref_idx]])
    X = sp.hstack(cols).tocsr()
    f = fit(X, d.n_correct.values.astype(float), d.n_samples.values.astype(float), ridge=1e-6, cluster=g)
    out = {"n_rows": int(N), "n_sessions": int(len(sess))}
    for j, x in enumerate(arms):
        L = np.zeros(X.shape[1]); L[j] = 1; out[f"T[{x}]"] = coef(f, L)
    return out


res = {"pool": pool, "top_model": top_model, "n_items": len(items), "n_models": len(models),
       "anchor_2pl_slopes": dict(zip(models, s2.tolist())), "anchor_theta": dict(zip(models, theta.tolist()))}
V = io[io.valid]
print(pool, "start fits", flush=True)
res["A_repro_all_rows"] = stage2(io, "off_rasch")
res["A_valid"] = stage2(V, "off_rasch")
res["A_valid_noFE"] = stage2(V, "off_rasch", fe=False)
res["A_valid_2pl_offset"] = stage2(V, "off_2pl")
res["A_valid_binned_offset"] = stage2(V, "off_bin")
res["A_valid_plus_TxBenchDifficulty"] = stage2(V, "off_rasch", extra={
    "T x bench_beta(centred)": lambda d: d.target.values * (d.bench_beta.values - sess_beta[list(valid & set(sess_beta.index))].mean()),
    "T x item_beta(centred)": lambda d: d.target.values * (d.item_beta.values - np.mean(beta))})
print(pool, "A variants done", flush=True)
# pseudo-target control: the reference top model as 'Target' in every arm including none (A spec, valid rows)
res["pseudo_top_A_valid"] = stage2(V, "off_rasch", tcol="is_top", arms=["none"] + ARMS)
res["pseudo_top_A_valid_binned"] = stage2(V, "off_bin", tcol="is_top", arms=["none"] + ARMS)
# sham split by identity arm (named sham leaders are drawn within reputation tier: mostly tier-1 models)
Vs = V.copy(); Vs.loc[Vs.arm == "sham", "arm"] = "sham_" + Vs.loc[Vs.arm == "sham", "ident"]
res["A_valid_sham_by_identity"] = stage2(Vs, "off_rasch", arms=["sham_blinded", "sham_true", "sham_false"] + ARMS[1:])
res["A_valid_sham_by_identity_binned"] = stage2(Vs, "off_bin", arms=["sham_blinded", "sham_true", "sham_false"] + ARMS[1:])
print(pool, "controls done", flush=True)
def model_fe(d):
    N = len(d); return [sp.csr_matrix((np.ones(N), (np.arange(N), d.m.values)), shape=(N, len(models)))[:, 1:]]
def model_fe_slope(d):
    N = len(d); cb = d.bench_beta.values - d.bench_beta.mean()
    return model_fe(d) + [sp.csr_matrix((cb, (np.arange(N), d.m.values)), shape=(N, len(models)))]
res["A_valid_modelFE"] = stage2(V, "off_rasch", addmats=model_fe)
res["A_valid_modelFE_x_benchdifficulty"] = stage2(V, "off_rasch", addmats=model_fe_slope)
res["A_valid_sham_by_identity_modelFE"] = stage2(Vs, "off_rasch", arms=["sham_blinded", "sham_true", "sham_false"] + ARMS[1:], addmats=model_fe)
res["pseudo_top_A_valid_modelFE_x_benchdifficulty"] = stage2(V, "off_rasch", tcol="is_top", arms=["none"] + ARMS, addmats=model_fe_slope)
print(pool, "modelFE done", flush=True)
res["BC_fallback"] = joint_bc(V)
res["BC_fallback_plus_sessionFE"] = joint_bc(V, fe=True)
print(pool, "BC done", flush=True)
# per-session descriptive: benchmark difficulty by arm and the top model's per-session residual
sess = V.drop_duplicates("session_id")[["session_id", "arm", "ident", "bench_beta"]]
top = V[V.model_key == top_model].assign(r=lambda d: d.n_correct / d.n_samples - sig(d.off_rasch)).groupby("session_id").r.mean()
allr = V.assign(r=lambda d: d.n_correct / d.n_samples - sig(d.off_rasch)).groupby("session_id").r.mean()
sess["top_resid_minus_mean"] = sess.session_id.map(top - allr)
sess["designer"] = sess.session_id.map(lambda s: allb[s]["designer"])
res["per_session"] = sess.to_dict(orient="records")
dump(res, f"{OUT}/dif_{pool}.json")
print(pool, "done", flush=True)
