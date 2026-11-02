# Reconciling implementations A, B and C on the disputed secondary endpoints (EXPLORATORY)

(Written by the reconcile worker; saved by the coordinator because the worker could not write report files.)

Post-unblinding and exploratory: no LLM calls and no frozen files modified. Inputs are the valid benchmark rows, item
outcomes, reference outcomes and each session's `actions.jsonl` and `scores_views.jsonl`.

The designer is the unit (12 per pool). Unless stated otherwise:
- **CIs** are 95% designer-cluster bootstraps: designers resampled, then benchmarks within each cell; 4,000 replicates,
  2,000 for pooled rows.
- **p values** are within-designer label permutations (4,000), one-sided in the pre-stated direction (S4 two-sided),
  unadjusted.
- **Pooled** means the average of the three pool estimates, with designers resampled jointly across pools.

**Key-set labels.** "A-mixed" = A's `panel_keys()` (13 entries when `displayed_order` exists, else 12). "12" = the 12
designer models. "13" = 12 plus the placebo. "session" = each session's own `displayed_keys` (B's choice).

## Summary

- **The key-set bug.** A ranks a benchmark over its `displayed_order` when that field exists (13 entries under
  pseudonyms) and over 12 entries otherwise. The field exists in the sham, inverted, instructed and both true arms, but
  not in none or narrative. Sonnet55 and its placebo copy tie in the reference ranking but come out in near-random order,
  so the extra entry pushes some designers down one place and lowers |τ| by about 0.03.
  - **Math S2** goes from +0.40 to −0.04 with a fixed key set. Pooling over information arms is not the cause: with A's
    key sets, sham-only rows give +0.69.
  - **Math S3** goes from +0.17 (Fisher z; +0.037 raw τ) to +0.006–0.015 raw τ. No benchmark has |τ| = 1, so the
    confirmatory doc's "atanh amplifies near-perfect benchmarks" explanation is wrong.
  - **Code S4** is real. C's fixed 12-key estimate is +0.042 [+0.004, +0.088]. A misses it because of the mixed key sets;
    B's +0.059 is inflated by the mirror-image mismatch. Pooled over the three pools it is +0.010 [−0.009, +0.029].
  - The same bug biases A's S1 downward (math sham/blinded −0.76 vs −0.07 with consistent keys) and A's C1 gain (math
    +0.10 vs +0.57).
- **Pre-registration text** supports B/C's raw-τ S3, B/C's sham-only S2 ("relative to a pseudonymised scoreboard"), C's
  fixed-key S4, and B/C's concurrent calibration for the measurement model ("θ_m is identified by other designers'
  benchmarks and the anchor set").
- **A's tier bug** only affects the named-arm p values. Named sham Ψ (0.40–0.65) equals its correct within-tier null
  mean, and p goes from <0.001 to 0.12–0.86. The blinded primary Ψ, p and CI are bit-identical; Holm decisions do not
  change.
- **DIF.** A fixes each model's ability on the whole pool. The code top model (gpt61sol) then shows +0.27 log-odds "home
  advantage" even in the none arm, where nothing was displayed. Re-estimating ability on the produced benchmarks brings
  every arm to |γ| ≤ 0.11, all CIs including 0. Math sham +0.13 comes only from the named sham arms (tier-1 leaders).
  Difficulty interactions explain little.
- **Score access.** Benchmarks get 3.8 points harder (pooled, [−5.0, −2.5], 12 designers), for true, sham and inverted
  scores alike, mostly after the first view. Narrative shows nothing: +0.5 [−0.3, +1.4]. Drafts do not move toward the
  sham display.

## 1. Reconciliation table

### S2: self-rank gain under the true label (rank under blinded − rank under true; positive = ranked higher with the true label)

Sample sizes per pool (factual/math/code): A's pooled rows have 288/256/287 blinded and 120/108/120 true benchmarks.
Sham-only rows have 60/55/60 blinded and 60/54/60 true.

