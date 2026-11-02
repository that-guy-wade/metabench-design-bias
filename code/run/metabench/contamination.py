"""Contamination check on the reference item outcomes.  Specification: docs/CONTAMINATION_SPEC.md.

Three per-entry statistics on the REFERENCE rows (every pool item x every confirmatory panel key):
  (a) ConStat-style twin-set regression of old-item accuracy on recent-item accuracy across the panel,
      leave-one-out residual, item + entry bootstrap, one-sided p-value;
  (b) difficulty-adjusted logistic date slope per entry, item bootstrap of (beta_m - panel median);
  (c) per-developer post_cutoff gap (LOO-panel-mean adjusted), item bootstrap.
No model is called; `metabench.panel` is imported only for the key -> developer map (the active panel is
not switched).  Flagged entries stay in the panel; the output lists them for the sensitivity analysis.
"""
from __future__ import annotations

import importlib.util
import json
import time
from datetime import date
from pathlib import Path

import numpy as np
import statsmodels.api as sm

from .panel import CONFIRMATORY_PANEL


def _cutoffs() -> dict[str, date]:
    """DEVELOPER_CUTOFFS from pools/schema_check.py, loaded by path (pools/ must not go on sys.path)."""
    p = Path(__file__).resolve().parents[1] / "pools" / "schema_check.py"
    spec = importlib.util.spec_from_file_location("_pools_schema_check", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return dict(mod.DEVELOPER_CUTOFFS)


DEVELOPER_CUTOFFS = _cutoffs()

SPEC_VERSION = 1
MIN_SET = 20          # smallest old / recent / pre / post set that is estimable
MIN_POST = 20
ALPHA = 0.05
DEVELOPERS = ["anthropic", "openai", "google", "xai"]
SPECS = {s.key: s for s in CONFIRMATORY_PANEL}
A_FIELDS = ["estimable", "reason", "n_old", "n_recent", "acc_old", "acc_old_ci", "acc_recent", "acc_recent_ci",
            "diff_old_recent", "diff_old_recent_ci", "loo_slope", "loo_intercept", "predicted_old", "residual",
            "residual_ci", "p_value", "flag"]
B_FIELDS = ["estimable", "reason", "n_items", "date_span_years", "beta_date", "se", "ci_wald", "ci_boot",
            "beta_minus_median", "beta_minus_median_ci", "flag"]
C_FIELDS = ["estimable", "reason", "cutoff", "n_pre", "n_post", "acc_pre", "acc_pre_ci", "acc_post", "acc_post_ci",
            "gap_raw", "gap_raw_ci", "gap_adjusted", "gap_adjusted_ci", "flag"]
ENTRY_FIELDS = ["key", "developer", "model_id", "n_items", "n_samples_total", "accuracy", "accuracy_ci", "a", "b", "c"]


# ---------------------------------------------------------------- helpers
def _f(x):
    """numpy -> JSON float, NaN/inf -> None."""
    if x is None:
        return None
    x = float(x)
    return x if np.isfinite(x) else None


def _ci(v):
    v = np.asarray(v, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return [None, None]
    return [_f(np.percentile(v, 2.5)), _f(np.percentile(v, 97.5))]


def _empty(fields, reason):
    d = {k: None for k in fields}
    d.update(estimable=False, reason=reason, flag=False)
    return d


def _parse_date(s: str) -> date:
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def _years(d: date) -> float:
    return d.toordinal() / 365.25


def _wmean(P: np.ndarray, W: np.ndarray) -> np.ndarray:
    """Weighted mean of P (M, n) under bootstrap count weights W (B, n), NaN-aware -> (M, B)."""
    ok = np.isfinite(P)
    Pz = np.where(ok, P, 0.0)
    return (Pz @ W.T) / (ok.astype(float) @ W.T)


def _ols(x: np.ndarray, y: np.ndarray, axis=-1):
    """Slope and intercept of y on x along `axis`; NaN when x has no variance."""
    xm = x.mean(axis, keepdims=True)
    ym = y.mean(axis, keepdims=True)
    sxx = ((x - xm) ** 2).sum(axis)
    sxy = ((x - xm) * (y - ym)).sum(axis)
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = np.where(sxx > 0, sxy / sxx, np.nan)
    intercept = ym.squeeze(axis) - slope * xm.squeeze(axis)
    return slope, intercept


def loo_panel_mean(P: np.ndarray) -> np.ndarray:
    """d[m, i] = mean over the other entries of p[m', i] (NaN-aware)."""
    ok = np.isfinite(P)
    Pz = np.where(ok, P, 0.0)
    tot, cnt = Pz.sum(0, keepdims=True), ok.sum(0, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (tot - Pz) / (cnt - ok)


def batched_logistic(X: np.ndarray, C: np.ndarray, S: np.ndarray, W: np.ndarray, iters: int = 30) -> np.ndarray:
    """Weighted binomial logistic regression for B weight vectors at once.
    X (n, p) design; C, S (n,) successes and trials; W (B, n) bootstrap count weights.  Returns (B, p)."""
    B, n = W.shape
    p = X.shape[1]
    beta = np.zeros((B, p))
    for _ in range(iters):
        eta = np.clip(X @ beta.T, -30, 30)                 # (n, B)
        mu = 1.0 / (1.0 + np.exp(-eta))
        g = X.T @ (W.T * (C[:, None] - S[:, None] * mu))   # (p, B)
        h = np.einsum("ni,nb,nj->bij", X, W.T * (S[:, None] * mu * (1 - mu)), X) + 1e-8 * np.eye(p)
        step = np.linalg.solve(h, g.T[:, :, None])[:, :, 0]
        beta = np.clip(beta + step, -50, 50)
        if np.abs(step).max() < 1e-9:
            break
    return beta


# ---------------------------------------------------------------- data
def load_inputs(reference_path: Path, pool_path: Path):
    """Return (keys, items, C, S) with C/S of shape (M, N); NaN-free ints, S == 0 where unscored."""
    pool = {}
    with open(pool_path) as f:
        for line in f:
            if line.strip():
                it = json.loads(line)
                pool[it["id"]] = it
    rows = {}
    ignored = set()
    with open(reference_path) as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("session_id") != "REFERENCE" or r["item_id"] not in pool:
                continue
            if r["model_key"] not in SPECS:
                ignored.add(r["model_key"])
                continue
            rows[(r["model_key"], r["item_id"])] = (int(r["n_correct"]), int(r["n_samples"]))
    keys = [s.key for s in CONFIRMATORY_PANEL if any(k == s.key for k, _ in rows)]
    missing = [s.key for s in CONFIRMATORY_PANEL if s.key not in keys]
    ids = sorted({i for _, i in rows})
    items = [{"id": i, "date": _parse_date(pool[i]["source_date"]),
              "post": {d: bool(pool[i]["post_cutoff_by_developer"].get(d, False)) for d in DEVELOPERS}} for i in ids]
    C = np.zeros((len(keys), len(ids)), dtype=int)
    S = np.zeros_like(C)
    for (k, i), (c, s) in rows.items():
        C[keys.index(k), ids.index(i)] = c
        S[keys.index(k), ids.index(i)] = s
    return keys, items, C, S, sorted(ignored), missing


# ---------------------------------------------------------------- statistics
def stat_a(P: np.ndarray, recent: np.ndarray, rng: np.random.Generator, B: int):
    """ConStat-adapted twin-set regression.  Returns (split_info, regression_info, per-entry list)."""
    M, N = P.shape
    old_idx, rec_idx = np.where(~recent)[0], np.where(recent)[0]
    if len(old_idx) < MIN_SET or len(rec_idx) < MIN_SET:
        reason = f"old={len(old_idx)} recent={len(rec_idx)}; both sets need >= {MIN_SET} items"
        return reason, None, [_empty(A_FIELDS, reason) for _ in range(M)]
    acc_old, acc_rec = np.nanmean(P[:, old_idx], 1), np.nanmean(P[:, rec_idx], 1)
    slope, intercept = _ols(acc_rec, acc_old)
    pred = intercept + slope * acc_rec
    ss_res, ss_tot = ((acc_old - pred) ** 2).sum(), ((acc_old - acc_old.mean()) ** 2).sum()
    reg = {"slope": _f(slope), "intercept": _f(intercept), "r2": _f(1 - ss_res / ss_tot) if ss_tot > 0 else None,
           "n_entries": int(M)}
    # item bootstrap (shared draws across entries)
    W_old = rng.multinomial(len(old_idx), np.full(len(old_idx), 1 / len(old_idx)), size=B).astype(float)
    W_rec = rng.multinomial(len(rec_idx), np.full(len(rec_idx), 1 / len(rec_idx)), size=B).astype(float)
    ao_b, ar_b = _wmean(P[:, old_idx], W_old), _wmean(P[:, rec_idx], W_rec)     # (M, B)
    out = []
    for m in range(M):
        others = np.array([j for j in range(M) if j != m])
        if len(others) < 3:
            out.append(_empty(A_FIELDS, "fewer than 3 other entries"))
            continue
        s_m, i_m = _ols(acc_rec[others], acc_old[others])
        r_m = acc_old[m] - (i_m + s_m * acc_rec[m])
        J = others[rng.integers(0, len(others), (B, len(others)))]              # entry resample per draw
        cols = np.arange(B)[:, None]
        s_b, i_b = _ols(ar_b[J, cols], ao_b[J, cols], axis=1)
        r_b = ao_b[m] - (i_b + s_b * ar_b[m])
        r_b = r_b[np.isfinite(r_b)]
        p_val = float(np.mean(r_b <= 0)) if r_b.size else None
        out.append({"estimable": True, "reason": None, "n_old": int(len(old_idx)), "n_recent": int(len(rec_idx)),
                    "acc_old": _f(acc_old[m]), "acc_old_ci": _ci(ao_b[m]), "acc_recent": _f(acc_rec[m]),
                    "acc_recent_ci": _ci(ar_b[m]), "diff_old_recent": _f(acc_old[m] - acc_rec[m]),
                    "diff_old_recent_ci": _ci(ao_b[m] - ar_b[m]), "loo_slope": _f(s_m), "loo_intercept": _f(i_m),
                    "predicted_old": _f(i_m + s_m * acc_rec[m]), "residual": _f(r_m), "residual_ci": _ci(r_b),
                    "p_value": p_val, "flag": bool(p_val is not None and p_val < ALPHA)})
    return None, reg, out


def stat_b(C: np.ndarray, S: np.ndarray, P: np.ndarray, t: np.ndarray, rng: np.random.Generator, B: int):
    """Difficulty-adjusted date slope per entry.  Returns (panel_info, per-entry list)."""
    M, N = P.shape
    D = np.clip(loo_panel_mean(P), 0.01, 0.99)
    W = rng.multinomial(N, np.full(N, 1 / N), size=B).astype(float)
    betas = np.full(M, np.nan)
    beta_b = np.full((M, B), np.nan)
    ent = []
    for m in range(M):
        use = (S[m] > 0) & np.isfinite(D[m])
        n = int(use.sum())
        tt = t[use]
        span = float(tt.max() - tt.min()) if n else 0.0
        acc = C[m, use].sum() / max(S[m, use].sum(), 1)
        if n < MIN_SET or np.unique(tt).size < 2:
            ent.append(_empty(B_FIELDS, f"n={n} items, {np.unique(tt).size} distinct dates")); continue
        if acc in (0.0, 1.0):
            ent.append(_empty(B_FIELDS, f"accuracy exactly {acc:.0f}")); continue
        X = np.column_stack([np.ones(n), tt - tt.mean(), np.log(D[m, use] / (1 - D[m, use]))])
        fit = sm.GLM(np.column_stack([C[m, use], S[m, use] - C[m, use]]), X, family=sm.families.Binomial()).fit()
        betas[m] = fit.params[1]
        se = float(fit.bse[1])
        beta_b[m] = batched_logistic(X, C[m, use].astype(float), S[m, use].astype(float), W[:, use])[:, 1]
        ent.append({"estimable": True, "reason": None, "n_items": n, "date_span_years": span,
                    "beta_date": _f(betas[m]), "se": _f(se), "ci_wald": [_f(betas[m] - 1.96 * se), _f(betas[m] + 1.96 * se)],
                    "ci_boot": _ci(beta_b[m])})
    est = np.isfinite(betas)
    if est.sum() == 0:
        panel = {"median_beta": None, "mad_beta": None, "n_entries_estimable": 0}
        for e in ent:
            e.update(beta_minus_median=None, beta_minus_median_ci=[None, None], flag=False)
        return panel, ent
    med = float(np.median(betas[est]))
    panel = {"median_beta": med, "mad_beta": float(np.median(np.abs(betas[est] - med))), "n_entries_estimable": int(est.sum())}
    med_b = np.nanmedian(beta_b[est], axis=0)
    for m, e in enumerate(ent):
        if not e["estimable"]:
            e.update(beta_minus_median=None, beta_minus_median_ci=[None, None], flag=False)
            continue
        diff_b = beta_b[m] - med_b
        diff_b = diff_b[np.isfinite(diff_b)]
        e.update(beta_minus_median=_f(betas[m] - med), beta_minus_median_ci=_ci(diff_b),
                 flag=bool(diff_b.size and np.percentile(diff_b, 95) < 0))
    return panel, ent


def stat_c(P: np.ndarray, items: list, devs: list, rng: np.random.Generator, B: int):
    """Per-developer post_cutoff gap, LOO-panel-mean adjusted.  Returns (developer_info, per-entry list)."""
    M, N = P.shape
    D = loo_panel_mean(P)
    Sadj = P - D
    dev_info, ent = {}, []
    masks = {d: np.array([it["post"][d] for it in items]) for d in DEVELOPERS}
    weights = {}
    for d in DEVELOPERS:
        n_post, n_pre = int(masks[d].sum()), int((~masks[d]).sum())
        ok = n_post >= MIN_POST and n_pre >= MIN_SET
        dev_info[d] = {"cutoff": DEVELOPER_CUTOFFS[d].isoformat(), "n_pre": n_pre, "n_post": n_post, "estimable": ok,
                       "reason": None if ok else f"n_post={n_post} < {MIN_POST} or n_pre={n_pre} < {MIN_SET}: not estimable"}
        if ok:
            weights[d] = (rng.multinomial(n_pre, np.full(n_pre, 1 / n_pre), size=B).astype(float),
                          rng.multinomial(n_post, np.full(n_post, 1 / n_post), size=B).astype(float))
    for m in range(M):
        d = devs[m]
        info = dev_info[d]
        if not info["estimable"]:
            e = _empty(C_FIELDS, info["reason"])
            e.update(cutoff=info["cutoff"], n_pre=info["n_pre"], n_post=info["n_post"])
            ent.append(e); continue
        pre, post = ~masks[d], masks[d]
        W_pre, W_post = weights[d]
        acc_pre, acc_post = np.nanmean(P[m, pre]), np.nanmean(P[m, post])
        gap_raw = acc_pre - acc_post
        gap_adj = np.nanmean(Sadj[m, pre]) - np.nanmean(Sadj[m, post])
        ap_b, apo_b = _wmean(P[m:m + 1, pre], W_pre)[0], _wmean(P[m:m + 1, post], W_post)[0]
        ga_b = _wmean(Sadj[m:m + 1, pre], W_pre)[0] - _wmean(Sadj[m:m + 1, post], W_post)[0]
        ga_b = ga_b[np.isfinite(ga_b)]
        ent.append({"estimable": True, "reason": None, "cutoff": info["cutoff"], "n_pre": info["n_pre"], "n_post": info["n_post"],
                    "acc_pre": _f(acc_pre), "acc_pre_ci": _ci(ap_b), "acc_post": _f(acc_post), "acc_post_ci": _ci(apo_b),
                    "gap_raw": _f(gap_raw), "gap_raw_ci": _ci(ap_b - apo_b), "gap_adjusted": _f(gap_adj),
                    "gap_adjusted_ci": _ci(ga_b), "flag": bool(ga_b.size and np.percentile(ga_b, 5) > 0)})
    return dev_info, ent


# ---------------------------------------------------------------- driver
def run_check(reference_path: Path, pool_path: Path, n_boot: int = 10000, seed: int = 20261025) -> dict:
    t0 = time.time()
    keys, items, C, S, ignored, missing = load_inputs(Path(reference_path), Path(pool_path))
    if not keys or not items:
        raise ValueError("no REFERENCE rows for confirmatory panel keys / pool items")
    rng = np.random.default_rng(seed)
    with np.errstate(divide="ignore", invalid="ignore"):
        P = np.where(S > 0, C / np.maximum(S, 1), np.nan)
    devs = [SPECS[k].provider for k in keys]
    t = np.array([_years(it["date"]) for it in items])
    # (a) split
    union = np.array([any(it["post"].values()) for it in items])
    if union.sum() >= MIN_SET:
        recent, method, thr = union, "post_cutoff_union", DEVELOPER_CUTOFFS["google"].isoformat()
    else:
        ords = np.array([it["date"].toordinal() for it in items])
        q = int(np.percentile(ords, 80))
        recent, method, thr = ords > q, "date_quantile_newest_20pct", date.fromordinal(q).isoformat()
    reason_a, reg_a, ent_a = stat_a(P, recent, rng, n_boot)
    split = {"method": method if reason_a is None else "not_estimable", "attempted": method, "threshold_date": thr,
             "n_old": int((~recent).sum()), "n_recent": int(recent.sum()), "reason": reason_a}
    panel_b, ent_b = stat_b(C, S, P, t, rng, n_boot)
    dev_info, ent_c = stat_c(P, items, devs, rng, n_boot)
    # overall accuracy with item-bootstrap CI
    W = rng.multinomial(len(items), np.full(len(items), 1 / len(items)), size=n_boot).astype(float)
    acc_b = _wmean(P, W)
    entries = {}
    for m, k in enumerate(keys):
        entries[k] = {"key": k, "developer": devs[m], "model_id": SPECS[k].model_id, "n_items": int((S[m] > 0).sum()),
                      "n_samples_total": int(S[m].sum()), "accuracy": _f(np.nanmean(P[m])), "accuracy_ci": _ci(acc_b[m]),
                      "a": ent_a[m], "b": ent_b[m], "c": ent_c[m]}
    flagged = {s: [k for k in keys if entries[k][s]["flag"]] for s in "abc"}
    flagged["any"] = [k for k in keys if any(entries[k][s]["flag"] for s in "abc")]
    return {"spec_version": SPEC_VERSION, "spec": "docs/CONTAMINATION_SPEC.md",
            "inputs": {"reference": str(reference_path), "pool": str(pool_path), "n_boot": int(n_boot), "seed": int(seed),
                       "n_items": len(items), "n_entries": len(keys), "panel": "confirmatory",
                       "cutoffs": {d: c.isoformat() for d, c in DEVELOPER_CUTOFFS.items()},
                       "ignored_keys": ignored, "missing_keys": missing, "min_set": MIN_SET, "min_post": MIN_POST, "alpha": ALPHA},
            "split_a": split, "regression_a": reg_a, "panel_b": panel_b, "developers": dev_info,
            "entries": entries, "flagged": flagged, "elapsed_s": round(time.time() - t0, 2)}


# ---------------------------------------------------------------- synthetic data (tests only)
SYNTH_THETA = {"fable51": 1.6, "sonnet55": 0.9, "opus5": 0.5, "gpt61sol": 1.5, "gpt6luna": 0.6, "gpt55": 0.8,
               "gemini4argon": 1.4, "gemini38flash": 0.3, "gemini31pro": 0.4, "grok47": 1.2, "grok45": 0.7, "grok43": 0.0,
               "placebo_sonnet55": 0.9, "heldout_sonnet46": 0.2, "heldout_gpt54": 0.5, "heldout_gemini35flash": -0.2,
               "heldout_grok420": 0.1}


def synthetic(seed: int, n_items: int = 600, k: int = 5, contaminate: dict | None = None, all_dates_2020: bool = False):
    """Rasch-style pool + REFERENCE rows for the 17 confirmatory keys.  Dates: 75% uniform 2015..2024, 15% in
    2025 before the openai cutoff, 10% after it and before the xai cutoff (so ~25% post google, ~10% post openai,
    none post xai/anthropic, as in the delivered pools).  Newer items are mildly harder.  `contaminate` maps a key to
    (probability boost, cutoff date): items dated before the cutoff get p += boost."""
    rng = np.random.default_rng(seed)
    keys = [s.key for s in CONFIRMATORY_PANEL]
    if all_dates_2020:
        dates = [date(2020, 1, 1).toordinal() + int(x) for x in rng.integers(0, 366, n_items)]
    else:
        spans = [(date(2015, 1, 1), date(2024, 12, 31), 0.75), (date(2025, 1, 2), date(2025, 11, 30), 0.15),
                 (date(2025, 12, 2), date(2026, 5, 30), 0.10)]
        which = rng.choice(3, size=n_items, p=[s[2] for s in spans])
        dates = [rng.integers(spans[w][0].toordinal(), spans[w][1].toordinal() + 1) for w in which]
    dates = [date.fromordinal(int(o)) for o in dates]
    years = np.array([_years(d) for d in dates])
    diff = rng.normal(0.5, 1.2, n_items) + 0.3 * (years - _years(date(2020, 1, 1))) / 5
    items, rows = [], []
    for i, d in enumerate(dates):
        items.append({"id": f"S{i:04d}", "domain": "synthetic", "source_date": d.isoformat(), "category": "x",
                      "strata": {"year": d.year}, "key_type": "integer", "source": "synthetic",
                      "post_cutoff": d > max(DEVELOPER_CUTOFFS.values()),
                      "post_cutoff_by_developer": {dev: d > c for dev, c in DEVELOPER_CUTOFFS.items()}})
    for key in keys:
        p = 1 / (1 + np.exp(-(SYNTH_THETA[key] - diff)))
        if contaminate and key in contaminate:
            boost, cut = contaminate[key]
            p = np.where(np.array([d < cut for d in dates]), np.minimum(1.0, p + boost), p)
        c = rng.binomial(k, p)
        rows += [{"session_id": "REFERENCE", "item_id": items[i]["id"], "model_key": key, "n_correct": int(c[i]), "n_samples": k}
                 for i in range(n_items)]
    return items, rows


def write_synthetic(out_dir: Path, **kw) -> tuple[Path, Path]:
    items, rows = synthetic(**kw)
    out_dir.mkdir(parents=True, exist_ok=True)
    pool, ref = out_dir / "pool.jsonl", out_dir / "reference_item_outcomes.jsonl"
    pool.write_text("".join(json.dumps(it) + "\n" for it in items))
    ref.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return ref, pool
