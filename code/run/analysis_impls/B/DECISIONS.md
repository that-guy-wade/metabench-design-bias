# Analysis implementation B: decisions on ambiguous points of PREREGISTRATION.md

Written before this implementation was run on any artefact tree (synthetic or real). Each entry names the
pre-registration text, the ambiguity, and the choice made. Later amendments are dated and appended at the end.
Inputs are read only from the ARTEFACT_SCHEMA layout; no other analysis code was consulted.

## Input and population

- D1. **Rows used.** `results/benchmarks.jsonl` if present, else every `sessions/*/benchmark.json`. Only rows with
  `valid == true` enter any estimate (§6.2, schema §5). Invalid rows and replacements are counted and listed.
- D2. **Displayed panel.** Rankings "of the displayed panel" (§7) are computed over the session's own
  `displayed_keys` (13 pseudonymous, 12 named) from `produced_scores`. Rank-position endpoints (S1, S2) need one
  panel that is identical across identity arms, so ranks there are taken among the fixed set
  DISPLAYED_KEYS ∪ PLACEBO (13 keys, derived from the data as the union of all `displayed_keys`), which every
  session scores (`panel_keys` has all 17). Ranks are 1 = best, ties get average rank.
- D3. **Displayed order.** `displayed_order` is used as the order "displayed at the first request_panel_scores call".
  For sham/inverted sessions the schema guarantees it equals the registered order; sessions that never requested
  scores keep the registered order (§7 negative control) so they are not dropped. The run checks
  `displayed_order == intended_displayed_order` for sham/inverted and reports mismatches.
