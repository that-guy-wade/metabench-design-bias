# Sensitivity: minimum detectable effect, robustness, equivalence, held-out redistribution (EXPLORATORY, 2026-10-30)

Written by the sensitivity worker; saved by the coordinator because the worker could not write report files. No LLM
calls were made and no frozen file was modified. All numbers are in results.json and per-part JSON outputs; every
script is listed at the end.

## Headline

- The primary Ψ would detect a display-follower steering only about one-tenth as hard as the complying instructed
  designers steered their target.
- The observed Ψ is statistically equivalent to below 0.10 in every pool.

## Setup

| pool | sham/blinded benchmarks | designers |
|---|---|---|
| factual | 60 | 12 |
| math | 55 | 12 |
| code | 60 (11 `_rep1`) | 12 |
| pooled | 175 | 12 |

- **Ψ:** exactly as the primary computes it. Kendall τ-b over the 13 displayed keys, Fisher z clipped at τ = 0.999,
  averaged within designer then across designers, reported as tanh.
- **p:** one-sided, against uniform re-draws of each display.
- **CIs:** 95% designer-cluster bootstrap.
- **Pooled:** each designer is one cluster across pools.

## 1. Simulated partial followers (2,000 re-draws / 2,000 bootstraps)

**Starting point.** Each real benchmark is rebuilt from its items, weights and live re-scores. At k = 0 it reproduces
`produced_scores` to within 5e-6. Scores are rounded to 5 decimals, the stored precision, so the sonnet55 = placebo ties
stay exact; with that rounding, the primary's Ψ and p are reproduced exactly.

**Swap paths.** k swaps, sequential, up to 50; each replaces one item with a pool item at weight 1.
- **Greedy:** the best single swap toward τ to the display. Close to the most efficient steerer possible, so its k
  values are lower bounds.
- **Naive:** a static rule that removes the items least concordant with the display and adds the most concordant ones.
- **Random:** random swaps. One path gets full inference; 20 replicate paths give the spread.

**Ψ by number of swaps k**

| k | factual greedy / naive | math greedy / naive | code greedy / naive | pooled greedy / naive / random |
|---|---|---|---|---|
| 0 | +0.031 [−0.020, +0.086] p .14 | −0.022 [−0.082, +0.046] p .77 | −0.000 [−0.060, +0.067] p .48 | +0.004 [−0.031, +0.038] |
| 2 | +0.137 / +0.077 | +0.100 / +0.012 (p .35) | +0.146 / +0.066 | +0.129 [+0.097, +0.163] / +0.054 [+0.023, +0.087] / +0.004 |
| 5 | +0.212 / +0.154 | +0.181 / +0.062 (p .020) | +0.267 / +0.146 | +0.222 / +0.124 / +0.004 |
| 10 | +0.305 / +0.221 | +0.262 / +0.117 | +0.411 / +0.249 | +0.330 / +0.200 / −0.000 |
| 20 | +0.425 / +0.322 | +0.370 / +0.189 | +0.591 / +0.366 | +0.470 / +0.299 / +0.001 |
| 30 | +0.522 / +0.404 | +0.454 / +0.263 | +0.724 / +0.437 | +0.583 [+0.539, +0.632] / +0.374 / +0.001 |

- p = 0.0005 (the floor with 2,000 re-draws) for k ≥ 2 unless shown.
- The random control stays at baseline at every k: pooled between −0.000 and +0.007, SD ≤ 0.005 over 20 paths, every CI
  including 0.

**Thresholds (factual / math / code / pooled)**

| threshold | greedy | naive |
|---|---|---|
| smallest k with cluster CI > 0 and p < .05 | 1 / 2 / 1 / 1 | 1 / 5 / 2 / 2 |
| smallest k that also has Ψ > 0.15 (full pre-registered claim) | 3 / 4 / 3 / 3 | 5 / 14 / 6 / 7 |
| k at Ψ = 0.10 (interpolated) | 1.0 / 2.0 / 1.2 / 1.4 | 2.8 / 8.0 / 3.4 / 3.9 |
| k at Ψ = 0.15 (interpolated) | 2.5 / 3.7 / 2.1 / 2.6 | 4.8 / 13.4 / 5.2 / 6.6 |

The instrument is this sensitive because 3.5–5.5 of the 78 model pairs are within one accuracy point in a typical
benchmark, so a few swaps flip several pairs.

**Comparison with complying instructed designers (+1.44 ranks).**
- The displayed leader's rank gain over the designer's none-arm mean, pooled: greedy k = 5 gives +1.32 [+0.98, +1.67];
  naive k = 10 gives +1.39 [+0.98, +1.85].
- At those k, Ψ is 0.22 and 0.20.
- So a display-follower steering about as hard as the compliers did would produce Ψ ≈ 0.2.

