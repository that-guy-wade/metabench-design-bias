# Analysis implementation C: report

Author C, double-blind analysis author. Written from `PREREGRATION.md` (sections 7 and 8), `prereg/DEVIATIONS.md`,
`prereg/frozen_sizes.json`, `docs/ARTEFACT_SCHEMA.md` and BLINDING.md section 3 only. No other analysis code, pilot
result, report or session artefact was opened; `metabench/synthetic.py` was read only to drive its CLI. No model API
key was loaded. All numbers below come from synthetic trees produced by the shared generator.

## What was delivered (`analysis_impls/C/`)

- `run.py --results DIR --out DIR [--n-perm 10000] [--n-boot 10000] [--seed 20261028] [--skip-measurement]` writes
  `OUT/endpoints.json`. Input is a runner working directory in the ARTEFACT_SCHEMA layout (`sessions/<id>/benchmark.json`,
  `item_outcomes.jsonl`, `scores_views.jsonl`, `reference_item_outcomes.jsonl`, `registration_full.json`,
  `run_manifest.json`); it falls back to `results/benchmarks.jsonl` when `sessions/` is absent.
- `cimpl/load.py` (schema reader, D1-D2), `cimpl/stats.py` (ranks, tau-b incl. a vectorised version checked against
  scipy, RBO, Holm, BH, designer-cluster bootstrap), `cimpl/endpoints.py` (primary, S1-S4 with Holm, RBO, trajectories),
  `cimpl/irt.py` (measurement model: Laplace crossed mixed logistic with EM-type variance updates, the pre-registered
  fallback GLM with session-clustered sandwich SEs, the item-level DIF screen).
- `DECISIONS.md`: 30 numbered decisions on points the pre-registration leaves open, written before the first run on
  any data; two were amended on synthetic evidence before any confirmatory data (D13/D14: S1 ranks over the session's
  own displayed key set so a placebo displayed as leader is kept; D17: S4 over the 12 designer keys because
  true_named shows 12 keys and the other cells 13).
- `tests/` (15 tests, all can fail; all pass), `requirements.txt` (numpy, scipy, pytest, all already in the project venv; nothing
  was installed).

### `endpoints.json` contents

- `primary`: tanh(Psi) and Psi, per-designer table, count and mean tau of sessions that never requested scores,
  stratified randomisation test (uniform re-draw of every sham/blinded display, one-sided p, null mean/sd/q95),
  designer-cluster bootstrap 95% CI, benchmark-level bootstrap CI, designer-level one-sided t, `claim_supported` and its
  three components.
- `secondary`: S1 leader rank gain (estimate, cluster CI, leader re-draw permutation p with the recovered reputation
  tiers for named sham sessions, by-cell estimates with CIs, the companion leader score shift in accuracy points and in
  reference gaps, placebo-leader count), descriptive leader gains for inverted/instructed/true arms; S2 self-rank
  contrast true vs pseudonymous (estimate, CI, within-designer label permutation p), self-rank gain vs none for each
  identity arm incl. the false arm scored for the told and the actual model (the told-model gain has its own
  randomisation p), and the pseudonym/true gain ratio; S3 and S4 (estimates, CIs, within-designer arm-label permutation
  p, split by true arm for S4); Holm over exactly (S1, S2, S3, S4).
- `measurement_model`: mixed model (pooled gamma, delta_c deviations, gamma_c per condition, each as log-odds, odds
  ratio, ETS delta with 95% CIs and the A/B/C category; variance components; convergence), the fallback GLM with the
  same summaries, `reported_model`, and the item-level DIF screen (BH-flagged counts, per-arm mean delta with
  benchmark-bootstrap CI).
- `exploratory`: RBO p = 0.8 (estimate, cluster CI, randomisation null and p), round-by-round tau trajectory (rounds 1-4
  and final, each with a cluster CI).
- `data`: counts of sessions, valid/invalid by status, replacements, designers, cells, invalid ids. `warnings`.

