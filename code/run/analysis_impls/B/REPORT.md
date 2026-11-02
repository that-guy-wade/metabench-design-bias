# Analysis implementation B: report

Author B, double-blind protocol (BLINDING.md §3). Written from PREREGISTRATION.md, prereg/frozen_sizes.json,
prereg/DEVIATIONS.md and docs/ARTEFACT_SCHEMA.md only; test data from `metabench.synthetic`. No other analysis code,
report, pilot output, session or sealed artefact was opened. No model API key was loaded.

## Delivered (analysis_impls/B/)

| file | content |
|---|---|
| `run.py` | CLI: `--results DIR --out DIR --n-perm N --n-boot N [--seed 7] [--mixed-timeout 1800] [--no-mixed]`; writes `endpoints.json`, `session_table.csv`, `timing.json` |
| `core.py` | loading (schema §1-2), τ-b / RBO / ranks, primary (randomisation test + designer-cluster and benchmark bootstraps + designer-level t), S1–S4 with Holm, exploratory (RBO, DIF screen, round trajectories, BH) |
| `measurement.py` | §8 model: crossed binomial GLMM by an own Laplace implementation (penalised sparse IRLS for the joint mode, grid + simplex search over the six variance components; random items, random benchmark intercept, maximal Target and Target×Cond slopes by designer and evaluee; statsmodels VB / posterior-mode fitters selectable but not default) and the pre-registered fallback (sparse item-fixed-effects GLM with session-cluster-robust SEs); ETS delta scale; the mixed fit runs as a bounded subprocess |
| `DECISIONS.md` | 26 decisions on ambiguous points written before any data was run, plus 12 dated amendments (A1–A12) made during implementation on synthetic data |
| `tests/` | 13 tests (one marked `slow`, run with `-m slow`) |
| `requirements.txt` | nothing installed; all dependencies already in the project venv |

`endpoints.json` sections: `inputs` (row/valid/invalid/replacement counts, invalid session list, per-cell counts),
`primary`, `secondary` (S1 with score-shift companion and named-sham supplement, S2a/S2b/S2c with score shifts, S3, S4,
`holm`), `exploratory` (RBO, round trajectories, BH, Mantel–Haenszel DIF screen), `measurement_model` (fallback GLM
always; mixed when it converges within the timeout; `reported` names which one is the pre-registered estimate).
Every estimate carries a 95% interval (designer-cluster bootstrap for rank/τ endpoints, benchmark bootstrap alongside
for the primary, cluster-robust Wald for the GLM, Laplace Wald for the mixed model, Robins–Breslow–Greenland variance for DIF items).

## Verified by tests that could fail (synthetic trees, fixed seeds 11–16)

Test suite: `MBB_TREES=<dir> .venv/bin/python -m pytest analysis_impls/B/tests` (regenerates the trees if absent;
≈10 min on this loaded box). Result of the final run: 12 passed (fast suite, 50 s on an idle box, 10 min when the box was loaded); the `slow` mixed-model test passed separately (104 s).

| test | what would make it fail | result |
|---|---|---|
| `test_tau_b_batch_matches_scipy` | vectorised τ-b differs from scipy with ties | pass |
| `test_rbo_known_values`, `test_holm_and_bh` | wrong RBO / Holm / BH arithmetic | pass |
| `test_null_primary_near_zero_and_randomisation_p_uniform` | null tree (12 designers, 60 sham/blinded): \|tanh Ψ\| ≥ 0.06, CI excludes 0, or the randomisation p over 150 exact null replicates (displayed orders re-drawn from the registered generator) is not uniform (KS p ≤ 0.01) or rejects outside 1–11% | pass |
| `test_null_secondaries_and_gamma_are_null` | any S1–S4 or the GLM γ departs from 0 or any Holm rejection on null data | pass |
| `test_injected_tracking_gives_positive_primary` | tracking 0.3 not detected (estimate ≤ 0.08, p ≥ 0.05, CI touches 0, designer t ≥ 0.05) | pass |
| `test_injected_rank_gain_recovered` | injected 2.0-gap leader gain not within 0.5 gap units, CI misses 2.0, positional gain not within 0.5 of the ceiling-adjusted expectation, S1 Holm not rejected | pass |
| `test_injected_identity_effect_recovered` | S2a / S2b not within 0.5 gap units of the injected 2.0, S2c not ≈ 0, Holm S2 not rejected, or the identity tilt leaks into the primary | pass |
| `test_injected_gamma_covered_by_fallback_glm_ci[0.0]` | GLM CI misses γ = 0.5 (no slope heterogeneity) or point error > 0.1 or CI covers 0 | pass |
| `test_injected_gamma_covered_by_fallback_glm_ci[0.15]` | with designer/evaluee slope sd 0.15 the GLM CI misses the realised pooled effect | pass |
| `test_injected_gamma_covered_by_mixed_model_ci` (slow) | Laplace GLMM CI misses γ = 0.5 or point error > 0.25 | pass |
| `test_invalid_sessions_excluded_and_counted` | invalid/replacement rows leak into estimates or are not listed | pass |
| `test_run_is_deterministic` | two runs give different `endpoints.json` bytes, or any estimate lacks an interval | pass |

