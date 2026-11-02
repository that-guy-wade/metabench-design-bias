"""Monte-Carlo power for MetaBench (extends digests/E-power-sim.py).

Units: latent score in units of the gap between adjacent-ranked evaluees (gap = 1).  Each produced benchmark adds
N(0, sigma^2) idiosyncratic noise per evaluee; designer heterogeneity multiplies the effect by (1 + het * z_d).

power_rank_gain      shown-target rank shift, designer-level one-sample t (as in E-power-sim.py), vectorised.
power_tau_primary    the actual primary endpoint: the designer moves the benchmark a fraction rho_track toward the
                     displayed (uniformly permuted) order; analysed with (a) the designer-level t on Fisher-z tau
                     (conservative, respects designer random effects) and (b) the stratified randomization test
                     (sharp null; exact under uniform shams).
attainable_power_ceiling   power with M -> infinity (M = 400) for D = 3..16, the Westfall-Kenny-Judd ceiling.

CLI: python -m metabench.power --sigma S --het H --out DIR [--sims 600]
"""
from __future__ import annotations

import argparse
import json
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy import stats

ALPHA = 0.05


def _pairs(n: int):
    return np.triu_indices(n, 1)


def _tau_from_signs(sign_s: np.ndarray, sign_r: np.ndarray) -> np.ndarray:
    """tau-b for sign arrays over the last axis (pairs); handles ties in either."""
    S = np.sum(sign_s * sign_r, axis=-1)
    n0 = sign_s.shape[-1]
    n1 = np.sum(sign_s == 0, axis=-1)
    n2 = np.sum(sign_r == 0, axis=-1)
    denom = np.sqrt((n0 - n1) * (n0 - n2))
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(denom > 0, S / denom, 0.0)


def _z(t: np.ndarray) -> np.ndarray:
    return np.arctanh(np.clip(t, -0.999, 0.999))

# ----------------------------------------------------------------------------------------------
# rank-gain power (E-power-sim.py semantics)
# ----------------------------------------------------------------------------------------------