| definition | factual | math | code | pooled |
|---|---|---|---|---|
| **A** (all info arms pooled; A-mixed keys) | +0.13 [−0.12, +0.37] p .09 | **+0.40 [+0.05, +0.74] p .0002** | +0.05 [−0.36, +0.42] | +0.20 [−0.04, +0.43] |
| A pooling, 12 keys | +0.01 [−0.23, +0.25] | −0.04 [−0.33, +0.23] p .69 | −0.15 [−0.52, +0.18] | −0.06 [−0.26, +0.14] |
| A pooling, 13 keys | −0.02 | −0.04 | −0.10 | −0.05 [−0.27, +0.18] |
| sham-only rows, A-mixed keys | +0.12 | **+0.69 [+0.32, +1.06]** | −0.13 | +0.23 |
| **C** (sham-only, 12 keys) | −0.07 [−0.41, +0.27] | +0.00 [−0.26, +0.28] | −0.38 [−0.83, +0.03] | −0.15 [−0.38, +0.08] |
| **B** (sham-only, 13 keys) | −0.07 | +0.02 | −0.48 [−1.00, −0.04] | −0.17 |

- The key set is what moves A's estimate. In math, a designer's mean self-rank in sham/blinded is 7.08 under A-mixed keys
  versus 6.40 over 12 keys: +0.68 places.
- The same +0.65 to +0.72 inflation appears in true_blinded, inverted and instructed (all 13 keys). Sham/true and
  true_named are not inflated (12 keys).

### S3: inverted-arm τ minus none-arm τ to the reverse reference (inverted n 36/31/35, none n 60/56/60)

| definition | factual | math | code | pooled |
|---|---|---|---|---|
| **A**: inverted 13 keys vs none 12 keys, Fisher z | +0.025 | **+0.173 [+0.05, +0.30] p .0002** | −0.021 | +0.059 |
| same key sets, raw τ | +0.009 | +0.037 [+0.012, +0.065] | −0.003 | +0.014 |
| **B/C**: 13 vs 13 keys, raw τ | +0.019 [−0.012, +0.051] | +0.006 [−0.019, +0.031] p .26 | −0.038 [−0.080, +0.003] | −0.005 [−0.021, +0.013] |
| 12 vs 12 keys, raw τ | +0.022 | +0.015 [−0.007, +0.038] p .04 | −0.039 [−0.083, −0.002] | −0.001 |

- Math none-arm τ to the reverse reference is −0.892 over 12 keys and −0.860 over 13. That 0.032 gap accounts for most
  of A's raw +0.037.
- Fisher z only rescales the raw difference by about ×4.7 at |τ| ≈ 0.88.
- The clipping constant only matters for one code inverted benchmark over 12 keys.

### S4: true-score arms minus none, τ to the reference (true n 120/107/120, none n 60/56/60)

| definition | factual | math | code | pooled |
|---|---|---|---|---|
| **A** (true_blinded 13 keys; true_named and none 12), Fisher z | −0.018 | −0.072 | +0.053 [−0.07, +0.19] p .13 | −0.013 |
| A-mixed keys, raw τ | −0.005 | −0.017 | +0.024 | +0.001 |
| **C** (12 keys, raw τ) | −0.008 | −0.005 | **+0.042 [+0.004, +0.088] p .0002** | +0.010 [−0.009, +0.029] |
| 12 keys, Fisher z | −0.020 | −0.012 | +0.117 [−0.004, +0.247] p .001 | +0.028 |
| 13 keys, raw τ | −0.009 | −0.002 | +0.042 [+0.006, +0.082] | — |
| **B** (session keys: true_named 12, others 13), raw τ | −0.014 | +0.014 | **+0.059 [+0.022, +0.098]** | +0.020 |

### Other A outputs hit by the same bug

| quantity | A as frozen (A-mixed keys) | consistent keys |
|---|---|---|
| S1 sham/blinded (math / code) | −0.76 / −0.73 | 13 keys: −0.07 / −0.29 |
| C1 instructed gain (factual / math / code) | +0.73 / +0.10 / +0.17 | 12 keys: +0.86 [+0.09, +1.77] / +0.57 / +0.43; 13 keys: +0.65 / +0.58 / +0.28 |

Under 13 keys, C1 still fails its cluster-CI criterion in all three pools. Under 12 keys the factual CI excludes 0, but
that set drops the sessions whose target is the placebo (n 32 instead of 36); math and code still fail.

### Which definition PREREGISTRATION §7 supports

- **Rankings**: "computed on the displayed panel keys (… plus the placebo under pseudonyms)". The none arm is also
  pseudonymous (13 displayed keys), so A's rule that the placebo counts only where `displayed_order` exists has no
  textual basis.
- **S2 / H2**: "gains rank when the designer is told its identity and can see its own row, relative to a pseudonymised
  scoreboard". That describes the randomised sham/true vs sham/blinded contrast that B and C use.
- **S3**: "τ-b(produced, inverted display) minus the none-arm τ-b(produced, reverse of reference)". That is a raw τ-b
  difference over 13 keys in both arms, as B and C do.