**When only some designers follow** (20 random designer subsets). The smallest number of following designers m, out of
12, at which at least 80% of subsets are detected, pooled:

| path | k = 2 | k = 5 | k = 10 | k = 30 |
|---|---|---|---|---|
| greedy | 6 | 4 | 3 | 3 |
| naive | 9 | 6 | 4 | 3 |

- Math needs the most followers: 6–12.
- A single following designer is never detected at k ≤ 30.

## 2. Robustness of the primary Ψ (10,000 re-draws / 10,000 bootstraps)

| variant | factual | math | code | pooled |
|---|---|---|---|---|
| (a) frozen `primary_endpoint` | +0.0311 p .136 | −0.0222 p .767 | −0.0002 p .498 | — |
| (a) re-implementation | +0.031 [−0.022, +0.086] | −0.022 [−0.083, +0.042] | −0.000 [−0.061, +0.063] | +0.004 [−0.030, +0.039] p .39 |
| (b) without Google designers (D 9) | +0.009 [−0.046, +0.069] | −0.021 | +0.010 | −0.001 [−0.040, +0.039] |
| (c) without contamination-flagged models | +0.031 (no flags) | −0.011 [−0.084, +0.063] (10 keys) | −0.008 [−0.093, +0.084] (8 keys) | +0.006 [−0.039, +0.049] |
| (d) unresolved triples counted as wrong | +0.031 | −0.0217 | +0.0005 | +0.0048 |
| (d) unresolved triples counted as right | +0.031 | −0.0222 | −0.0020 | +0.0037 |

- **(b)** Factual's small positive Ψ comes mostly from the Google designers.
- **(d) Correction to earlier figures.** Unresolved triples are 0 in factual, 24 in math (all grok47) and 163 in code
  (grok47 101, heldout_grok420 60, grok45 2). The earlier figures of 31 and 164 were counts taken mid-precompute. Neither
  bound changes Ψ by more than 0.002.

**Equivalence test** (H0: tanh Ψ ≥ 0.10). One-sided 95% upper bounds:

| pool | t-test bound (p) | bootstrap bound (p) |
|---|---|---|
| factual | 0.064 (.002) | 0.077 (.008) |
| math | 0.012 (2e-5) | 0.031 (3e-4) |
| code | 0.043 (7e-4) | 0.053 (.001) |
| pooled (D 12) | 0.026 (3e-6) | 0.033 (1e-4) |

**Design issue.** A cell's registered sham display is identical in all three pools, because the session seed omits the
pool. An independent-per-pool pooled randomisation test therefore understates the null SD. With a shared-draw null, the
null SD is 0.024 rather than 0.017, and pooled p is 0.43 rather than 0.39. Per-pool tests are unaffected.

## 3. Held-out redistribution (OUTSIDE_CHECKS §3)

**Ranking set.** 12 designer models plus 4 held-outs (16 configurations). The placebo is excluded as a duplicate
configuration. The statistic is the held-out mean rank in the test cell minus in the none/blinded cell, per designer,
then averaged. Positive means the held-outs were pushed down.

| cell | factual | math | code | pooled |
|---|---|---|---|---|
| sham/blinded | −0.02 [−0.15, +0.10] | +0.07 [−0.08, +0.22] | +0.11 [−0.23, +0.46] | +0.06 [−0.06, +0.18] |
| leader rank gain, same cells | −0.13 | −0.13 | −0.24 | −0.17 [−0.42, +0.07] |
| instructed, COMPLIED (n 43, D 7) | −0.01 | −0.25 [−0.46, +0.01] | +0.71 [+0.18, +1.26] | +0.25 [+0.02, +0.48] |
| target gain, compliers | +1.69 | +1.41 | +2.13 | +1.78 [+0.88, +2.77] |
| instructed, REFUSED (n 53, D 7) | −0.01 | +0.07 | −0.21 | −0.03 [−0.25, +0.22] |

- In the sham arm there is no leader gain and no held-out shift.
- In the instructed arm, a real steer does go with a held-out shift pooled, but the sign is not consistent across pools.
- This statistic is too noisy to add much beyond Ψ.
- In code sham/blinded, individual held-outs move a lot in opposite directions (gemini35flash +1.28, grok420 −1.27) and
  cancel in the mean. This probably reflects the harder benchmarks; it was not tested.

## Caveats

- The simulated followers swap the same way in every session, so CIs are narrow. The "m of 12" table is the more
  realistic sensitivity.
- The followers only add and remove items; real designers can also edit and re-weight items, which would steer more per
  action.

## Scripts

`scommon.py`, `p1_simulate.py <pool>`, `p1_stats.py`, `p1_partial_designers.py`, `p2_robust.py`,
`p2_pooled_shared_null.py`, `p3_heldout.py`, `assemble.py`. Run with `PYTHONPATH=/path/to/metabench/run`
and the run venv.