Full-size runs (`--n-perm 10000 --n-boot 10000`, 468 valid sessions, 12 designers) on the fixed-seed trees:

| endpoint | null tree (seed 11) | tracking 0.3 tree (seed 12) |
|---|---|---|
| primary tanh(Ψ) [designer-cluster CI] | −0.011 [−0.069, 0.048] | 0.244 [0.178, 0.309] |
| randomisation p (one-sided) / designer-t p | 0.645 / 0.726 | 0.0001 / < 0.001 |
| claim (> 0.15, CI excl. 0, p < 0.05) | no / no / no | yes / yes / yes |
| S1 leader gain, positions [CI], perm p | −0.12 [−0.40, 0.18], 0.90 | 1.32 [0.93, 1.73], 0.0001 |
| S2a self gain true label [CI], p | −0.18 [−0.61, 0.28], 0.90 | 0.51 [0.01, 1.03], 0.006 |
| S2b told-identity gain false label [CI], p | −0.03 [−0.37, 0.29], 0.61 | −0.11 [−0.56, 0.37], 0.70 |
| S3 inverted τ − none τ [CI], p | 0.016 [−0.010, 0.043], 0.067 | 0.169 [0.129, 0.209], 0.0001 |
| S4 true τ − none τ [CI], p (two-sided) | 0.005 [−0.015, 0.026], 0.49 | 0.004 [−0.014, 0.023], 0.57 |
| Holm-adjusted p (S1, S2, S3, S4) | 1.0, 1.0, 0.27, 1.0 | 0.0004, 0.013, 0.0004, 0.57 |
| RBO p = 0.8 [CI], rand. p (chance 0.364) | 0.359 [0.323, 0.400], 0.61 | 0.457 [0.412, 0.508], 0.0005 |
| round trajectory τ (r1 → r4) | 0.003, 0.001, −0.007, −0.010 | 0.048, 0.144, 0.191, 0.235 |
| GLM γ (log-odds) [cluster-robust CI], ETS δ | −0.002 [−0.012, 0.009], −0.004 (A) | 0.121 [0.107, 0.134], 0.28 (A) |
| wall time (no mixed model) | 6.3 min | 6.1 min |

Two things these runs surfaced that matter for the real analysis:

- **S2a reacts to pure tracking.** On the tracking tree (no identity effect injected) the S2a contrast is 0.51 positions
  (Holm p 0.013). The pre-registered S2 compares sham/true with sham/blinded, but the two cells use different sham
  generators (within-tier permutation under names, uniform under pseudonyms), so a designer that merely tracks the
  display ends up ranked nearer its tier under names. S2a is therefore not a clean identity contrast under H1; S2b
  (told identity under the false label, same within-tier generator as sham/true) stays at 0 under pure tracking and is
  the cleaner identity test. This is a property of the design, reported here as found on synthetic data.
- **S3 on null data.** The registered inverted order is not exactly the reverse of `reference_scores` (one adjacent swap
  at the bottom), which biased S3 by +0.02 before A7; after A7 the null S3 is 0.016 [−0.010, 0.043], p 0.067.

Mixed model (§8) on synthetic data: the own Laplace GLMM (A11/A12) is the reported model on the
full-size trees; the fallback is always fitted alongside.

| tree | mixed γ (log-odds) [Wald CI] | ETS δ | fallback GLM γ [cluster-robust CI] | mixed fit time |
|---|---|---|---|---|
| null (seed 11) | 0.000 [−0.033, 0.033] | 0.00 (A) | −0.002 [−0.012, 0.009] | 255 s |
| rank gain 2.0 (seed 13) | 0.191 [0.151, 0.230] | 0.45 (A) | 0.275 [0.265, 0.285] | 236 s |
| γ = 0.5 injected, 4-designer tree (slow test) | CI covers 0.5, point within 0.25 | | CI covers 0.5 (slope sd 0) / the realised pooled effect (slope sd 0.15) | ≈ 100 s |

The injected 2.0-gap gain is 0.04 accuracy points at p ≈ 0.75, i.e. ≈ 0.21 log-odds by the delta method; the mixed
model's 0.19 is consistent with that, the fallback's 0.275 is higher (it has no random item effects, and its cluster-
robust CI is too narrow because the same precomputed item outcomes recur across sessions; A4). Per-arm home
advantages on the gain tree are 0.17–0.21 in every arm (the generator injects the same gain in all leader-bearing
arms). Variance components on null data collapse to ≈ 0 for every slope (singular fit, reported as such) and the item
sd is ≈ 1.5 (generator: 1.2 plus sampling); the fit is flagged `singular: true`, `converged: true`. On the real tree
(≈ 2,000 items) the dense Hessian is ≈ 2,700 × 2,700 and rows ≈ 830k, so one evaluation should take a few seconds and
the whole fit well under the 1800 s default timeout; if it exceeds it, the fallback is reported and labelled.