Runtime on a full-size tree (468 sessions, 300-item pool): about 200 s with 10,000 permutations and bootstraps, of
which the measurement model is about 40 s (five runs in parallel on this box). Determinism: byte-identical output
across two runs (tested).

## What was verified by a test that could fail (`tests/`, 15 tests, all passing)

Run with `MBC_TREE_CACHE=/tmp/dir .venv/bin/python -m pytest analysis_impls/C/tests -q` from `run/` (the cache dir
keeps the generated trees; without it they are regenerated in pytest's tmp dir). Test trees: 4 designers, 150-item
pool (156 sessions), seeds 9001-9004; the uniformity test generates 16 further null trees.

| Claim | Test | Result on synthetic data |
|---|---|---|
| Null: randomisation p of the primary is uniform, estimate near 0, cluster CI covers 0 | `test_null_primary_p_uniform_and_estimate_near_zero` (16 trees, KS) | pass; separately on 40 null trees (seeds 301-340): KS p = 0.39, mean tanh(Psi) = 0.008 (sd 0.053), cluster CI covers 0 in 95% |
| Injected tracking gives a positive estimate with p < 0.05 and CI > 0 | `test_tracking_detected` | pass; full-size tracking 0.3 tree: tanh(Psi) = 0.230, cluster CI [0.147, 0.314], p = 0.0001 |
| Injected rank gain recovered within 0.5 positions (expected = entries within 2 reference gaps above the leader) and the leader score shift within 0.4 gaps of 2 | `test_rank_gain_recovered_within_half_position` | pass; full-size rank-gain-2 tree: S1 = 1.39 positions, CI [1.23, 1.56], expected 1.54; score shift 1.93 gaps, CI [1.82, 2.05] |
| Injected identity effect recovered in the identity contrast; told entry gains in the false arm; pseudonymous self gain near 0 | `test_identity_effect_recovered_in_identity_contrast` | pass; full-size identity-2 tree: S2 = 1.22, CI [0.76, 1.68], p = 0.0001; gains vs none: true 1.40, false-told 1.30, blinded 0.18, false-actual -0.16; ratio 0.13 |
| Known gamma (0.6 and 0.0 with designer and evaluee slope heterogeneity; 0.3 without) covered by the mixed model's CI; ETS delta CI covers 2.35 gamma | `test_known_gamma_covered_by_mixed_ci` (own Rasch simulation, 160 items, 17 evaluees, 72 benchmarks) | pass |
| Generator rank gain gives gamma CI > 0; null gives CI covering 0 | `test_generator_rank_gain_gives_positive_gamma_and_null_covers_zero` | pass; full-size: gamma = 0.276 [0.244, 0.308] (ETS delta 0.65) vs null 0.0006 [-0.029, 0.030] |
| Determinism: two runs byte-identical | `test_determinism_two_runs_identical` | pass |
| Every estimate carries a CI | `test_every_estimate_carries_a_ci` | pass (it failed once and caught missing by-cell CIs, which were then added) |
| Holm family has exactly four members with monotone adjusted p | `test_holm_family_has_four_members` | pass |
| Vectorised tau-b equals scipy's tau-b including ties; ranks; RBO bounds; Holm/BH arithmetic | `test_stats.py` (4 tests) | pass |

Null calibration of the secondary endpoints over the 40 small null trees (not a pytest test; `n_perm` 500):
S1 mean -0.003 (se 0.014), KS p 0.29, 5% below 0.05, CI covers 0 95%; S2 mean 0.004 (se 0.034), KS p 0.84, 5%, 95%;
S3 mean -0.002 (se 0.002), KS p 0.23, 0%, 97.5%; S4 mean +0.003 (se 0.002), KS p 0.18, 10%, 97.5%. The full-size
null tree gave S4 = 0.022 with permutation p = 0.004 (Holm 0.017) while two other full-size null trees gave 0.006
(p 0.19) and 0.003 (p 0.31). Pooling all 43 null trees (2,940 sessions in the three cells), mean tau-b to the reference is 0.9293 (se 0.0014) in
none/blinded against 0.9340 and 0.9337 in the two true cells, and on the 40 small trees none/blinded is the lowest of
all nine cells (0.9332 vs 0.9338-0.9376). The arm-label permutation is exact under the sharp null by construction and
the generator is documented as selecting uniformly in every arm, so this is either chance at about 2 sigma or a
property of the generator's none arm that I could not locate in the time; it is worth a look by whoever sees both
implementations, because it would bias S4 upward by roughly 0.004 if it carries over to the real runner.

Measurement-model behaviour worth knowing: the mixed model's Wald SE for gamma is 2-2.5x the fallback's
session-clustered SE on every tree (0.015 vs 0.006 on the null trees), because the evaluee-slope component carries
real variance under injected effects and the fallback's clusters cannot see it; with slope heterogeneity injected in
my own simulation the fallback's CI misses the truth while the mixed CI covers it. Variance components for a slope
that is not identified in the data stay at their start value (0.1) and inflate the SE (seen when my simulation
accidentally confounded designer with condition; not possible in the real design where every designer runs every arm).

## What was not done

- No run on real, pilot or sealed data (not permitted; the runner does that at unblinding).
- "Maximal" random slopes are implemented as independent variance components with one variance shared across the
  condition slopes per grouping factor (D21), not a full covariance matrix.
- The exploratory list is limited to what the brief asked for (RBO, item-level DIF screen, trajectories); the
  pre-registration's other exploratory items (placebo separation, held-out shifts, rank-flip counts, content shifts)
  and the controls C1-C7 are not implemented here.
- The DIF screen is the model-residual screen of D27, not a literal Mantel-Haenszel with matched examinee groups
  (there are only 17 evaluees).
- The S4 null offset above is reported, not resolved.
- OpenBLAS with 8 threads makes LAPACK's Cholesky ~70x slower on this box; `run.py` and the tests pin
  `OPENBLAS_NUM_THREADS=2` before importing numpy. Results do not depend on it.

## DECISIONS (summary; full text in DECISIONS.md)

D1 valid rows only, replacements used; D2 sessions/ first; D3 average ranks 1 = best, session's displayed keys for
agreement with the display, 12 designer keys for cross-arm rank contrasts; D4 tau-b via scipy, Fisher z with clipping
at 0.999999; D5 primary = sham/blinded; D6 displayed_order as recorded; D7 Psi designer-averaged Fisher z, reported as
tanh; D8 uniform re-draw randomisation test, p = (1 + #{Psi* >= Psi})/(1 + n); D9 designer-cluster bootstrap percentile
CI plus benchmark-level CI and designer t; D10 claim flag = all three conditions; D11 one-sided secondary p-values,
Holm over four; D12 designer-level averaging everywhere, cells resampled within designer; D13 S1 arms = sham (all
identities) + narrative, ranks over the session's key set with a matched none baseline; D14 S1 permutation generator
uniform over displayed keys, top tier for named sham (tiers recovered from registered orders); D15 S2 = own rank
sham/blinded minus sham/true, plus gains vs none per arm and the pseudonym/true ratio, told identity re-drawn from other
developers; D16 S3 in raw tau units with Fisher-z alongside, label permutation; D17 S4 on the 12 designer keys, label
permutation; D18 binomial rows plus the anchor as its own cluster; D19 Target = instructed target else displayed
leader, conditions deviation-coded so gamma is pooled; D20 item and evaluee fixed effects; D21 five independent variance
components; D22 Laplace with EM-type updates, Wald CIs; D23 fallback GLM with session-clustered sandwich always
reported; D24 ETS delta = 2.35 log-odds, A/B/C at 1.0 and 1.5; D25 no statsmodels; D26 RBO p = 0.8 extrapolated;
D27 residual-based DIF screen; D28 trajectories from the last numeric view per round; D29 95% intervals, 2,000
replicates for exploratory bootstraps; D30 fixed seeds, deterministic output.