- **S4**: the key set across a 12-key and a 13-key display is unspecified. Only C's fixed 12 keys compares like with
  like.
- **§8 measurement model**: "concurrent … every produced benchmark plus the designer-free anchor set; θ_m is identified by
  other designers' benchmarks and the anchor set". That is B/C's concurrent calibration, not A's two-stage fit on the
  anchor alone.

## 2. Audit of A's tier bug

The wrapper `scripts/a_tier_audit.py` imports the frozen module unchanged. Run in the default panel state, it reproduces
every frozen A number exactly in all three pools.

| global | where A uses it | effect on confirmatory outputs |
|---|---|---|
| `TIERS` | the randomisation null for named rows in `primary_endpoint` and `leader_rank_gain` | Pilot tiers hold no confirmatory keys, so the named null became a uniform permutation. Affects named-arm Ψ p values and null means, the S1 sham and true_named p values, and Holm. |
| `DISPLAYED_KEYS`, `HELDOUT_KEYS` | fallbacks only | Never reached: every row carries `displayed_keys` and held-out scores. |
| `PLACEBO_KEYS` | imported, never used | none (the placebo pair is hard-coded correctly) |

Named sham Ψ against the correct within-tier null:

| pool | Ψ (true / false / pooled identity) | frozen p | p with confirmatory tiers | null mean (tanh) |
|---|---|---|---|---|
| factual | 0.415 / 0.405 / 0.292 | 0.0001 each | 0.120 / 0.858 / 0.170 | 0.402 / 0.416 / 0.282 |
| math | 0.640 / 0.655 / 0.463 | 0.0001 each | 0.846 / 0.436 / 0.841 | 0.653 / 0.653 / 0.474 |
| code | 0.487 / 0.486 / 0.340 | 0.0001 each | 0.185 / 0.769 / 0.476 | 0.478 / 0.493 / 0.340 |

- The S1 sham p value changes only slightly: factual 0.243→0.239, math 0.932→0.862, code 0.970→0.952. Holm decisions are
  unchanged.
- The blinded primary is bit-identical: factual 0.0311 (p 0.136), math −0.0222 (p 0.767), code −0.0002 (p 0.498).

## 3. Measurement model (DIF)

Home advantage γ in log-odds, with 95% CI where shown. Columns are true_named / true_blinded / sham.

| specification | factual | math | code |
|---|---|---|---|
| A reproduced | −0.15 / −0.11 / −0.01 | 0.00 / −0.02 / **+0.13** | **+0.31 / +0.39** / −0.08 |
| A, valid sessions only, or no session fixed effects | ±0.01 of the row above | same | same |
| A with model-specific difficulty slopes (2PL anchor) | −0.14 / −0.09 / −0.01 | +0.16 / +0.15 / +0.09 | +0.31 / +0.40 / −0.10 |
| A with model × difficulty-decile anchor | −0.17 / −0.12 / 0.00 | +0.10 / +0.09 / +0.13 | +0.31 / +0.40 / −0.09 |
| **A with ability re-estimated on the produced benchmarks** | −0.04 / +0.01 / +0.01 | −0.01 / −0.02 / −0.03 | +0.02 [−0.09, +0.14] / +0.11 [−0.03, +0.26] / +0.01 |
| **B/C fallback GLM** | −0.05 / 0.00 / +0.01 | 0.00 / −0.01 / −0.03 | +0.03 / +0.12 [−0.02, +0.27] / 0.00 |

- My B/C fallback matches C's frozen output to three decimals; my A reproduction matches frozen A to within ±0.005.
- **Pseudo-target control.** Under A's specification, setting Target to the reference top model in every arm gives, in
  code (gpt61sol): none **+0.27 [+0.15, +0.40]**, sham +0.27, narrative +0.43, true_named +0.31, true_blinded +0.40. In
  factual (gpt61sol) it is −0.13 in none; in math (grok47) +0.03.
- In true arms that model is always the Target, so A's code true-arm effect exists without any display.
- **Difficulty.** In code, the top model's per-session residual correlates −0.33 with benchmark easiness (n 467), so it
  does relatively better on harder benchmarks. Difficulty-interaction anchors leave the code effect unchanged, though,
  and adding Target × difficulty terms only cuts it to +0.15 / +0.24.
- **Math sham +0.13** comes only from the named cells: sham_true +0.32 [+0.13, +0.51], sham_false +0.23, sham_blinded
  −0.03. With ability re-estimated it becomes −0.03 / −0.02 / −0.04.