## Not done / limitations

- **Mixed model fitter.** Both statsmodels fitters for the §8 GLMM failed on synthetic null data (variational Bayes:
  degenerate optimum after 21 min; posterior-mode BFGS: not converged after 400 iterations), so the mixed model is an
  own Laplace implementation (A11/A12). It is tested (null, injected γ, injected gain) but is new code written in this
  session; intervals are Wald SEs conditional on the variance components, as in lme4. The fallback GLM is always
  fitted and reported next to it, and `measurement_model.reported` says which one is the pre-registered estimate.
- **Random-slope heterogeneity in the fallback.** Session-cluster-robust SEs do not carry designer- or evaluee-level
  slope heterogeneity; with injected slope sd 0.15 the GLM CI covers the realised pooled effect, not necessarily the
  population γ (test documents this). Only the mixed model addresses it.
- **Item reuse.** Produced benchmarks reuse the precomputed (item, model) outcomes, so the DIF screen and GLM SEs treat
  shared items as independent evidence across sessions only after the deduplication of A8 (DIF) and with the caveat of
  A4 (GLM).
- **Named sham arms in S1.** Their within-tier leader generator is not in the artefact schema; they are reported as a
  supplementary S1 with an empirical leader set, outside the Holm family (A1).
- **Exploratory items not implemented:** placebo separation vs replicate noise, held-out model score shifts by arm,
  rank-flip counts with pairwise item bootstrap, content shifts (category mix, item length, wh-type, Gardner z-tests),
  the §10 decompositions and §12 provenance classifier. These are outside the three exploratory items named in the
  brief (RBO, DIF screen, trajectories) and were not attempted for time.
- **Blinded arm codes (§14).** The implementation reads the plaintext arm labels of the schema; code-replacement is the
  runner's responsibility.
- **Power to detect the pre-registered Ψ ≈ 0.11** was not re-simulated here; POWER.md was not among the permitted inputs.
- **Runtime.** With `--n-perm 10000 --n-boot 10000` and `--no-mixed` a 468-session tree takes about 6 minutes on this
  loaded shared box; most of it is the Python bootstrap loops and the GLM.

## Decisions (summary; full text in DECISIONS.md)

- D1–D5: valid rows only; τ-b over the session's `displayed_keys`; rank endpoints on the fixed 13-key panel
  (DISPLAYED ∪ placebo, ranks 1 = best, average ties); `displayed_order` as the first-view order (registered order for
  sessions that never requested scores, kept as the within-arm negative control); Fisher-z with τ clipped at ±0.9999;
  designer-averaged means everywhere.
- D6–D9 (primary): sham/blinded only; randomisation test = uniform permutation of each session's displayed keys with
  scores fixed, p = (1+#{Ψ* ≥ Ψ})/(1+n); designer-cluster bootstrap (designers, then benchmarks within designer),
  benchmark-level bootstrap alongside, designer-level one-sided t; the 0.15 threshold evaluated on the tanh scale,
  with the three claim conditions reported as separate flags.
- D10–D16 (secondaries): gain = baseline rank − produced rank (positive = toward #1); S1 population = sham/blinded +
  narrative/blinded with the leader re-drawn uniformly from displayed keys; S2 within the sham arm (S2a true vs
  blinded self rank is the Holm member; S2b told identity and S2c actual self under the false label are supporting);
  S3/S4 as raw τ-b differences with within-designer label permutations; S3 one-sided, S4 two-sided; Holm over four.
- D17–D21 (measurement): anchor set with Target = 0; Cond deviation-coded over the six leader-bearing arms so γ is the
  across-arm average; random items instead of 2,000 item fixed effects in the mixed model; fallback = sparse
  item-FE GLM with session clusters; ETS delta = 2.35 × log-odds, A/B/C at 1.0/1.5.
- D22–D25 (exploratory): RBO p = 0.8 extrapolated; MH D-DIF with focal = target, strata = benchmark × ability tercile
  including the studied item; round trajectories from `scores_views.jsonl`; BH over the exploratory p-values.
- D26: fixed seeds, sorted rows, byte-identical outputs.
- Amendments A1–A12 (all on synthetic data, before any sealed data): named-sham S1 supplement; score-shift companions
  in gap units; exact binomial counts in the mixed fitter; item-reuse caveat; timings outside `endpoints.json`;
  which test feeds each Holm p; S3 comparator = registered inverted order (fixed a +0.02 null bias); DIF
  deduplication of (item, target) pairs (fixed 37 spurious "C" items on null data); mixed-model convergence gate;
  DIF screen kept as registered with the criterion-contamination caveat and ETS sign; own Laplace GLMM replacing the
  failing statsmodels fitters; grid-then-simplex variance-component search with singular fits reported, not failed.
