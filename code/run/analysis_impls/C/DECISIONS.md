# Analysis implementation C: decisions on ambiguous points

Written from `PREREGISTRATION.md` (sections 7 and 8), `prereg/DEVIATIONS.md`, `prereg/frozen_sizes.json` and
`docs/ARTEFACT_SCHEMA.md` alone, before this implementation was run on any data (synthetic test trees included).
Each entry names the ambiguity and the choice. Numbered so the report and the code can cite them (D1, D2, ...).

## Inputs and inclusion

- **D1. Rows.** A session enters an analysis only if `valid == true` in its `benchmark.json`. Both the invalid original
  and its `_rep1` replacement are in the tree; the invalid one is excluded, the replacement is used if valid
  (ARTEFACT_SCHEMA section 5). Invalid rows are counted and listed by status in `endpoints.json["data"]`.
- **D2. Source of truth.** `sessions/<id>/benchmark.json` is read first; `results/benchmarks.jsonl` is used only when the
  `sessions/` tree is absent. `item_outcomes.jsonl` per session (fallback `results/item_outcomes.jsonl`),
  `reference_item_outcomes.jsonl` (fallback `results/reference_item_outcomes.jsonl`) and `registration_full.json`
  (for `false_identity`) are read from the same root. `scores_views.jsonl` is read for the round-by-round trajectories.
- **D3. Ranking.** The produced ranking is `rankdata(-produced_scores)` over a key set, average ranks for ties, 1 = best.
  For agreement with what the designer saw (primary, S3, S4, RBO, trajectories) the key set is the session's own
  `displayed_keys` (12 named, 13 pseudonymous). For rank contrasts across arms whose displayed sets differ by the
  placebo (S1, S2) the common set of the 12 displayed designer keys is used, so a rank position means the same thing
  in both arms. The pre-registration says "on the displayed panel keys" and does not say how to compare a 12-key rank
  with a 13-key rank; this is the choice.
- **D4. Kendall tau-b** is computed between the produced scores vector and the displayed-order position vector (best
  first encoded as descending integers), `scipy.stats.kendalltau(variant="b")`. Fisher z = atanh(tau) after clipping
  tau to [-0.999999, 0.999999] so a perfectly reproduced order is finite.

## Primary (section 7)

- **D5. Arm.** Sham information arm with identity arm `blinded` only (DEVIATIONS 02:05: the pseudonymous sham arm is
  the primary). Sham sessions under `true` or `false` identity enter S1 and S2 only.
- **D6. Displayed order.** `displayed_order` from `benchmark.json`, which per the schema equals the registered sigma for
  sham sessions (including sessions that never requested scores, which the pre-registration keeps as a within-arm
  negative control; their count and their own mean tau are reported).