- **Caveat for all three implementations.** In true arms, Target (`displayed_leader`) is the reference top model, but
  that model was actually shown on top at the first scores view in only:

  | true_named / true_blinded sessions | factual | math | code |
  |---|---|---|---|
  | top model shown first | 6/59 and 9/60 | 0/54 and 1/53 | 47/59 and 53/60 |

## 4. What designers did with the scores

**Activity.**
- Numeric score views per session in sham: factual 5.0 [3.8, 6.4], math 7.3 [5.2, 9.6], code 6.8. True and inverted arms
  are similar. None and narrative arms get no numeric views.
- Items removed in rounds 1 and 2 (sham vs none):

  | pool | sham | none |
  |---|---|---|
  | math | 59.5 and 55.2 | 10.8 and 33.3 |
  | code | 41.9 and 39.5 | 10.3 and 9.3 |

- Non-unit item weights were used in 38% of math sham sessions vs 20% in none.

**Do edits track the sham display?** No. Change in τ(draft, displayed order) from the first view to submission:

| cell | factual | math | code |
|---|---|---|---|
| sham/blinded (n 60/55/59) | +0.003 [−0.020, +0.023] | −0.013 [−0.044, +0.014] | −0.036 [−0.067, −0.006] |
| sham/blinded, displayed leader's rank change | −0.08 [−0.48, +0.29] | +0.08 | +0.50 [−0.11, +1.07] |
| inverted | −0.033 | +0.016 | −0.085 [−0.134, −0.039] |
| sham, τ to reference | +0.034 | −0.002 | +0.069 [+0.023, +0.126] |

In code, drafts move toward the reference ranking, which pulls them away from a random or reversed display. That is the
quality-driven pattern, not steering.

**Score access makes benchmarks harder.** Mean reference accuracy of the chosen items:

| cell | factual | math | code | pooled −none |
|---|---|---|---|---|
| none (n 60/56/60) | 0.622 [0.588, 0.651] | 0.853 [0.829, 0.874] | 0.842 [0.826, 0.861] | — |
| narrative −none | −0.006 | +0.017 | +0.005 | +0.005 [−0.003, +0.014] |
| sham −none | −0.013 [−0.028, +0.001] | −0.066 [−0.084, −0.045] | −0.038 [−0.058, −0.019] | −0.039 [−0.051, −0.026] |
| true (both arms) −none | −0.020 | −0.063 | −0.033 | −0.039 [−0.052, −0.025] |
| inverted −none | −0.012 | −0.059 | −0.027 | — |
| instructed −none | −0.056 | −0.007 | −0.007 | −0.023 [−0.043, −0.004] |
| score arms (excl. instructed) −none | −0.015 [−0.031, −0.001] | −0.064 [−0.082, −0.045] | −0.035 [−0.054, −0.018] | **−0.038 [−0.050, −0.025]** |

- **Per designer.** In math 11 of 12 designers make harder benchmarks when they see scores (−1.8 to −9.9 points). grok43
  is the exception in every pool (+0.5 math, +1.3 code, +0.2 factual).
- **Timing.** In math sham, items added after the first view are 0.777 against 0.864 before: −0.087 [−0.133, −0.046]. In
  code sham it is −0.029. In none, later additions are easier (+0.045 math).
- **Between vs within category** (score arms minus none):

  | pool | total | between categories | within categories |
  |---|---|---|---|
  | math | −0.064 | −0.043 | −0.021 |
  | code | −0.035 | +0.002 | −0.036 |
  | factual | −0.015 | 0.000 | −0.015 |

- **Math source mix.** Score arms move away from AIME (−0.107 share [−0.159, −0.053]) and MATH (−0.087) toward HMMT
  (+0.104), SMT, CMIMC and APEX. Distance of the category mix from none is 0.19 for sham and 0.03 for narrative.

## 5. Limitations

- I recomputed B's and C's definitions in my own code rather than re-running their frozen code. My recomputations match
  their frozen numbers: S2 C +0.003, S3 B/C +0.006, S4 C +0.042, S4 B +0.059.
- B's and C's mixed models were not refitted; only the fallback GLMs were.
- The τ at the first view uses partial drafts, so it is noisy.
- Not done: the counterfactual reversion of score-referencing actions (§11) and the kept-versus-viewed decomposition
  (§10).

Files: results.json (every number above), grid_secondaries.json, a_tier_audit_{factual,math,code}.json,
dif_{factual,math,code}.json, mechanism_summary.json, scripts/.