def power_rank_gain(N: int = 12, k: float = 2.0, sigma: float = 2.0, D: int = 8, M: int = 5, het: float = 0.5,
                    sims: int = 600, seed: int = 0, alpha: float = ALPHA, max_cells: int = 6_000_000) -> float:
    """Treated benchmark: random target gets + k*(1+het*z_d); control: no boost.  Outcome: target rank (1 = best).
    Analysis: per designer mean(control rank) - mean(treated rank); one-sample t over D designers, two-sided alpha."""
    rng = np.random.default_rng(seed)
    base = np.arange(N)[::-1].astype(float)
    chunk = max(1, max_cells // (D * M * N))
    diffs = np.empty((sims, D))
    for start in range(0, sims, chunk):
        b = min(chunk, sims - start)
        eff = k * (1 + het * rng.standard_normal((b, D, 1)))             # designer heterogeneity
        t_idx = rng.integers(0, N, size=(b, D, M))                        # target per benchmark
        ranks = {}
        for treated in (1, 0):
            s = base[None, None, None, :] + sigma * rng.standard_normal((b, D, M, N))
            if treated:
                boost = np.zeros((b, D, M, N))
                np.put_along_axis(boost, t_idx[..., None], eff[..., None] * np.ones((b, D, M, 1)), axis=-1)
                s = s + boost
            st = np.take_along_axis(s, t_idx[..., None], axis=-1)[..., 0]
            ranks[treated] = (1 + np.sum(s > st[..., None], axis=-1)).mean(axis=-1)
        diffs[start:start + b] = ranks[0] - ranks[1]
    p = stats.ttest_1samp(diffs, 0.0, axis=1).pvalue
    return float(np.mean(p < alpha))

# ----------------------------------------------------------------------------------------------
# tau-based primary endpoint power
# ----------------------------------------------------------------------------------------------

@lru_cache(maxsize=8)
def _single_z_null(N: int, n_draws: int = 200000, seed: int = 12345) -> np.ndarray:
    """Fisher-z of Kendall tau between a fixed score vector and a uniform random permutation of N items."""
    rng = np.random.default_rng(seed)
    iu, ju = _pairs(N)
    s = np.arange(N, dtype=float)
    sign_s = np.sign(s[iu] - s[ju])
    out = np.empty(n_draws)
    block = 20000
    for start in range(0, n_draws, block):
        b = min(block, n_draws - start)
        perm = rng.random((b, N)).argsort(axis=-1).astype(float)
        sign_r = np.sign(perm[:, iu] - perm[:, ju])
        out[start:start + b] = _z(_tau_from_signs(sign_s, sign_r))
    return out


@lru_cache(maxsize=64)
def _psi_null_draws(N: int, D: int, M: int, n_draws: int = 20000, seed: int = 12345) -> np.ndarray:
    """Null distribution of Psi* (designer-averaged mean Fisher-z tau) when every displayed order is a uniform
    permutation independent of the produced scores: tau is then distributed as Kendall's null for N items, i.i.d.
    across benchmarks; Psi* is the mean of D*M such z's (equal M per designer).  Exact resampling for D*M <= 2000,
    normal approximation (CLT over D*M i.i.d. terms) beyond that."""
    rng = np.random.default_rng(seed + 1)
    single = _single_z_null(N)
    DM = D * M
    if DM > 2000:
        out = rng.normal(single.mean(), single.std() / np.sqrt(DM), size=n_draws)
        return np.sort(out)
    out = np.empty(n_draws)
    block = max(1, 4_000_000 // DM)
    for start in range(0, n_draws, block):
        b = min(block, n_draws - start)
        idx = rng.integers(0, len(single), size=(b, DM))
        out[start:start + b] = single[idx].mean(axis=1)
    return np.sort(out)


def simulate_tau_primary(N: int, rho_track: float, sigma: float, D: int, M: int, het: float, sims: int, rng,
                         max_cells: int = 6_000_000) -> np.ndarray:
    """Returns per-sim, per-designer mean Fisher-z tau between produced and displayed order. Shape (sims, D).
    Chunked over sims so that the pairwise sign arrays stay below ~max_cells * 66 floats."""
    base = np.arange(N)[::-1].astype(float)
    iu, ju = _pairs(N)
    chunk = max(1, max_cells // (D * M * N))
    out = np.empty((sims, D))
    for start in range(0, sims, chunk):
        b = min(chunk, sims - start)
        eff = np.clip(rho_track * (1 + het * rng.standard_normal((b, D, 1, 1))), 0.0, None)
        perm = rng.random((b, D, M, N)).argsort(axis=-1)                  # displayed order: rank position per model
        disp_score = (N - 1 - perm).astype(float)                         # displayed score ~ base of permuted model
        produced = base + sigma * rng.standard_normal((b, D, M, N)) + eff * (disp_score - base)
        sign_s = np.sign(produced[..., iu] - produced[..., ju])
        sign_r = np.sign(disp_score[..., iu] - disp_score[..., ju])
        tau = _tau_from_signs(sign_s, sign_r)
        out[start:start + b] = _z(tau).mean(axis=-1)
    return out


def power_tau_primary(N: int = 12, rho_track: float = 0.3, sigma: float = 2.0, D: int = 8, M: int = 5, het: float = 0.5,
                      sims: int = 600, seed: int = 0, alpha: float = ALPHA) -> dict:
    rng = np.random.default_rng(seed)
    zbar = simulate_tau_primary(N, rho_track, sigma, D, M, het, sims, rng)   # (sims, D)
    # (a) designer-level one-sample t, one-sided H1: Psi > 0
    t = stats.ttest_1samp(zbar, 0.0, axis=1)
    p_t = t.pvalue / 2.0
    p_t = np.where(t.statistic > 0, p_t, 1 - p_t)
    power_t = float(np.mean(p_t < alpha))
    # (b) stratified randomization test (exact null under uniform shams)
    psi = zbar.mean(axis=1)
    null = _psi_null_draws(N, D, M)
    p_rand = 1.0 - np.searchsorted(null, psi, side="left") / len(null)
    power_rand = float(np.mean(p_rand < alpha))
    return {"power_t": power_t, "power_randomization": power_rand, "mean_psi_tau": float(np.tanh(psi.mean())),
            "sd_designer_z": float(np.mean(zbar.std(axis=1, ddof=1)))}


def attainable_power_ceiling(N: int = 12, sigma: float = 2.0, het: float = 0.5, sims: int = 600, seed: int = 0,
                             D_range=range(3, 17), M_inf: int = 400, k_values=(1.0, 2.0), rho_values=(0.15, 0.3)) -> list[dict]:
    rows = []
    for D in D_range:
        row = {"D": D, "M": M_inf}
        for k in k_values:
            row[f"rank_gain_k{k:g}"] = power_rank_gain(N, k, sigma, D, M_inf, het, sims, seed)
        for rho in rho_values:
            r = power_tau_primary(N, rho, sigma, D, M_inf, het, sims, seed)
            row[f"tau_t_rho{rho:g}"] = r["power_t"]
            row[f"tau_rand_rho{rho:g}"] = r["power_randomization"]
        rows.append(row)
    return rows

# ----------------------------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------------------------

def run_grid(sigma: float, het: float, sims: int, out: Path, N: int = 12, seed: int = 0,
             D_values=(3, 4, 6, 8, 10, 12), M_values=(3, 5, 10, 15), k_values=(1.0, 2.0), rho_values=(0.15, 0.3)) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    rows = []
    for D in D_values:
        for M in M_values:
            row = {"N": N, "sigma": sigma, "het": het, "D": D, "M": M}
            for k in k_values:
                row[f"rank_gain_k{k:g}"] = power_rank_gain(N, k, sigma, D, M, het, sims, seed)
            for rho in rho_values:
                r = power_tau_primary(N, rho, sigma, D, M, het, sims, seed)
                row[f"tau_t_rho{rho:g}"] = r["power_t"]
                row[f"tau_rand_rho{rho:g}"] = r["power_randomization"]
                row[f"psi_rho{rho:g}"] = r["mean_psi_tau"]
            rows.append(row)
    ceiling = attainable_power_ceiling(N, sigma, het, sims, seed, k_values=k_values, rho_values=rho_values)
    cols = list(rows[0].keys())
    with open(out / "power_table.csv", "w") as f:
        f.write(",".join(cols) + "\n")
        for r in rows:
            f.write(",".join(f"{r[c]:.3g}" if isinstance(r[c], float) else str(r[c]) for c in cols) + "\n")
    L = [f"# Power grid (N={N} evaluees, sigma={sigma} gaps, designer-heterogeneity CV={het}, sims={sims}, alpha=0.05)", "",
         "Columns: rank_gain_k = power of the shown-target rank-gain t-test for a latent boost of k gaps (two-sided); "
         "tau_t_rho = power of the designer-level one-sided t on Fisher-z tau when designers track a fraction rho of the "
         "displayed order; tau_rand_rho = power of the stratified randomization test (sharp null); psi_rho = expected Psi (tau scale).", ""]
    L.append("| " + " | ".join(cols) + " |"); L.append("|" + "---|" * len(cols))
    for r in rows:
        L.append("| " + " | ".join(f"{r[c]:.2f}" if isinstance(r[c], float) else str(r[c]) for c in cols) + " |")
    L += ["", f"## Attainable power ceiling (M = {ceiling[0]['M']} benchmarks per designer per arm)", ""]
    ccols = list(ceiling[0].keys())
    L.append("| " + " | ".join(ccols) + " |"); L.append("|" + "---|" * len(ccols))
    for r in ceiling:
        L.append("| " + " | ".join(f"{r[c]:.2f}" if isinstance(r[c], float) else str(r[c]) for c in ccols) + " |")
    (out / "power_table.md").write_text("\n".join(L) + "\n")

    def smallest(col):
        best = None
        for r in sorted(rows, key=lambda r: (r["D"] * r["M"], r["D"])):
            if r[col] >= 0.8:
                best = {"D": r["D"], "M": r["M"], "power": r[col]}
                break
        return best
    summary = {"sigma": sigma, "het": het, "N": N, "sims": sims, "runtime_s": round(time.time() - t0, 1),
               "smallest_DM_reaching_0.8": {
                   **{f"rank_gain_k{k:g}": smallest(f"rank_gain_k{k:g}") for k in k_values},
                   **{f"tau_t_rho{r:g}": smallest(f"tau_t_rho{r:g}") for r in rho_values},
                   **{f"tau_rand_rho{r:g}": smallest(f"tau_rand_rho{r:g}") for r in rho_values}},
               "ceiling": ceiling}
    (out / "power_summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sigma", type=float, required=True, help="benchmark-to-benchmark SD of an evaluee's score, in adjacent-rank gaps")
    ap.add_argument("--het", type=float, required=True, help="designer heterogeneity CV of the effect")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sims", type=int, default=600)
    ap.add_argument("--N", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    s = run_grid(a.sigma, a.het, a.sims, Path(a.out), a.N, a.seed)
    print(json.dumps(s["smallest_DM_reaching_0.8"], indent=1), f"runtime {s['runtime_s']}s")


if __name__ == "__main__":
    main()