- **D7. Psi** = mean over designers of (mean over that designer's valid sham/blinded benchmarks of Fisher-z tau-b).
  Reported as tanh(Psi); every CI is computed on the Fisher-z scale and mapped through tanh.
- **D8. Randomisation test.** `--n-perm` re-draws (default 10,000); in each, every sham/blinded session's displayed order
  is replaced by a uniform random permutation of its displayed keys (the pre-registered generator under pseudonyms);
  Psi* is recomputed from the fixed produced scores; one-sided p = (1 + #{Psi* >= Psi}) / (1 + n_perm).
- **D9. Designer-cluster bootstrap.** `--n-boot` replicates (default 10,000): designers resampled with replacement,
  then benchmarks within each resampled designer with replacement; percentile 95% CI of Psi. A designer drawn twice
  counts as two clusters. The benchmark-level bootstrap (sessions resampled with replacement, Psi recomputed as a
  designer average over whatever designers appear) is reported alongside, as required for D < 4; also the designer-level
  one-sided t test on per-designer mean Fisher-z tau, named as the equivalent heterogeneity-respecting test.
- **D10. Claim flag.** `claim_supported` = (cluster CI lower bound on tanh scale > 0) and (randomisation p < 0.05) and
  tanh(Psi) > 0.15, exactly as the falsifiable claim states; the components are reported separately.

## Secondary endpoints (section 7, one Holm family of four)

- **D11. Direction and p-values.** All four are tested one-sided in the pre-stated direction (S1 gain > 0, S2 gain > 0,
  S3 shift upward, S4 positive), as the primary is; two-sided p-values are also written but Holm is applied to the
  one-sided ones. Holm step-down at alpha 0.05 over exactly (S1, S2, S3, S4).
- **D12. Designer averaging.** Every secondary estimate is a designer-level quantity averaged over designers (as the
  primary is), so designers with more valid sessions do not dominate. CIs are designer-cluster bootstrap percentile
  intervals with benchmarks resampled within (designer, arm cell).
- **D13. S1 arms.** The "displayed (or narrated) leader" is taken from the arms where the leader is exogenous to the
  truth: sham (all three identity arms) and narrative. Inverted (leader = reference bottom), true arms (leader =
  reference top) and instructed (positive control C1) are excluded from S1 and reported separately as descriptive
  leader gains. S1 for a session = mean rank of that leader in the same designer's valid none-arm benchmarks minus the
  leader's rank in the session (positive = moved toward first). Ranks are over the session's displayed key set: the 13
  pseudonymous keys (the placebo can be the displayed leader under pseudonyms and is kept) or the 12 named keys; the
  none-arm baseline is computed over the same key set as the session it serves (none-arm sessions are pseudonymous and
  score all 17 keys, so both sets are available). Sessions whose designer has no valid none-arm benchmark are dropped
  from S1 with a count. Amended before any run on confirmatory data: the first draft ranked over the 12 designer keys
  and would have dropped placebo-leader sessions, found on synthetic data.
- **D14. S1 permutation generator.** For sham/blinded and narrative/blinded sessions the leader is re-drawn uniformly
  from the session's displayed keys (13, including the placebo, matching the uniform permutation under pseudonyms). For named sham sessions (identity `true`/`false`) the registered generator is a
  within-reputation-tier permutation, so the leader is re-drawn uniformly from the top tier. The tier partition is not
  in the artefact schema; it is recovered from the registered displayed orders of all named sham sessions in the tree
  (keys grouped by the set of positions they occupy; the groups must form contiguous position blocks covering 1..12).
  If recovery fails the fallback is uniform over the 12 keys and a warning is written to `endpoints.json`.
- **D15. S2 definition.** The Holm-family member is the true-vs-pseudonymous self-rank contrast within the sham
  information arm: S2 = mean rank of the designer's own entry in its sham/blinded benchmarks minus its mean rank in its
  sham/true benchmarks (positive = own entry higher under the true label). Its permutation test shuffles the identity
  label (`blinded` vs `true`) among each designer's sham sessions. Also reported with CIs: self-rank gain vs the none arm
  for each identity arm (blinded, true, false scored for the told model, false scored for the actual self), and the
  ratio (gain under pseudonyms) / (gain under true label) that the falsifiable claim's "at least halved" refers to.
  The told-model gain in the false arm has a randomisation p from re-drawing the told identity uniformly among
  displayed designer keys from a developer other than the designer's own (developer read from the `designer_model_id`
  prefix: claude / gpt or o-series / gemini / grok), which is the registered generator as far as the pre-registration
  states it.
- **D16. S3.** Designer-level mean tau-b(produced, `displayed_order`) over inverted/blinded benchmarks minus the mean
  tau-b(produced, reverse of the reference ranking on the session's displayed keys) over none/blinded benchmarks,
  averaged across designers. The pre-registration writes the difference in raw tau-b units; that is the estimate, and
  the Fisher-z version is written alongside. Permutation p: within designer, shuffle the arm label (inverted vs none)
  across those sessions, both scored against the reverse-reference order.
- **D17. S4.** Designer-level mean tau-b(produced, reference ranking) over true_named/true and true_blinded/blinded
  benchmarks together minus over none/blinded benchmarks; also split by the two true arms. Because true_named displays
  12 keys and the other two cells 13 (the placebo, whose reference score ties its twin), the reference ranking and the
  produced ranking are taken over the 12 designer keys for every S4 session (the D3 rule for cross-arm contrasts).
  Permutation p as in D16 with the arm label (true vs none).

## Measurement model (section 8)

- **D18. Data.** One row per (benchmark b, item i, evaluee m) with `n_correct` of `n_samples`, binomial likelihood;
  plus the anchor set (`session_id == "REFERENCE"`, every pool item, every panel key) as its own cluster with
  Target = 0 and no benchmark effect. Items with `n_samples == 0` are dropped with a count.
- **D19. Target and conditions.** Target_{b,m} = 1 when m is `target_model` (instructed) or otherwise `displayed_leader`
  of benchmark b. Conditions c are the information arms that have a Target (sham, inverted, narrative, instructed,
  true_named, true_blinded). Condition indicators are sum-to-zero (deviation) coded over those arms, so gamma is the
  pooled home advantage (unweighted mean over conditions) and delta_c are deviations from it; per-condition
  gamma_c = gamma + delta_c are also written with CIs. None-arm benchmarks have no Target and inform theta, beta and u_b.
- **D20. Fixed effects.** theta_m: evaluee fixed effects (one dropped against the intercept); beta_i: item fixed effects
  (the pre-registered fallback also keeps item fixed effects, so the mixed model keeps them too and the two differ
  only in the random part). 
- **D21. Random effects.** u_b (benchmark intercept); Target slope by designer; Target x Cond slopes by designer;
  Target slope by evaluee; Target x Cond slopes by evaluee. "Maximal" is implemented as independent variance
  components with one variance shared across the condition slopes of a grouping factor (5 variance components, no
  slope correlations), because correlated slopes for 6 conditions over 12 designers are not estimable at this size.
- **D22. Estimation.** Own implementation: Laplace approximation to the marginal likelihood, inner Newton over
  (fixed effects, random effects) with sparse design matrices, variance components updated by the EM-type fixed point
  sigma_c^2 = (sum_j b_j^2 + sum_j Var(b_j | y)) / q_c until relative change < 1e-4 or 60 iterations. SE(gamma) from the
  inverse of the joint Hessian at the mode (the lme4-style conditional covariance). CIs are Wald 95%.
  Convergence status and iteration count are written; if the fixed point does not converge the pre-registered
  fallback (D23) is flagged as the reported model.
- **D23. Fallback.** Pooled binomial GLM with the same fixed effects and no random effects, cluster-robust sandwich SEs
  with clusters = session (the anchor set is one cluster). Always fitted and written alongside the mixed model.
- **D24. Scale conversion.** ETS delta = 2.35 x log-odds; category A if |delta| < 1.0, B if 1.0 <= |delta| < 1.5, C if
  |delta| >= 1.5 (A/B/C from the point estimate only). Odds ratios exp(gamma) with exp of the CI bounds.
- **D25. Statsmodels is not used** for the mixed model because its Bayesian mixed GLM is variational and binary-only;
  the pre-registration names it as software for the Builder's implementation, not as a requirement on this one.

## Exploratory (BH q = 0.05 over the exploratory p-values that exist)

- **D26. RBO.** Rank-biased overlap at p = 0.8 (Webber et al. 2010, extrapolated form with full-depth lists) between the
  produced ranking (ties broken by key name after score) and the displayed order, sham/blinded sessions; designer
  average with cluster-bootstrap CI; the randomisation null mean and one-sided p are written using the same
  permutations as D8.
- **D27. Item-level DIF screen.** Standardised residual of the Target evaluee against the no-DIF Rasch fit
  (anchor-based item and evaluee effects, from the fallback fit with gamma and deltas set to 0) per (benchmark, item)
  where the row is a Target row; per information arm the mean residual in ETS delta units with a benchmark-level
  bootstrap CI, and the number of items flagged after BH q = 0.05 across all Target rows. Descriptive only.
- **D28. Trajectories.** For sham/blinded sessions, tau-b between the draft's true scores (`"true"` field of each
  numeric view in `scores_views.jsonl`, over displayed keys) and `displayed_order`, taking the last numeric view of
  each round; designer-averaged mean per round with cluster-bootstrap CI, plus the final produced tau as round "final".
- **D29. Every CI is a 95% interval.** Bootstrap percentile intervals use the same `--n-boot`; the exploratory and
  descriptive numbers use 2,000 bootstrap replicates when `--n-boot` is larger, to bound runtime, and say so in the JSON.

## Determinism

- **D30.** Every random draw comes from `numpy.random.default_rng(seed)` with fixed seeds derived from a base seed
  (default 20261025 + 3) and the endpoint name; `run.py` has `--seed`. Two runs with the same inputs and flags produce
  byte-identical `endpoints.json`.
