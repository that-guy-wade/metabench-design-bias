"""Implementation B of the MetaBench pre-registered endpoints (PREREGISTRATION.md sections 7 and 8).

Written from the pre-registration text and docs/ARTEFACT_SCHEMA.md only; see DECISIONS.md for every choice made where
the text is ambiguous.  Pure numpy/scipy/pandas; every random draw comes from an explicit numpy Generator.
"""
from __future__ import annotations

import glob
import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

TAU_CLIP = 0.9999
LEADER_ARMS = ("sham", "inverted", "narrative", "true_named", "true_blinded", "instructed")


# ----------------------------------------------------------------------------------------------------- loading

def _read_jsonl(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def load_tree(results_dir: str | Path) -> dict:
    """Read a WORK/ tree (ARTEFACT_SCHEMA section 1) into memory.  Returns benchmarks (sorted by session id), the
    per-session config.json and scores_views rows, and the paths of the item-outcome files."""
    root = Path(results_dir)
    bpath = root / "results" / "benchmarks.jsonl"
    if bpath.exists():
        bench = _read_jsonl(bpath)
    else:
        bench = [json.load(open(p)) for p in sorted(glob.glob(str(root / "sessions" / "*" / "benchmark.json")))]
    bench.sort(key=lambda b: b["session_id"])
    configs, views = {}, {}
    for b in bench:
        sdir = root / "sessions" / b["session_id"]
        if (sdir / "config.json").exists():
            configs[b["session_id"]] = json.load(open(sdir / "config.json"))
        if (sdir / "scores_views.jsonl").exists():
            views[b["session_id"]] = _read_jsonl(sdir / "scores_views.jsonl")
    registration = {}
    if (root / "registration_full.json").exists():
        registration = json.load(open(root / "registration_full.json"))
    ref = root / "reference_item_outcomes.jsonl"
    if not ref.exists():
        ref = root / "results" / "reference_item_outcomes.jsonl"
    io = root / "results" / "item_outcomes.jsonl"
    return {"root": root, "benchmarks": bench, "configs": configs, "views": views, "registration": registration,
            "reference_outcomes_path": ref if ref.exists() else None,
            "item_outcomes_path": io if io.exists() else None}


def load_item_outcomes(tree: dict, session_ids: set[str] | None = None) -> pd.DataFrame:
    """Per item x model correctness counts for the produced benchmarks (results/item_outcomes.jsonl or the per-session
    files)."""
    if tree["item_outcomes_path"] is not None:
        df = pd.read_json(tree["item_outcomes_path"], lines=True)
    else:
        parts = []
        for b in tree["benchmarks"]:
            p = tree["root"] / "sessions" / b["session_id"] / "item_outcomes.jsonl"
            if p.exists():
                parts.append(pd.read_json(p, lines=True))
        df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["session_id", "item_id", "model_key", "n_correct", "n_samples"])
    if session_ids is not None:
        df = df[df["session_id"].isin(session_ids)]
    return df.reset_index(drop=True)


def load_reference_outcomes(tree: dict) -> pd.DataFrame | None:
    if tree["reference_outcomes_path"] is None:
        return None
    return pd.read_json(tree["reference_outcomes_path"], lines=True)


def valid_rows(bench: list[dict]) -> list[dict]:
    return [b for b in bench if b.get("valid")]


def rank_panel(bench: list[dict]) -> list[str]:
    """DISPLAYED_KEYS u PLACEBO: every key that is displayed in some session (D2)."""
    keys: set[str] = set()
    for b in bench:
        keys.update(b["displayed_keys"])
    return sorted(keys)


# ----------------------------------------------------------------------------------------------------- rank statistics

def tau_b(scores: dict[str, float], order: list[str]) -> float:
    """Kendall tau-b between produced scores and a displayed order (best first)."""
    x = np.array([scores[k] for k in order], dtype=float)
    y = -np.arange(len(order), dtype=float)
    if len(order) < 2 or np.all(x == x[0]):
        return float("nan")
    return float(stats.kendalltau(x, y, variant="b").statistic)