- D4. **τ-b.** scipy `kendalltau(variant="b")` between produced scores (over the display's keys) and the displayed
  rank (best first = highest). Fisher-z is atanh(τ) with τ clipped to ±0.9999 so a perfect agreement is finite.
- D5. **Designer averaging.** "Designer-averaged mean" = mean over designers of the per-designer mean. Applied to
  every endpoint and to every bootstrap / permutation replicate.

## Primary

- D6. **Population.** `info_arm == "sham"` and `identity_arm == "blinded"` (pseudonymous arm; DEVIATIONS 02:05).
- D7. **Randomisation test.** 10,000 re-draws (or `--n-perm`) of each session's displayed order as a uniform
  permutation of that session's `displayed_keys`, the pre-registered generator under pseudonyms (§4, §7); the
  placebo is included because it is a displayed label under pseudonyms. Produced scores are held fixed, Ψ* uses
  D5, p = (1 + #{Ψ* ≥ Ψ}) / (1 + n_perm), one-sided. The real generator's seed stream is irrelevant: only its
  distribution (uniform) is pre-registered.
- D8. **Bootstrap CIs.** Designer-cluster: resample designers with replacement, then benchmarks within each
  resampled designer with replacement; percentile 95% CI of Ψ on the Fisher-z scale, endpoints tanh-transformed.
  Benchmark-level: resample benchmarks i.i.d. and recompute the designer-averaged statistic on the resample.
  Both reported. The designer-level one-sided t on per-designer mean Fisher-z τ is reported as the equivalent
  heterogeneity-respecting criterion.
- D9. **Claim threshold.** "Ψ exceeds 0.15" is evaluated on the reported tanh scale; both tanh(Ψ) and Ψ are given
  and the three claim conditions (estimate > 0.15, cluster CI excludes 0, p < 0.05) are reported as separate flags.

## Secondary endpoints (Holm family of four)

- D10. **Sign of rank gain.** Gain = (mean none-arm produced rank of the model, same designer) − (produced rank
  in the session), so a positive number means the model moved toward rank 1 by that many positions.
- D11. **S1 population.** Sessions whose leader is randomised by the registered generator and whose identity
  arm is pseudonymous: `sham/blinded` and `narrative/blinded`. The named sham arms (`sham/true`, `sham/false`)
  use a within-reputation-tier permutation whose tiers are not part of the artefact schema; they are reported as
  a supplementary S1 estimate (CI only, no permutation p). Inverted and true arms have deterministic leaders and
  are excluded from S1. Sessions whose designer has no valid none-arm benchmark are dropped with a count.
- D12. **S1 test.** Permutation over the identity of the leader: for each session the leader is re-drawn
  uniformly from that session's `displayed_keys`, the gain recomputed against the same designer's none-arm
  baseline for the re-drawn model, Ψ-style designer average, one-sided p (gain ≥ observed).
- D13. **S2 population and contrasts.** The sham information arm is the only arm with all three identity levels,
  so S2 is computed within sham. Three quantities, all in positions (D10 sign convention, baseline = sham/blinded):
  S2a self gain under the true label (rank of designer in sham/blinded − in sham/true); S2b told-identity gain
  under the false label (rank of the told model in sham/blinded − rank of that model in the sham/false session
  that was told it); S2c actual-self gain under the false label. The Holm-family p for S2 is S2a (H2's main
  clause). S2b and S2c carry CIs and unadjusted p and are reported as supporting. The told model is read from
  `config.json` (`false_identity`), falling back to the session's `label_map` (the key whose label is the
  designer's real name but that is not the designer).
- D14. **Tests for S2, S3, S4.** Within-designer label-permutation tests (the arm labels of a designer's valid
  sessions in the two contrasted cells are shuffled; the multiset of told identities travels with the "false"
  label in S2b), 10,000 draws, with the designer-averaged difference as the statistic. S1, S2, S3 one-sided in
  the pre-stated direction (gain > 0, inverted τ shifted upward); S4 two-sided (no direction is pre-stated; it is
  "confounded with quality by design"). All four get designer-cluster bootstrap CIs (D8).
- D15. **S3 and S4 scale.** Differences of raw τ-b (the text says "τ-b(...) minus ..."), not Fisher-z. S3: inverted
  sessions τ-b(produced, displayed_order) minus none sessions τ-b(produced, reference order reversed), both over
  the session's displayed_keys. S4: τ-b(produced, reference order) in `true_named` and `true_blinded` pooled, minus
  the none arm; per-arm values are also reported.
- D16. **Holm.** Step-down Holm at α = 0.05 over {S1, S2a, S3, S4}; adjusted p-values reported.

## Measurement model (§8)

- D17. **Data.** Every valid produced benchmark's `item_outcomes` rows (binomial n_correct / n_samples) plus the
  anchor set `reference_item_outcomes.jsonl` (session REFERENCE, Target = 0, no condition). Target_{b,m} = 1 when
  m is the benchmark's `displayed_leader` (instructed arm: `target_model`); none-arm rows have Target = 0.
- D18. **Condition coding.** Cond covers the six leader-bearing arms (sham, inverted, narrative, true_named,
  true_blinded, instructed) with sum-to-zero (deviation) coding, so γ is the pooled home advantage averaged over
  arms and δ_c are arm deviations (the sixth is minus the sum). Per-arm home advantages γ + δ_c are reported with
  CIs as linear combinations.
- D19. **Mixed model.** statsmodels `BinomialBayesMixedGLM` (variational Bayes) with fixed θ_m (17 evaluee
  effects, no intercept), fixed γ and δ_c, and variance components: item (β_i as random item effects, the
  explanatory-IRT formulation, because ~2,000 dense item columns are infeasible in that fitter), benchmark
  intercept u_b, Target slope by designer and by evaluee, Target×Cond slopes by designer and by evaluee (Barr
  2013 maximal). Rows are expanded to Bernoulli trials because the fitter takes binary outcomes. Posterior mean ±
  1.96 posterior sd is the 95% interval. If the fit raises, fails to converge, or exceeds `--mixed-timeout`
  seconds, the fallback is used and labelled.
- D20. **Fallback.** Pooled binomial logistic GLM with item fixed effects (sparse IRLS, one item constrained to 0),
  θ_m, γ, δ_c, and session-cluster-robust sandwich SEs (the anchor set is its own cluster). Always fitted and
  reported; marked as the pre-registered fallback when the mixed model is unavailable.
- D21. **Scales.** Each of γ, δ_c, γ+δ_c reported as log-odds, odds ratio, ETS delta = 2.35 × log-odds with the
  A/B/C class (|delta| < 1.0 A, 1.0–1.5 B, ≥ 1.5 C), each with 95% CI.

## Exploratory

- D22. **RBO.** Rank-biased overlap at p = 0.8 (Webber et al. 2010, extrapolated form) between the produced
  ranking and the displayed order over displayed_keys, sham/blinded, designer-averaged, cluster-bootstrap CI,
  and a randomisation p from the same uniform re-draws as D7 (chance level ≈ RBO of a random permutation).
- D23. **DIF screen.** Per item in produced benchmarks: Mantel–Haenszel common odds ratio of correctness, focal =
  the benchmark's Target model, reference = the other panel models, strata = benchmark × ability tercile where
  ability is the model's total score on that benchmark including the studied item (Holland & Thayer). D-DIF =
  −2.35 ln α_MH with the Robins–Breslow–Greenland variance; A/B/C counts and the list of C items. Descriptive.
- D24. **Trajectories.** From `scores_views.jsonl` in sham/blinded sessions: for each numeric view, τ-b between the
  draft's true scores (`true_all` restricted to displayed_keys) and the displayed order, grouped by round;
  designer-averaged mean per round with cluster-bootstrap CI; the submitted benchmark's τ as the final point.
- D25. **BH.** Benjamini–Hochberg q = 0.05 is applied to the exploratory p-values that exist (RBO, round
  trajectories); the DIF screen is descriptive and gets no p.

## Reproducibility

- D26. Every random draw comes from `numpy.random.default_rng(seed)` with seeds fixed in `run.py` (`--seed`,
  default 20261025 is refused to avoid confusion with the run's master seed; default 7). Rows are sorted by
  session id before any computation. Two runs on the same inputs must produce byte-identical `endpoints.json`.

## Amendments made during implementation (before any run on sealed data; synthetic data only)

- A1 (2026-10-25, amends D11). The named sham arms are reported as a supplementary S1 with a permutation p whose leader
  generator is "uniform over the set of leaders observed in the named sham sessions" (an empirical proxy for the
  tier-1 set, since the within-tier generator produces only tier-1 leaders and the tier table is not in the schema).
  It is labelled as such and is not in the Holm family.
- A2 (2026-10-25). Score shifts are reported alongside rank flips (§7, "both score shifts and rank flips"): S1 and S2
  carry a `score_shift` companion, the model's produced score relative to the 13-key panel mean, in accuracy points
  and in units of the reference median adjacent gap (the pre-registration's "rank gap"). The generator's injected
  sizes are defined on that scale, so the recovery tests check the gap-unit estimate within 0.5 and the positional
  estimate against a ceiling-adjusted expectation (a leader already at rank 1 cannot gain).
- A3 (2026-10-25, amends D19). The mixed model keeps the binomial trial counts exactly instead of expanding rows: the
  fitter is subclassed so each row contributes y·η + n·E[−log(1+e^η)] to the ELBO (the base class assumes n = 1).
  Variational mean-field intervals (posterior sd) are reported; they ignore posterior covariance between fixed
  effects, so the per-arm (γ+δ_c) intervals from the mixed model are approximate. The fallback GLM's intervals use the
  full cluster-robust covariance.
- A4 (2026-10-25). Item-level dependence: every benchmark that contains item i reuses the same precomputed outcomes
  for (i, m). Session-cluster-robust SEs therefore understate uncertainty for parameters driven by item reuse. γ is
  identified from the Target rows (one model per benchmark), which is less affected, but the DIF screen and the GLM
  SEs are reported with this caveat.
- A5 (2026-10-25). Timing fields are written to `timing.json`, not `endpoints.json`, so two runs on identical inputs
  produce byte-identical endpoint files (D26 test).
- A6 (2026-10-25). The S3 and S4 Holm-family p-values use the within-designer label permutation (D14); the S1 p uses
  the leader re-draw (D12); the S2 p uses the S2a label permutation (D13). Exploratory `designer_t_p_one_sided` on
  round trajectories is a designer-level one-sided t test on per-designer mean τ, feeding the BH list with the RBO p.
- A7 (2026-10-25, amends D15). On synthetic null data the registered inverted order differed from "reverse of
  `reference_scores`" by one adjacent swap at the bottom in every inverted session, which biased S3 upward by ≈ 0.02
  (p ≈ 0.05 on null data). The none-arm comparator for S3 is now the registered inverted order itself (the modal
  `intended_displayed_order` of the valid inverted sessions), falling back to the reversed reference order only when
  no inverted session exists or the key sets differ. Decided on synthetic data before any sealed data was seen.
- A8 (2026-10-25, amends D23). The DIF screen counted an (item, target model) pair once per session although its
  outcomes are the same precomputed draws in every session; on null data this produced 37 "C" items of 295. Each
  (item, target) pair now enters once (first session), so the screen is calibrated against the actual information.
- A9 (2026-10-25, amends D19). Mixed-model fitting algorithm and convergence rule. On the synthetic null tree the
  mean-field variational fit (statsmodels `fit_vb`) ran 21 minutes on a 4-designer tree and returned a degenerate
  optimum (γ = −0.51 with per-arm home advantages from −6 to +8 log-odds and slope sds of 2.6 to 5.1 on data generated
  with γ = 0), so it is not usable as the pre-registered estimate. The default fitter is now the posterior mode with
  Laplace covariance (`fit_map`, the lme4-style Laplace approximation, with the binomial log-likelihood written for
  trial counts); VB remains available via `--mixed-method vb`. A mixed fit counts as converged only if the optimizer
  reports success AND the fit passes a sanity gate fixed here: every variance-component sd ≤ 3 log-odds and every
  fixed effect |estimate| ≤ 10 log-odds with a finite covariance. Otherwise the pre-registered fallback GLM is the
  reported model and the mixed output is kept in `endpoints.json` under `measurement_model.mixed` with
  `degenerate: true`. Decided on synthetic data before any sealed data was seen.
- A10 (2026-10-25, amends D23). On the synthetic tracking tree the total-score-matched MH screen pointed against the
  target (mean D-DIF −0.26 although the target scored +2.6 points above its reference on the selected items): the
  textbook criterion-contamination effect when a whole benchmark is tilted toward one examinee. An anchor-matched
  variant (reference-score terciles) was tried and is identically 1 by construction once every model has been a target
  on an item, because the (item, model) outcomes are fixed precomputed draws and the selection signal lives in which
  items were chosen, not in their outcomes. The screen therefore stays exactly as registered (total-score matching,
  descriptive, deduplicated per A8), its sign is the ETS orientation (delta_MH = 2.35 ln alpha_focal, positive favours
  the target) and `endpoints.json` carries this caveat; gamma in the measurement model is the informative DIF quantity.
- A11 (2026-10-25, amends A9/D19). The statsmodels posterior-mode fit (`fit_map`, BFGS) also failed to converge on the
  4-designer null tree (400 iterations, γ = −0.75 with a CI 6 log-odds wide, 305 s). The mixed model is therefore
  fitted by an own implementation of the standard Laplace approximation (lme4 glmer, nAGQ = 1): penalised sparse IRLS
  for the joint mode of fixed and random effects given the variance components, Nelder–Mead over the six log-sd
  parameters on the Laplace marginal log-likelihood, Wald SEs from the inverse penalised Hessian at the optimum.
  The statsmodels fitters stay selectable (`--mixed-method map|vb`) but are not the default. The convergence gate of
  A9 applies unchanged.
- A12 (2026-10-25, amends A11). Variance-component search: two deterministic coordinate sweeps over a log-sd grid
  (−4 … 1) followed by a Nelder–Mead polish with a small simplex (`--mixed-maxiter` evaluations), because a plain
  simplex from a common start wandered to inflated slope sds on null data. A variance component at the lower grid
  boundary (sd ≈ e^−4) is a singular fit (reported with `singular: true`), not a convergence failure; the A9 gate
  (sd ≤ 3, |fixed effect| ≤ 10, finite covariance) decides convergence.
