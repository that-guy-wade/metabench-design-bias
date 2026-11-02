# Power analysis and frozen sizes

Written 2026-10-25 after the T1 pilot's blind phase (Phase A: 3 designers × 4 none-arm benchmarks) and before any confirmatory session. Pilot data are excluded from the confirmatory analysis. Simulation code: `metabench/power.py` (extends `digests/E-power-sim.py`); outputs: `power/pilot/` (pilot estimates), `power/pilot_het05/` (sensitivity), `power/smoke/` (pre-pilot smoke at σ = 2). Frozen sizes: `prereg/frozen_sizes.json` (SHA-256 recorded inside).

## 1. Pilot estimates (Phase A, 12 blind benchmarks, pilot domain)

| Quantity | Estimate | How |
|---|---|---|
| Reference adjacent-rank gap (displayed panel, 11 entries) | 0.0209 accuracy points | median gap between adjacent models on the full 1,300-item pool |
| Benchmark-to-benchmark SD of a model's score, within designer | 0.0174 points = **0.83 gaps** | pooled SD over (designer, model) cells with 4 replicates |
| Within-designer rank SD of a model | 0.46 positions | |
| Consistency ceiling (test-retest τ-b between replicates) | **0.925** (min 0.81, max 0.99; 18 pairs) | Fisher-z mean |
| τ-b of blind benchmarks to the reference ranking | 0.905 (12 benchmarks, 0.84 to 0.95) | |
| Designer heterogeneity proxy (CV of designers' mean absolute deviation from reference) | **0.71** | Sonnet 0.014, Opus 0.087, GPT-5.5 0.109 points |
| Authorship self-rank gain in the blind arm (positions, + = up) | Sonnet +0.5 (n=4), Opus −1.4 (ties at ceiling), GPT-5.5 +0.4 | reference rank − produced rank |

The digest's prior guesses were σ = 1 to 4 gaps and CV 0.5; the pilot's σ is lower (0.83) and heterogeneity higher (0.71). The heterogeneity proxy is a null-arm proxy (designers differ in how much they move every model), not the CV of a steering effect; it is used because the sham arm had not run when sizes were frozen, and it is the conservative choice relative to 0.5.

## 2. Simulation

As in `E-power-sim.py`: N = 12 evaluees spaced one gap apart; each benchmark adds N(0, σ²) noise per evaluee; the designer effect is multiplied by (1 + het·z_d) per designer. Two endpoints:

- **rank gain** (secondary S1 form): the shown target gets a latent boost of k gaps; designer-level one-sample t on the per-designer mean rank difference (treated − control), two-sided α = 0.05.
- **τ primary**: the designer moves the benchmark a fraction ρ toward a uniformly permuted displayed order; expected Ψ ≈ 0.11 at ρ = 0.15 and ≈ 0.30 at ρ = 0.3. Tested two ways: the designer-level one-sided t on Fisher-z τ (respects designer random effects; this is the heterogeneity-respecting criterion) and the stratified randomisation test (sharp null, power → 1 as M → ∞ at any D).

600 simulations per cell; grids over D ∈ {3,4,6,8,10,12}, M ∈ {3,5,10,15}.

## 3. Results at the pilot estimates (σ = 0.83, het = 0.71)

Smallest (D, M) reaching 0.8 power:

| Endpoint | D, M | power |
|---|---|---|
| rank gain, k = 1 gap | 12, 5 | 0.87 |
| rank gain, k = 2 gaps | 10, 3 | 0.89 |
| τ primary, ρ = 0.15 (Ψ ≈ 0.11), designer-level t | 12, 5 | 0.84 |
| τ primary, ρ = 0.3 (Ψ ≈ 0.30), designer-level t | 8, 3 | 0.92 |
| τ primary, ρ = 0.15, randomisation test | 12, 3 | 0.83 |
| τ primary, ρ = 0.3, randomisation test | 3, 3 | 0.85 |

Selected cells (designer-level t unless stated):

| D | M | rank k=1 | rank k=2 | τ ρ=0.15 | τ ρ=0.3 | rand ρ=0.15 |
|---|---|---|---|---|---|---|
| 8 | 5 | 0.62 | 0.84 | 0.66 | 0.94 | 0.83 |
| 8 | 10 | 0.77 | 0.90 | 0.79 | 0.95 | 0.95 |
| 8 | 15 | 0.82 | 0.90 | 0.85 | 0.96 | 0.99 |
| 10 | 10 | 0.89 | 0.96 | 0.91 | 0.99 | 0.98 |
| 12 | 5 | 0.87 | 0.97 | 0.84 | 0.99 | 0.92 |

Sensitivity at het = 0.5 (`power/pilot_het05/`): rank k=1 reaches 0.8 at (10, 5); τ ρ=0.15 at (12, 5) with 0.85; ceilings are higher (D = 6 already 0.95 to 0.98).

## 4. Attainable power under the crossed-design ceiling (M = 400, het = 0.71)

| D | rank k=1 | rank k=2 | τ ρ=0.15 | τ ρ=0.3 |
|---|---|---|---|---|
| 3 | 0.24 | 0.24 | 0.34 | 0.29 |
| 4 | 0.47 | 0.46 | 0.64 | 0.59 |
| 5 | 0.62 | 0.63 | 0.84 | 0.78 |
| 6 | 0.76 | 0.77 | 0.94 | 0.91 |
| 8 | 0.92 | 0.93 | 0.99 | 0.98 |
| 10 | 0.97 | 0.97 | 1.00 | 1.00 |
| 12 | 0.99 | 0.99 | 1.00 | 1.00 |

Adding benchmarks cannot rescue a study with fewer than 6 designers; the pilot's three designers cap the designer-level test at 0.24 to 0.34 no matter how many benchmarks are run (Westfall, Kenny & Judd 2014). The randomisation test reaches 0.99 at D = 3 but answers a different question (does any designer track the display), so the pilot can only *detect* tracking, not estimate its designer-population mean with power.

## 5. Frozen sizes (`prereg/frozen_sizes.json`)

- **D = 12 designers** from ≥ 4 developers, **M = 5 benchmarks per designer per primary arm**, N = 14 panel entries (every designer, siblings, descendants, matched-strength models, 1 placebo, 2 held-out), K = 4 rounds, 5 samples per item, 100 items (T1).
- Power at the frozen size: 0.84 for Ψ ≈ 0.11 (ρ = 0.15), 0.99 for Ψ ≈ 0.30, 0.87 for a 1-gap leader shift, 0.97 for 2 gaps; randomisation test 0.92 at ρ = 0.15.
- Fallback if only 10 designers can be sourced: D = 10, M = 10 (0.91 / 0.99 / 0.89 / 0.96). Minimum acceptable: D = 8, M = 15 (0.85 / 0.96 / 0.82 / 0.90). Below D = 8 the study is not run.
- Sessions per designer (confirmatory T1): sham-blinded 5, none 5, true-named 5, true-blinded 5, sham-true 5, sham-false 5, inverted 3, narrative 3, instructed 3 = 39; × 12 designers = 468 sessions. No optional stopping.
- Cost at pilot rates (T1): Sonnet-class $0.12, Opus-class $2.2, GPT-5.5-class $4 per session (cached-input accounting); 468 sessions ≈ $500 to $1,000 plus one panel precompute per domain (≈ $125 per 1,300-item pool at 3 samples; ≈ $300 at 5 samples and 2,000 items).

## 6. Caveats

- σ and het come from one pilot domain and three designers; the main-study domains (math, code, factual QA) have different ceilings. Re-estimate from the first 12 confirmatory none-arm sessions and report the comparison without changing sizes.
- The τ-primary simulation assumes a uniform permutation of all displayed entries; named arms permute within tiers, which lowers the expected Ψ for a given ρ.
- Ties at ceiling (several models at 0.99 on an Opus-built benchmark) inflate rank noise beyond the simulated Gaussian model; the pre-registered analysis uses τ-b and average ranks for ties.