def tau_b_batch(S: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Vectorised tau-b of every row of S (m, n) against a fixed vector y (n,) with no ties in y."""
    n = S.shape[1]
    iu, ju = np.triu_indices(n, 1)
    ds = np.sign(S[:, iu] - S[:, ju])
    dy = np.sign(y[iu] - y[ju])[None, :]
    conc = (ds * dy).sum(axis=1)
    n0 = n * (n - 1) / 2
    n1 = (ds == 0).sum(axis=1)
    n2 = (dy == 0).sum()
    denom = np.sqrt((n0 - n1) * (n0 - n2))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(denom > 0, conc / denom, np.nan)


def fisher_z(t: float) -> float:
    return float(np.arctanh(np.clip(t, -TAU_CLIP, TAU_CLIP)))


def ranks_desc(scores: dict[str, float], keys: list[str]) -> dict[str, float]:
    """Rank 1 = highest score; ties get the average rank."""
    x = np.array([scores[k] for k in keys], dtype=float)
    r = stats.rankdata(-x, method="average")
    return {k: float(v) for k, v in zip(keys, r)}


def rbo_ext(a: list, b: list, p: float = 0.8) -> float:
    """Rank-biased overlap, extrapolated (Webber, Moffat & Zobel 2010, eq. 32), for two rankings of the same set."""
    k = max(len(a), len(b))
    if k == 0:
        return float("nan")
    sa, sb = set(), set()
    x_d = 0
    s = 0.0
    for d in range(1, k + 1):
        if d <= len(a):
            sa.add(a[d - 1])
        if d <= len(b):
            sb.add(b[d - 1])
        x_d = len(sa & sb)
        s += (x_d / d) * p ** d
    return float((1 - p) / p * s + (x_d / k) * p ** k)


def designer_mean(values_by_designer: dict[str, list[float]]) -> float:
    m = [np.nanmean(v) for v in values_by_designer.values() if len(v) and not np.all(np.isnan(v))]
    return float(np.mean(m)) if m else float("nan")


def ci_from_samples(samples: np.ndarray, level: float = 0.95) -> list[float]:
    s = np.asarray(samples, dtype=float)
    s = s[~np.isnan(s)]
    if s.size == 0:
        return [float("nan"), float("nan")]
    lo, hi = np.percentile(s, [100 * (1 - level) / 2, 100 * (1 + level) / 2])
    return [float(lo), float(hi)]


def designer_cluster_boot(cells: dict[str, dict], per_designer_stat, n_boot: int, rng: np.random.Generator) -> np.ndarray:
    """Designer-cluster bootstrap (D8): designers with replacement, then rows within each cell of each resampled designer.
    cells[d][cell] is a list / array whose first axis indexes that designer's sessions in that cell.
    per_designer_stat(resampled cells dict) -> float (nan if undefined)."""
    designers = sorted(cells)
    D = len(designers)
    out = np.full(n_boot, np.nan)
    for i in range(n_boot):
        idx = rng.integers(0, D, size=D)
        vals = []
        for j in idx:
            d = designers[j]
            res = {}
            for c, arr in cells[d].items():
                arr = np.asarray(arr)
                if arr.shape[0] == 0:
                    res[c] = arr
                else:
                    res[c] = arr[rng.integers(0, arr.shape[0], size=arr.shape[0])]
            v = per_designer_stat(res)
            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                vals.append(v)
        if vals:
            out[i] = float(np.mean(vals))
    return out


def benchmark_boot(rows: list[tuple[str, float]], n_boot: int, rng: np.random.Generator) -> np.ndarray:
    """Benchmark-level bootstrap of the designer-averaged mean (D8): benchmarks resampled i.i.d."""
    d = np.array([r[0] for r in rows])
    v = np.array([r[1] for r in rows], dtype=float)
    n = len(v)
    out = np.full(n_boot, np.nan)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        s = pd.Series(v[idx]).groupby(d[idx]).mean()
        out[i] = float(s.mean())
    return out


def perm_p(null: np.ndarray, observed: float, side: str) -> float:
    null = np.asarray(null, dtype=float)
    null = null[~np.isnan(null)]
    if math.isnan(observed) or null.size == 0:
        return float("nan")
    if side == "greater":
        k = int((null >= observed).sum())
    elif side == "less":
        k = int((null <= observed).sum())
    else:
        k = int((np.abs(null) >= abs(observed)).sum())
    return (1 + k) / (1 + null.size)


def holm(pvals: dict[str, float], alpha: float = 0.05) -> dict[str, dict]:
    """Step-down Holm; nan p-values are left out of the family (reported as such)."""
    items = [(k, v) for k, v in pvals.items() if not (v is None or math.isnan(v))]
    m = len(items)
    order = sorted(items, key=lambda kv: kv[1])
    adj, running = {}, 0.0
    for i, (k, p) in enumerate(order):
        running = max(running, min(1.0, (m - i) * p))
        adj[k] = running
    return {k: {"p": v, "p_holm": adj.get(k, float("nan")), "reject_at_0.05": (adj.get(k, 1.0) < alpha) if k in adj else None,
                "family_size": m} for k, v in pvals.items()}


def bh(pvals: dict[str, float], q: float = 0.05) -> dict[str, dict]:
    items = [(k, v) for k, v in pvals.items() if not (v is None or math.isnan(v))]
    m = len(items)
    order = sorted(items, key=lambda kv: kv[1])
    adj = {}
    running = 1.0
    for i in range(m - 1, -1, -1):
        k, p = order[i]
        running = min(running, p * m / (i + 1))
        adj[k] = running
    return {k: {"p": v, "q_bh": adj.get(k, float("nan")), "reject_at_q0.05": (adj.get(k, 1.0) < q) if k in adj else None}
            for k, v in pvals.items()}


# ----------------------------------------------------------------------------------------------------- per-session table

def session_table(bench: list[dict], configs: dict[str, dict]) -> pd.DataFrame:
    """One row per valid benchmark with every rank statistic the endpoints need (D2-D4)."""
    panel13 = rank_panel(bench)
    rows = []
    for b in valid_rows(bench):
        disp = b["displayed_keys"]
        prod = b["produced_scores"]
        ref = b["reference_scores"]
        ref_order = sorted(disp, key=lambda k: (-ref[k], k))
        cfg = configs.get(b["session_id"], {})
        told = cfg.get("false_identity")
        if told is None and b["identity_arm"] == "false":
            # the key whose shown label is the designer's real name but that is not the designer
            own_label = b["label_map"].get(b["designer"])
            told = next((k for k, lab in b["label_map"].items() if lab == own_label and k != b["designer"]), None)
        r13 = ranks_desc(prod, panel13)
        pm = float(np.mean([prod[k] for k in panel13]))
        rel13 = {k: float(prod[k] - pm) for k in panel13}
        rows.append({
            "session_id": b["session_id"], "designer": b["designer"], "info_arm": b["info_arm"], "identity_arm": b["identity_arm"],
            "cell": f'{b["info_arm"]}/{b["identity_arm"]}', "n_displayed": len(disp), "named": b["named"],
            "displayed_order": b.get("displayed_order"), "intended_displayed_order": b.get("intended_displayed_order"),
            "displayed_leader": b.get("displayed_leader"), "target_model": b.get("target_model"), "told_identity": told,
            "n_score_requests": b.get("n_score_requests", 0),
            "tau_disp": tau_b(prod, b["displayed_order"]) if b.get("displayed_order") else float("nan"),
            "tau_ref": tau_b(prod, ref_order), "tau_ref_rev": tau_b(prod, ref_order[::-1]),
            "rbo_disp": (rbo_ext(sorted(disp, key=lambda k: (-prod[k], k)), b["displayed_order"], 0.8)
                         if b.get("displayed_order") else float("nan")),
            "rank13": r13, "rel13": rel13, "disp_scores": {k: prod[k] for k in disp},
            "displayed_keys": list(disp),
        })
    df = pd.DataFrame(rows)
    df.attrs["panel13"] = panel13
    df.attrs["reference_gap"] = reference_gap(bench, panel13)
    v = valid_rows(bench)
    df.attrs["reference_scores"] = {k: v[0]["reference_scores"][k] for k in panel13} if v else {}
    return df


def reference_gap(bench: list[dict], panel13: list[str]) -> float:
    """Median adjacent gap of the reference scores over the 13-key panel (the pre-registration's rank-gap unit)."""
    v = valid_rows(bench) or bench
    if not v:
        return float("nan")
    ref = sorted(v[0]["reference_scores"][k] for k in panel13)
    return float(np.median(np.diff(ref)))


# ----------------------------------------------------------------------------------------------------- primary

def primary_endpoint(df: pd.DataFrame, n_perm: int, n_boot: int, rng: np.random.Generator) -> dict:
    pop = df[(df.info_arm == "sham") & (df.identity_arm == "blinded")].copy()
    pop = pop.sort_values("session_id").reset_index(drop=True)
    out: dict = {"definition": "designer-averaged mean of atanh(tau-b(produced ranking of displayed panel, displayed order at first "
                               "request_panel_scores)), sham information arm, pseudonymous (blinded) identity arm",
                 "n_benchmarks": int(len(pop)), "n_designers": int(pop.designer.nunique()),
                 "n_never_requested_scores": int((pop.n_score_requests == 0).sum()),
                 "n_displayed_order_mismatch": int(sum(1 for _, r in pop.iterrows()
                                                      if r.intended_displayed_order is not None and r.displayed_order != r.intended_displayed_order))}
    if len(pop) == 0:
        out.update({"estimate_tanh": float("nan"), "estimate_z": float("nan")})
        return out
    pop["z"] = pop.tau_disp.map(fisher_z)
    by_d = {d: g.z.tolist() for d, g in pop.groupby("designer")}
    psi = designer_mean(by_d)
    out["estimate_z"] = psi
    out["estimate_tanh"] = float(np.tanh(psi))
    out["mean_tau_unaveraged"] = float(pop.tau_disp.mean())
    out["per_designer"] = {d: {"n": len(v), "mean_z": float(np.mean(v)), "mean_tau": float(np.mean(np.tanh(v)))} for d, v in by_d.items()}

    # randomisation test (D7): uniform permutation of each session's displayed keys, scores fixed
    designers = sorted(by_d)
    d_index = np.array([designers.index(d) for d in pop.designer])
    Z = np.zeros((n_perm, len(pop)))
    for i, r in pop.iterrows():
        s = np.array([r.disp_scores[k] for k in r.displayed_keys], dtype=float)
        n = len(s)
        perms = np.argsort(rng.random((n_perm, n)), axis=1)
        S = s[perms]
        y = -np.arange(n, dtype=float)
        Z[:, i] = np.arctanh(np.clip(tau_b_batch(S, y), -TAU_CLIP, TAU_CLIP))
    counts = np.bincount(d_index, minlength=len(designers))
    sums = np.zeros((n_perm, len(designers)))
    for j in range(len(designers)):
        sums[:, j] = Z[:, d_index == j].sum(axis=1)
    psi_star = (sums / counts[None, :]).mean(axis=1)
    out["randomisation"] = {"n_perm": int(n_perm), "p_one_sided": perm_p(psi_star, psi, "greater"),
                            "null_mean_z": float(psi_star.mean()), "null_sd_z": float(psi_star.std(ddof=1)),
                            "generator": "uniform permutation of displayed_keys per session (pseudonymous sham)"}

    # designer-cluster bootstrap and benchmark-level bootstrap (D8)
    cells = {d: {"z": np.array(v)} for d, v in by_d.items()}
    boot = designer_cluster_boot(cells, lambda c: float(np.mean(c["z"])), n_boot, rng)
    ci_z = ci_from_samples(boot)
    out["cluster_bootstrap"] = {"n_boot": int(n_boot), "ci95_z": ci_z, "ci95_tanh": [float(np.tanh(ci_z[0])), float(np.tanh(ci_z[1]))],
                                "excludes_zero": bool(ci_z[0] > 0 or ci_z[1] < 0)}
    bboot = benchmark_boot(list(zip(pop.designer, pop.z)), n_boot, rng)
    ci_b = ci_from_samples(bboot)
    out["benchmark_bootstrap"] = {"n_boot": int(n_boot), "ci95_z": ci_b, "ci95_tanh": [float(np.tanh(ci_b[0])), float(np.tanh(ci_b[1]))]}

    # designer-level one-sided t on per-designer mean Fisher-z tau (the equivalent heterogeneity-respecting criterion)
    dm = np.array([np.mean(v) for v in by_d.values()])
    if len(dm) >= 2 and dm.std(ddof=1) > 0:
        t = dm.mean() / (dm.std(ddof=1) / math.sqrt(len(dm)))
        out["designer_t"] = {"t": float(t), "df": int(len(dm) - 1), "p_one_sided": float(stats.t.sf(t, len(dm) - 1)),
                             "ci95_z": [float(dm.mean() - stats.t.ppf(0.975, len(dm) - 1) * dm.std(ddof=1) / math.sqrt(len(dm))),
                                        float(dm.mean() + stats.t.ppf(0.975, len(dm) - 1) * dm.std(ddof=1) / math.sqrt(len(dm)))]}
    else:
        out["designer_t"] = {"t": float("nan"), "df": int(len(dm) - 1), "p_one_sided": float("nan")}
    out["claim"] = {"estimate_tanh_gt_0.15": bool(out["estimate_tanh"] > 0.15),
                    "cluster_ci_excludes_zero": out["cluster_bootstrap"]["excludes_zero"],
                    "randomisation_p_lt_0.05": bool(out["randomisation"]["p_one_sided"] < 0.05)}
    out["claim"]["all_three"] = all(out["claim"].values())
    return out


# ----------------------------------------------------------------------------------------------------- secondaries

def _designer_cells(df: pd.DataFrame, value_col: str, cells: list[str]) -> dict[str, dict[str, np.ndarray]]:
    out: dict[str, dict[str, np.ndarray]] = {}
    for d, g in df.groupby("designer"):
        out[d] = {c: g.loc[g.cell == c, value_col].to_numpy(dtype=float) for c in cells}
    return out


def _label_perm_diff(df: pd.DataFrame, value_col: str, cell_a: str, cell_b: str, n_perm: int, rng: np.random.Generator,
                     side: str) -> dict:
    """Designer-averaged mean(value | cell_a) - mean(value | cell_b), within-designer label permutation test (D14)."""
    sub = df[df.cell.isin([cell_a, cell_b])].sort_values("session_id")
    per_d, groups = {}, []
    for d, g in sub.groupby("designer"):
        va = g.loc[g.cell == cell_a, value_col].to_numpy(dtype=float)
        vb = g.loc[g.cell == cell_b, value_col].to_numpy(dtype=float)
        if len(va) == 0 or len(vb) == 0 or np.all(np.isnan(va)) or np.all(np.isnan(vb)):
            continue
        per_d[d] = float(np.nanmean(va) - np.nanmean(vb))
        groups.append((np.concatenate([va, vb]), len(va)))
    est = float(np.mean(list(per_d.values()))) if per_d else float("nan")
    null = np.full(n_perm, np.nan)
    if groups:
        for i in range(n_perm):
            vals = []
            for v, na in groups:
                p = rng.permutation(len(v))
                vals.append(np.nanmean(v[p[:na]]) - np.nanmean(v[p[na:]]))
            null[i] = float(np.mean(vals))
    return {"estimate": est, "per_designer": per_d, "n_designers": len(per_d),
            "n_a": int((sub.cell == cell_a).sum()), "n_b": int((sub.cell == cell_b).sum()),
            "permutation": {"n_perm": int(n_perm), "p": perm_p(null, est, side), "side": side,
                            "scheme": f"within-designer shuffle of {cell_a} vs {cell_b} labels"}}


def s1_leader_gain(df: pd.DataFrame, pop_cells: list[str], n_perm: int, n_boot: int, rng: np.random.Generator,
                   leader_draw: str = "displayed_keys", measure: str = "rank") -> dict:
    """S1: produced rank of the displayed/narrated leader vs the same designer's none-arm mean rank of that model (D10-D12).
    leader_draw: 'displayed_keys' (uniform over the session's displayed keys) or 'observed' (uniform over the set of leaders seen
    in the population's cells, used for the named sham arms whose within-tier generator is not in the schema)."""
    panel13 = df.attrs["panel13"]
    col, sgn = ("rank13", 1.0) if measure == "rank" else ("rel13", -1.0)   # gain = base - rank; score gain = rel - base
    none = df[df.cell == "none/blinded"]
    base: dict[str, np.ndarray] = {}        # designer -> (n_none, 13) matrix
    for d, g in none.groupby("designer"):
        base[d] = np.array([[r[k] for k in panel13] for r in g[col]], dtype=float)
    pop = df[df.cell.isin(pop_cells) & df.displayed_leader.notna()].sort_values("session_id")
    pop = pop[pop.designer.isin(base)]
    n_dropped = int(df.cell.isin(pop_cells).sum() - len(pop))
    observed_leaders = sorted(set(pop.displayed_leader))
    cells: dict[str, dict] = {}
    gains, per_session = [], []
    for d, g in pop.groupby("designer"):
        R = np.array([[r[k] for k in panel13] for r in g[col]], dtype=float)       # (n, 13) produced ranks / relative scores
        L = np.array([panel13.index(l) for l in g.displayed_leader])
        cand = []
        for r in g.itertuples():
            keys = r.displayed_keys if leader_draw == "displayed_keys" else observed_leaders
            cand.append(np.array([panel13.index(k) for k in keys]))
        cells[d] = {"none": base[d], "pop": np.arange(len(g))}
        cells[d]["_R"], cells[d]["_L"], cells[d]["_cand"] = R, L, cand
        bmean = base[d].mean(axis=0)
        gd = sgn * (bmean[L] - R[np.arange(len(g)), L])
        gains.append((d, gd))
        for sid, l, gg in zip(g.session_id, g.displayed_leader, gd):
            per_session.append({"session_id": sid, "designer": d, "leader": l, "gain_positions": float(gg)})
    by_d = {d: list(gd) for d, gd in gains}
    est = designer_mean(by_d)
    # permutation over the identity of the leader
    null = np.full(n_perm, np.nan)
    if by_d:
        per_d_null = []
        for d, gd in gains:
            c = cells[d]
            bmean = base[d].mean(axis=0)
            n = len(gd)
            draws = np.zeros((n_perm, n))
            for i in range(n):
                cand = c["_cand"][i]
                m = cand[rng.integers(0, len(cand), size=n_perm)]
                draws[:, i] = sgn * (bmean[m] - c["_R"][i, m])
            per_d_null.append(draws.mean(axis=1))
        null = np.mean(per_d_null, axis=0)

    def stat(c):
        if c["none"].shape[0] == 0 or len(c["pop"]) == 0:
            return float("nan")
        bmean = c["none"].mean(axis=0)
        idx = c["pop"]
        return float(np.mean(sgn * (bmean[c["_L"][idx]] - c["_R"][idx, c["_L"][idx]])))

    boot_cells = {d: {"none": cells[d]["none"], "pop": cells[d]["pop"]} for d in cells}
    for d in cells:
        boot_cells[d]["_R"], boot_cells[d]["_L"] = cells[d]["_R"], cells[d]["_L"]

    def stat_wrapped(c):
        return stat(c)

    # designer_cluster_boot resamples every array in the dict; keep _R/_L fixed by excluding them from resampling
    class _Fixed(dict):
        pass

    def boot_fn(n_boot_):
        designers = sorted(boot_cells)
        D = len(designers)
        out = np.full(n_boot_, np.nan)
        for i in range(n_boot_):
            idx = rng.integers(0, D, size=D)
            vals = []
            for j in idx:
                d = designers[j]
                c = boot_cells[d]
                none_r = c["none"][rng.integers(0, c["none"].shape[0], size=c["none"].shape[0])] if c["none"].shape[0] else c["none"]
                pop_i = c["pop"][rng.integers(0, len(c["pop"]), size=len(c["pop"]))] if len(c["pop"]) else c["pop"]
                v = stat({"none": none_r, "pop": pop_i, "_R": c["_R"], "_L": c["_L"]})
                if not math.isnan(v):
                    vals.append(v)
            if vals:
                out[i] = float(np.mean(vals))
        return out

    boot = boot_fn(n_boot)
    if measure == "rank":
        definition = ("mean none-arm produced rank of the leader (same designer) minus produced rank of the leader in the "
                      "session, positions, positive = leader moved toward rank 1; ranks among the fixed 13-key panel")
    else:
        definition = ("leader's produced score minus the 13-key panel mean, minus the same quantity for that model in the designer's "
                      "none-arm benchmarks; accuracy points (x100 = percentage points); gap_units divides by the reference median adjacent gap")
    gap = df.attrs.get("reference_gap", float("nan"))
    return {"definition": definition, "measure": measure,
            "cells": pop_cells, "n_benchmarks": int(len(pop)), "n_designers": len(by_d), "n_dropped_no_none_baseline": n_dropped,
            ("estimate_positions" if measure == "rank" else "estimate_accuracy"): est,
            **({"estimate_gap_units": est / gap if gap and gap > 0 else float("nan"), "reference_gap": gap,
                "ci95_gap_units": [v / gap for v in ci_from_samples(boot)] if gap and gap > 0 else None} if measure == "score" else {}),
            "per_designer": {d: {"n": len(v), "mean": float(np.mean(v))} for d, v in by_d.items()},
            "cluster_bootstrap": {"n_boot": int(n_boot), "ci95": ci_from_samples(boot)},
            "permutation": {"n_perm": int(n_perm), "p_one_sided": perm_p(null, est, "greater"),
                            "leader_generator": ("uniform over the session's displayed_keys" if leader_draw == "displayed_keys"
                                                 else f"uniform over the observed leader set {observed_leaders} (empirical tier-1 proxy)")},
            "per_session": per_session}


def s2_identity(df: pd.DataFrame, n_perm: int, n_boot: int, rng: np.random.Generator) -> dict:
    """S2 within the sham information arm (D13): S2a self gain true vs blinded; S2b told-identity gain under the false label;
    S2c actual-self gain under the false label."""
    panel13 = df.attrs["panel13"]
    sham = df[df.info_arm == "sham"].copy()
    sham["rank_self"] = [r[d] if d in r else float("nan") for r, d in zip(sham.rank13, sham.designer)]
    sham["rel_self"] = [r[d] if d in r else float("nan") for r, d in zip(sham.rel13, sham.designer)]
    gap = df.attrs.get("reference_gap", float("nan"))
    out: dict = {"arm": "sham", "definition": "positions, positive = the entry moved toward rank 1 relative to sham/blinded; ranks among the fixed 13-key panel",
                 "reference_gap": gap}
    # score-scale companions (accuracy points relative to the 13-key panel mean, and in reference-gap units)
    sc = {}
    for key, a_cell, b_cell in (("S2a_self_gain_true_label", "sham/true", "sham/blinded"), ("S2c_actual_self_gain_false_label", "sham/false", "sham/blinded")):
        r_ = _label_perm_diff(sham, "rel_self", a_cell, b_cell, n_perm, rng, "greater")
        cells_ = _designer_cells(sham, "rel_self", [a_cell, b_cell])
        b_ = designer_cluster_boot(cells_, lambda c, a_cell=a_cell, b_cell=b_cell: float(np.mean(c[a_cell]) - np.mean(c[b_cell]))
                                   if len(c[a_cell]) and len(c[b_cell]) else float("nan"), n_boot, rng)
        ci = ci_from_samples(b_)
        sc[key] = {"estimate_accuracy": r_["estimate"], "estimate_gap_units": r_["estimate"] / gap if gap and gap > 0 else float("nan"),
                   "ci95_accuracy": ci, "ci95_gap_units": [v / gap for v in ci] if gap and gap > 0 else None, "p_unadjusted": r_["permutation"]["p"]}
    sc["S2b_told_identity_gain_false_label"] = _s2b(sham, panel13, "rel13", -1.0, n_perm, n_boot, rng, gap)
    out["score_shift"] = sc
    # S2a: rank(self) blinded - rank(self) true
    a = _label_perm_diff(sham, "rank_self", "sham/blinded", "sham/true", n_perm, rng, "greater")
    cells_a = _designer_cells(sham, "rank_self", ["sham/blinded", "sham/true"])
    boot_a = designer_cluster_boot(cells_a, lambda c: float(np.mean(c["sham/blinded"]) - np.mean(c["sham/true"]))
                                   if len(c["sham/blinded"]) and len(c["sham/true"]) else float("nan"), n_boot, rng)
    out["S2a_self_gain_true_label"] = {**a, "cluster_bootstrap": {"n_boot": int(n_boot), "ci95": ci_from_samples(boot_a)}}
    # S2c: rank(self) blinded - rank(self) false
    c_ = _label_perm_diff(sham, "rank_self", "sham/blinded", "sham/false", n_perm, rng, "greater")
    cells_c = _designer_cells(sham, "rank_self", ["sham/blinded", "sham/false"])
    boot_c = designer_cluster_boot(cells_c, lambda c: float(np.mean(c["sham/blinded"]) - np.mean(c["sham/false"]))
                                   if len(c["sham/blinded"]) and len(c["sham/false"]) else float("nan"), n_boot, rng)
    out["S2c_actual_self_gain_false_label"] = {**c_, "cluster_bootstrap": {"n_boot": int(n_boot), "ci95": ci_from_samples(boot_c)}}
    out["S2b_told_identity_gain_false_label"] = _s2b(sham, panel13, "rank13", 1.0, n_perm, n_boot, rng, gap)
    out["S2a_halved_under_pseudonyms_check"] = {
        "note": "the claim compares self gain under the true label with its value under pseudonyms; the sham/blinded arm is the "
                "pseudonymous baseline, so S2a itself is the true-minus-pseudonym difference"}
    return out


def _s2b(sham: pd.DataFrame, panel13: list[str], col: str, sgn: float, n_perm: int, n_boot: int, rng: np.random.Generator, gap: float) -> dict:
    """Told-identity gain under the false label: sgn * (mean over sham/blinded of value[told] - value[told] in the false session)."""
    per_d, groups, cells_b = {}, [], {}
    for d, g in sham[sham.cell.isin(["sham/blinded", "sham/false"])].groupby("designer"):
        bl = g[g.cell == "sham/blinded"]
        fa = g[(g.cell == "sham/false") & g.told_identity.notna()]
        if len(bl) == 0 or len(fa) == 0:
            continue
        B = np.array([[r[k] for k in panel13] for r in bl[col]], dtype=float)
        F = np.array([[r[k] for k in panel13] for r in fa[col]], dtype=float)
        T = np.array([panel13.index(t) for t in fa.told_identity])
        per_d[d] = float(np.mean(sgn * (B.mean(axis=0)[T] - F[np.arange(len(T)), T])))
        groups.append((np.vstack([B, F]), len(B), T))
        cells_b[d] = {"B": B, "F_idx": np.arange(len(T)), "_F": F, "_T": T}
    est_b = float(np.mean(list(per_d.values()))) if per_d else float("nan")
    null = np.full(n_perm, np.nan)
    for i in range(n_perm):
        vals = []
        for M, nb, T in groups:
            p = rng.permutation(M.shape[0])
            Bp, Fp = M[p[:nb]], M[p[nb:]]
            vals.append(np.mean(sgn * (Bp.mean(axis=0)[T] - Fp[np.arange(len(T)), T])))
        if vals:
            null[i] = float(np.mean(vals))

    def stat_b(c):
        if c["B"].shape[0] == 0 or len(c["F_idx"]) == 0:
            return float("nan")
        idx = c["F_idx"]
        T = c["_T"][idx]
        return float(np.mean(sgn * (c["B"].mean(axis=0)[T] - c["_F"][idx, T])))

    designers = sorted(cells_b)
    boot_b = np.full(n_boot, np.nan)
    for i in range(n_boot):
        vals = []
        for j in rng.integers(0, len(designers), size=len(designers)) if designers else []:
            c = cells_b[designers[j]]
            Br = c["B"][rng.integers(0, c["B"].shape[0], size=c["B"].shape[0])]
            Fi = c["F_idx"][rng.integers(0, len(c["F_idx"]), size=len(c["F_idx"]))]
            v = stat_b({"B": Br, "F_idx": Fi, "_F": c["_F"], "_T": c["_T"]})
            if not math.isnan(v):
                vals.append(v)
        if vals:
            boot_b[i] = float(np.mean(vals))
    ci = ci_from_samples(boot_b)
    out = {"estimate": est_b, "per_designer": per_d, "n_designers": len(per_d), "n_false": int(sum(len(T) for _, _, T in groups)),
           "permutation": {"n_perm": int(n_perm), "p": perm_p(null, est_b, "greater"), "side": "greater",
                           "scheme": "within-designer shuffle of blinded/false labels; told identities travel with the false label"},
           "cluster_bootstrap": {"n_boot": int(n_boot), "ci95": ci}}
    if col != "rank13":
        out.update({"estimate_accuracy": est_b, "estimate_gap_units": est_b / gap if gap and gap > 0 else float("nan"),
                    "ci95_gap_units": [v / gap for v in ci] if gap and gap > 0 else None})
    return out


def s3_inverted(df: pd.DataFrame, n_perm: int, n_boot: int, rng: np.random.Generator) -> dict:
    sub = df[df.cell.isin(["inverted/blinded", "none/blinded"])].copy()
    # the none-arm comparator is the registered inverted order itself (A7): the modal intended order of the inverted sessions
    inv_orders = [tuple(o) for o in sub.loc[sub.info_arm == "inverted", "intended_displayed_order"] if o]
    registered = list(max(set(inv_orders), key=inv_orders.count)) if inv_orders else None
    def none_val(r):
        if registered and set(registered) == set(r.displayed_keys):
            return tau_b(r.disp_scores, registered)
        return r.tau_ref_rev
    sub["val"] = [r.tau_disp if r.info_arm == "inverted" else none_val(r) for r in sub.itertuples()]
    r = _label_perm_diff(sub, "val", "inverted/blinded", "none/blinded", n_perm, rng, "greater")
    cells = _designer_cells(sub, "val", ["inverted/blinded", "none/blinded"])
    boot = designer_cluster_boot(cells, lambda c: float(np.mean(c["inverted/blinded"]) - np.mean(c["none/blinded"]))
                                 if len(c["inverted/blinded"]) and len(c["none/blinded"]) else float("nan"), n_boot, rng)
    return {"definition": "tau-b(produced, inverted display) in inverted/blinded minus tau-b(produced, registered inverted order = reverse "
                          "of the reference ranking) in none/blinded, raw tau",
            "none_arm_comparator": "registered inverted order" if registered else "reverse of reference_scores", **r, "mean_tau_inverted": float(sub.loc[sub.info_arm == "inverted", "val"].mean()),
            "mean_tau_none_vs_reversed_reference": float(sub.loc[sub.info_arm == "none", "val"].mean()),
            "cluster_bootstrap": {"n_boot": int(n_boot), "ci95": ci_from_samples(boot)}}


def s4_true_minus_none(df: pd.DataFrame, n_perm: int, n_boot: int, rng: np.random.Generator) -> dict:
    sub = df[df.info_arm.isin(["true_named", "true_blinded", "none"])].copy()
    sub["cell2"] = np.where(sub.info_arm == "none", "none", "true")
    sub["cell_orig"] = sub.cell
    sub["cell"] = sub["cell2"]
    r = _label_perm_diff(sub, "tau_ref", "true", "none", n_perm, rng, "two-sided")
    cells = _designer_cells(sub, "tau_ref", ["true", "none"])
    boot = designer_cluster_boot(cells, lambda c: float(np.mean(c["true"]) - np.mean(c["none"]))
                                 if len(c["true"]) and len(c["none"]) else float("nan"), n_boot, rng)
    per_arm = {}
    for arm in ("true_named", "true_blinded"):
        sub["cell"] = np.where(sub.info_arm == arm, arm, np.where(sub.info_arm == "none", "none", "other"))
        rr = _label_perm_diff(sub, "tau_ref", arm, "none", n_perm, rng, "two-sided")
        per_arm[arm] = {"estimate": rr["estimate"], "n": rr["n_a"], "p_unadjusted": rr["permutation"]["p"]}
    return {"definition": "tau-b(produced, reference order over displayed keys): true-score arms (true_named + true_blinded) minus none arm, raw tau",
            **r, "cluster_bootstrap": {"n_boot": int(n_boot), "ci95": ci_from_samples(boot)}, "per_arm": per_arm,
            "mean_tau_ref_true": float(sub.loc[sub.cell2 == "true", "tau_ref"].mean()),
            "mean_tau_ref_none": float(sub.loc[sub.cell2 == "none", "tau_ref"].mean())}


def secondary_endpoints(df: pd.DataFrame, n_perm: int, n_boot: int, rng: np.random.Generator) -> dict:
    s1 = s1_leader_gain(df, ["sham/blinded", "narrative/blinded"], n_perm, n_boot, rng)
    s1_score = s1_leader_gain(df, ["sham/blinded", "narrative/blinded"], n_perm, n_boot, rng, measure="score")
    s1["score_shift"] = {k: v for k, v in s1_score.items() if k not in ("per_session", "cells", "n_benchmarks", "n_designers", "n_dropped_no_none_baseline")}
    s1["per_session_score_gain_accuracy"] = {r["session_id"]: r["gain_positions"] for r in s1_score["per_session"]}
    s1_named = s1_leader_gain(df, ["sham/true", "sham/false"], n_perm, n_boot, rng, leader_draw="observed")
    s1_by_arm = {c: s1_leader_gain(df, [c], n_perm // 5 if n_perm >= 5 else n_perm, n_boot // 5 if n_boot >= 5 else n_boot, rng)
                 for c in ("sham/blinded", "narrative/blinded")}
    for v in s1_by_arm.values():
        v.pop("per_session", None)
    s2 = s2_identity(df, n_perm, n_boot, rng)
    s3 = s3_inverted(df, n_perm, n_boot, rng)
    s4 = s4_true_minus_none(df, n_perm, n_boot, rng)
    family = {"S1_leader_gain": s1["permutation"]["p_one_sided"], "S2_self_gain_true_label": s2["S2a_self_gain_true_label"]["permutation"]["p"],
              "S3_inverted_tau": s3["permutation"]["p"], "S4_true_minus_none_tau": s4["permutation"]["p"]}
    s1_main = dict(s1)
    per_session = s1_main.pop("per_session")
    score_by_sid = s1_main.pop("per_session_score_gain_accuracy")
    for r in per_session:
        r["gain_accuracy"] = score_by_sid.get(r["session_id"])
    return {"S1": s1_main, "S1_supplementary_named_sham": {k: v for k, v in s1_named.items() if k != "per_session"},
            "S1_by_arm": s1_by_arm, "S1_per_session": per_session, "S2": s2, "S3": s3, "S4": s4, "holm": holm(family)}


# ----------------------------------------------------------------------------------------------------- exploratory

def exploratory(df: pd.DataFrame, tree: dict, n_perm: int, n_boot: int, rng: np.random.Generator,
                item_outcomes: pd.DataFrame | None) -> dict:
    out: dict = {}
    pop = df[(df.info_arm == "sham") & (df.identity_arm == "blinded")].sort_values("session_id")
    # RBO p = 0.8 (D22)
    by_d = {d: g.rbo_disp.tolist() for d, g in pop.groupby("designer")}
    est = designer_mean(by_d)
    null = np.full(n_perm, np.nan)
    if len(pop):
        designers = sorted(by_d)
        d_index = np.array([designers.index(d) for d in pop.designer])
        n_p = min(n_perm, 2000)
        R = np.zeros((n_p, len(pop)))
        for i, r in enumerate(pop.itertuples()):
            produced = sorted(r.displayed_keys, key=lambda k: (-r.disp_scores[k], k))
            keys = list(r.displayed_keys)
            for j in range(n_p):
                perm = rng.permutation(len(keys))
                R[j, i] = rbo_ext(produced, [keys[t] for t in perm], 0.8)
        null = np.array([np.mean([R[j, d_index == q].mean() for q in range(len(designers))]) for j in range(n_p)])
    boot = designer_cluster_boot({d: {"v": np.array(v)} for d, v in by_d.items()}, lambda c: float(np.mean(c["v"])), n_boot, rng)
    out["rbo_p0.8_sham_blinded"] = {"estimate": est, "n_benchmarks": int(len(pop)), "n_designers": len(by_d),
                                    "cluster_bootstrap": {"n_boot": int(n_boot), "ci95": ci_from_samples(boot)},
                                    "randomisation": {"n_perm": int(len(null[~np.isnan(null)])), "p_one_sided": perm_p(null, est, "greater"),
                                                      "null_mean": float(np.nanmean(null)) if len(pop) else float("nan")}}
    # round-by-round trajectories (D24)
    traj: dict[int, dict[str, list[float]]] = {}
    for r in pop.itertuples():
        for v in tree["views"].get(r.session_id, []):
            if not v.get("order") or "true_all" not in v:
                continue
            sc = {k: v["true_all"][k] for k in r.displayed_order if k in v["true_all"]}
            if len(sc) != len(r.displayed_order):
                continue
            traj.setdefault(int(v["round"]), {}).setdefault(r.designer, []).append(tau_b(sc, r.displayed_order))
    rounds = {}
    pvals = {}
    for rd in sorted(traj):
        cells = {d: {"v": np.array(v)} for d, v in traj[rd].items()}
        b = designer_cluster_boot(cells, lambda c: float(np.nanmean(c["v"])), n_boot, rng)
        dm = np.array([np.nanmean(v) for v in traj[rd].values()])
        t = dm.mean() / (dm.std(ddof=1) / math.sqrt(len(dm))) if len(dm) > 1 and dm.std(ddof=1) > 0 else float("nan")
        p = float(stats.t.sf(t, len(dm) - 1)) if not math.isnan(t) else float("nan")
        rounds[str(rd)] = {"mean_tau_draft_vs_display": designer_mean(traj[rd]), "n_views": int(sum(len(v) for v in traj[rd].values())),
                           "n_designers": len(traj[rd]), "ci95_cluster": ci_from_samples(b), "designer_t_p_one_sided": p}
        pvals[f"round_{rd}"] = p
    out["round_trajectories_sham_blinded"] = {"by_round": rounds, "final_submitted_tau": float(pop.tau_disp.mean()) if len(pop) else float("nan")}
    pvals["rbo"] = out["rbo_p0.8_sham_blinded"]["randomisation"]["p_one_sided"]
    out["benjamini_hochberg_q0.05"] = bh(pvals)
    # item-level DIF screen (D23)
    out["dif_screen_mantel_haenszel"] = dif_screen(df, item_outcomes) if item_outcomes is not None else {"status": "no item outcomes"}
    return out


def dif_screen(df: pd.DataFrame, io: pd.DataFrame) -> dict:
    """Per-item Mantel-Haenszel D-DIF, focal = the benchmark's Target model, reference = other panel models in the same ability
    stratum.  Two matching criteria are reported (A10): the pre-registered one (total score on the benchmark including the
    studied item, Holland & Thayer) and an anchor-matched one (full-pool reference score tercile), which is robust to a
    whole-benchmark tilt toward the target that contaminates the total-score criterion.  Descriptive only."""
    def _lead(r):
        for v in (r.target_model, r.displayed_leader):
            if isinstance(v, str):
                return v
        return None
    tgt = {r.session_id: _lead(r) for r in df.itertuples() if _lead(r) is not None}
    sub = io[io.session_id.isin(tgt)].copy()
    if sub.empty:
        return {"status": "no sessions with a target", "n_items": 0}
    sub["target"] = sub.session_id.map(tgt)
    # outcomes for (item, model) are precomputed once and reused by every benchmark containing the item, so an (item, target)
    # pair is one piece of evidence however many sessions share it: keep its first session only (A8)
    first = sub.drop_duplicates(["item_id", "target"])[["item_id", "target", "session_id"]]
    sub = sub.merge(first, on=["item_id", "target", "session_id"])
    n_pairs = int(len(first))
    tot = io[io.session_id.isin(set(first.session_id))].groupby(["session_id", "model_key"], as_index=False).agg(c=("n_correct", "sum"), n=("n_samples", "sum"))
    tot["ability"] = tot.c / tot.n
    tot["tercile"] = tot.groupby("session_id")["ability"].transform(lambda a: pd.qcut(a.rank(method="first"), 3, labels=False))
    ref_scores = core_reference_scores(df)
    out = {"status": "ok", "n_sessions_with_target": int(len(tgt)), "n_unique_item_target_pairs": n_pairs,
           "convention": ("ETS delta_MH = 2.35 ln(alpha) with alpha the Mantel-Haenszel odds of a correct answer for the focal (target) model "
                          "relative to its matched reference models; positive favours the target"),
           "caveat": ("outcomes per (item, model) are fixed precomputed draws, so once every model has been a target on an item the "
                      "anchor-matched MH odds ratio is identically 1 and the total-score-matched one is driven by criterion contamination; "
                      "the selection signal is carried by gamma in the measurement model, not by this screen (A10)"),
           "total_score_matching": _mh(sub.merge(tot[["session_id", "model_key", "tercile"]], on=["session_id", "model_key"]))}
    return out


def core_reference_scores(df: pd.DataFrame) -> dict[str, float]:
    return dict(df.attrs.get("reference_scores", {}))


def _mh(sub: pd.DataFrame) -> dict:
    foc = sub[sub.model_key == sub.target][["session_id", "item_id", "tercile", "n_correct", "n_samples"]].rename(
        columns={"tercile": "ft", "n_correct": "A", "n_samples": "nA"})
    foc["B"] = foc.nA - foc.A
    ref = sub[sub.model_key != sub.target].merge(foc[["session_id", "item_id", "ft"]], on=["session_id", "item_id"])
    ref = ref[ref.tercile == ref.ft].groupby(["session_id", "item_id"], as_index=False).agg(C=("n_correct", "sum"), nC=("n_samples", "sum"))
    ref["D"] = ref.nC - ref.C
    t = foc.merge(ref[["session_id", "item_id", "C", "D"]], on=["session_id", "item_id"])
    t["N"] = t.A + t.B + t.C + t.D
    t = t[t.N > 0].copy()
    t["ad"] = t.A * t.D / t.N
    t["bc"] = t.B * t.C / t.N
    t["P"] = (t.A + t.D) / t.N
    t["Q"] = (t.B + t.C) / t.N
    t["pr"] = t.P * t.ad
    t["ps_qr"] = t.P * t.bc + t.Q * t.ad
    t["qs"] = t.Q * t.bc
    g = t.groupby("item_id").agg(R=("ad", "sum"), S=("bc", "sum"), PR=("pr", "sum"), PS_QR=("ps_qr", "sum"), QS=("qs", "sum"), n_strata=("N", "size"))
    g = g[(g.R > 0) & (g.S > 0)].copy()
    g["ln_alpha"] = np.log(g.R / g.S)
    g["var_ln"] = g.PR / (2 * g.R ** 2) + g.PS_QR / (2 * g.R * g.S) + g.QS / (2 * g.S ** 2)      # Robins-Breslow-Greenland
    g["d_dif"] = 2.35 * g.ln_alpha
    g["d_se"] = 2.35 * np.sqrt(g.var_ln)
    g["d_lo"] = g.d_dif - 1.96 * g.d_se
    g["d_hi"] = g.d_dif + 1.96 * g.d_se
    z = g.ln_alpha / np.sqrt(g.var_ln)
    g["p"] = 2 * stats.norm.sf(np.abs(z))

    def cls(row):
        a = abs(row.d_dif)
        if a < 1.0 or row.p >= 0.05:
            return "A"
        if a >= 1.5 and (row.d_lo >= 1.0 if row.d_dif > 0 else row.d_hi <= -1.0):
            return "C"
        return "B"

    g["ets_class"] = g.apply(cls, axis=1) if len(g) else pd.Series(dtype=str)
    counts = g.ets_class.value_counts().to_dict() if len(g) else {}
    c_items = g[g.ets_class == "C"].sort_values("d_dif", ascending=False) if len(g) else g
    return {"n_items_screened": int(len(g)), "class_counts": {k: int(v) for k, v in counts.items()},
            "mean_d_dif": float(g.d_dif.mean()) if len(g) else float("nan"),
            "mean_d_dif_ci95_item_bootstrap": _item_boot_mean(g.d_dif.to_numpy()),
            "share_favouring_target": float((g.d_dif > 0).mean()) if len(g) else float("nan"),
            "c_items": [{"item_id": i, "d_dif": float(r.d_dif), "ci95": [float(r.d_lo), float(r.d_hi)], "n_strata": int(r.n_strata)}
                        for i, r in c_items.head(50).iterrows()]}


def _item_boot_mean(x: np.ndarray, n: int = 2000, seed: int = 3) -> list[float]:
    rng = np.random.default_rng(seed)
    if len(x) == 0:
        return [float("nan"), float("nan")]
    idx = rng.integers(0, len(x), size=(n, len(x)))
    return ci_from_samples(x[idx].mean(axis=1))
