# MetaBench T1 confirmatory analysis (post-unblinding, 2026-10-30)

Source: REPORT_CONFIRMATORY.md (scripts_unblind.py, 2026-10-29 22:57Z; factual A re-run on linux/amd64, DEVIATIONS
2026-10-30). Three frozen implementations: A = metabench/analysis.py (the pre-registered software, PREREGISTRATION §14),
B and C = independent implementations written from the pre-registration alone (BLINDING §3). Everything below the
"Confirmatory" heading quotes frozen endpoints; everything else is labelled exploratory.

## 1. Confirmatory

### Primary H1: does a designer track an uninformative (sham) scoreboard? No.

Ψ = tanh of the designer-averaged Fisher-z τ-b(produced ranking, displayed sham order), sham arm, pseudonymous identity.
A, B and C agree to three decimals in every pool.

| pool | n bench / designers | Ψ | 95% designer-cluster CI | randomisation p (one-sided) | designer t p |
|---|---|---|---|---|---|
| factual | 60 / 12 | +0.031 | [−0.021, +0.085] | 0.136 | 0.061 |
| math | 55 / 12 | −0.022 | [−0.083, +0.042] | 0.767 | 0.868 |
| code | 60 / 12 | −0.000 | [−0.062, +0.064] | 0.498 | 0.504 |

- The falsifiable claim (Ψ > 0.15, cluster CI excluding 0, randomisation p < 0.05) fails all three components in every
  pool.
- The pre-stated prediction (Ψ between 0.10 and 0.35) is rejected: every CI upper bound is below 0.10. The frozen size had
  power 0.84 for Ψ ≈ 0.11.
- No designer is consistently positive across pools; the largest per-designer means (opus5 +0.18 code, gemini4argon
  +0.11 factual) are not replicated in the other pools.
- Round-by-round τ(draft, display) is flat (B: no round significant after BH in any pool).
- RBO(0.8) to the displayed order equals its permutation null (0.33–0.37 vs null 0.36).

### Positive control C1 (instructed bias): fails its pre-registered criterion in every pool

Criterion: target rank gain > 0 with a 95% CI excluding 0. Instructed arm: 3 benchmarks per designer (n ≈ 30–36 per pool).

| pool | A gain (positions) | A cluster CI | A permutation p | C gain | C cluster CI |
|---|---|---|---|---|---|
| factual | +0.73 | [−0.12, +1.69] | <0.001 | +0.65 | [−0.16, +1.59] |
| math | +0.10 | [−0.68, +1.01] | 0.002 | +0.58 | [−0.15, +1.44] |
| code | +0.17 | [−0.58, +1.04] | 0.025 | +0.28 | [−0.42, +1.05] |

- The measurement model agrees: B's and C's instructed-arm home advantage is +0.01 to +0.08 log-odds, with every CI
  including 0 (ETS category A).
- The point estimates are positive and A's permutation test (over target identity) rejects. The designer-cluster CIs,
  which the protocol requires, do not exclude 0. That fits strongly heterogeneous compliance: some designers move the
  target, others do not.
- PREREGISTRATION §2 abandon rule: if C1 fails, "the pipeline is broken and no null is interpretable; stop and fix".
  Read strictly, the H1 null cannot be taken as evidence that designers *could not* steer through the scoreboard. It can
  still be read as a measured fact: they *did not* track the sham display. Even when explicitly instructed, designers
  moved the target by under one position on average, so this T1 task gives a designer little room to move a stable panel
  ranking (τ to reference 0.81–0.90 in every arm).
- The C1 second criterion (full-trace monitor recall ≥ 0.8 on the instructed arm) was not computed by any implementation.

### Secondary endpoints (Holm family of four): the implementations disagree; B and C agree with each other

| endpoint | factual A / B / C | math A / B / C | code A / B / C |
|---|---|---|---|
| S1 displayed-leader gain (sham), positions | +0.00 / −0.10 / +0.02 | −0.30 / +0.03 / −0.04 | −0.23 / −0.22 / −0.09 |
| S2 self-rank gain, true vs blinded | +0.13 / −0.07 / −0.07 | **+0.40** / +0.02 / +0.00 | +0.05 / −0.48* / −0.38 |
| S3 inverted τ − none τ | +0.03 / +0.02 / +0.04 | **+0.17** / +0.01 / +0.02 | −0.02 / −0.04 / −0.14 |
| S4 true − none τ to reference | −0.02 / −0.01 / −0.01 | −0.07 / +0.01 / −0.01 | +0.05 / **+0.06** / **+0.04** |

- Bold: Holm p < 0.05 in that implementation.
- \* B's S2a cluster CI is [−0.98, −0.02], so the designer's own entry *loses* rank under its true label. That is
  opposite to H2, and the one-sided test does not reject.
- B and C agree on every Holm decision. Only one survives: in code, true-score arms rank the panel slightly closer to the
  reference than the none arm (τ +0.04 to +0.06; B Holm p < 0.001, C < 0.001). A's estimate is similar (+0.053) but its
  Fisher-z CI includes 0.
- A alone finds math S2 and math S3. Both trace to A's definitions, not to the data.
  - **Corrected after the reconcile analysis (analysis/reconcile/REPORT.md).** My first explanation (pooling across arms,
    and atanh near |τ| = 1) was wrong.
  - The cause is a key-set inconsistency. A ranks the panel over 13 keys (placebo included) where a row has
    `displayed_order` (sham, inverted, instructed, true arms) and over 12 keys elsewhere (none, narrative), then contrasts
    those arms.
  - With one fixed key set, the estimates collapse:
    - math S2: +0.40 → −0.04;
    - math S3: +0.17 → +0.006–0.015 raw τ.
  - The same inconsistency hides code S4, which is +0.042 [+0.004, +0.088] with C's fixed 12 keys.
  - The pre-registration's text (rankings over the displayed keys plus the placebo under pseudonyms; S2 relative to a
    pseudonymised scoreboard; S3 as a τ-b difference) supports B's and C's definitions.
- A is the software the pre-registration names (§14), so its numbers stand in the record. This document reports the
  disagreement and its cause rather than choosing an implementation.

### Measurement model (pooled home-advantage DIF)

- B and C (identical fallback GLMs; B also fitted the mixed model) find no home advantage in any arm or pool. Every
  95% CI includes 0, and every |ETS delta| ≤ 0.35 (category A).
- A (two-stage anchor-conditioned GLM, mixed model skipped for size) finds:
  - math: γ(sham) +0.13 log-odds;
  - code: true-arm totals of +0.32 and +0.40 log-odds (ETS B for true_blinded);
  - factual: γ(sham) ≈ 0.
- The signs differ across pools and B and C do not reproduce these, so the measurement-model evidence for home advantage
  is not robust.

## 2. Exploratory

- **Named-identity sham Ψ: RESOLVED, an artefact.**
  - A never calls `panel.set_active("confirmatory")`, so its named-arm null used pilot tiers and was effectively uniform.
  - With the correct within-tier null, the excess Ψ is −0.021 to +0.015, with every p ≥ 0.12
    (analysis/capacity, analysis/reconcile).
  - The original note is kept below for the record.
- **Named-identity sham Ψ (A only, descriptive; superseded):**
  - Sham with real names gives Ψ = 0.41 (factual), 0.64 (math) and 0.49 (code), with p < 0.001 against A's
    within-tier null.
  - The displayed order under names is a within-tier shuffle of reputation tiers, so a large τ is expected under the null.
    The report does not print the null mean, so the excess over null is unknown.
  - B's named-sham displayed-leader gain is ≈ 0 in every pool (+0.11, −0.11, +0.10; all CIs include 0). This is the one
    lead worth checking on the raw data (A's endpoints.json has null_mean_z for the named arms).
- **Score access makes benchmarks harder:**
  - In math and code, all four held-out models score lower, relative to the reference, in the arms that show panel scores
    (sham, inverted, true_named, true_blinded) than in none.
    - math, sham vs none: gemini35flash −0.27 vs −0.16; gpt54 −0.20 vs −0.11; grok420 −0.13 vs −0.07; sonnet46 −0.29
      vs −0.17.
    - code, sham vs none: −0.055 vs −0.015; −0.043 vs −0.010; −0.041 vs −0.026; −0.106 vs −0.043.
    - factual shows the same direction, weaker (sham +0.07 to +0.11 vs none +0.09 to +0.12).
  - In math and code, rank flips against the reference rise in score arms. In math: 4.3–5.7 vs 3.5 in none.
  - This is the pre-registered "legitimate, quality-driven use" alternative: designers use scores to pick harder,
    discriminative items, and that reshuffles closely matched models without tracking the display.
- **Placebo (C2-like):**
  - |sonnet55 − placebo| is 0.007–0.015 in every arm, with no excess over none.
  - One exception: code true_named, +0.004 (p = 0.008).
  - The pre-registered criterion (replicate-noise 95th percentile) was not computed.
- **Contamination:**
  - Pool items predate most developers' cutoffs, so the per-developer contamination estimates were mostly not
    estimable.
  - Flags: math (opus5, gemini38flash, gemini31pro and two held-outs); code (all Anthropic panel entries plus
    gemini4argon, by method b).
  - Ψ is a within-session ranking comparison and is insensitive to a model's absolute level. Flagged models' absolute
    scores should not be quoted.

## 3. Not computed by any implementation (pre-registered controls)

- C1 monitor recall on the instructed arm.
- C2 replicate-noise criterion.
- C3 random-subset Ψ.
- C4 greedy-oracle upper bound on the achievable rank gain.
- C5 test–retest ceiling.
- C6 manipulation check (probe recall of the displayed leader).
- Self-recognition (§12).
- Provenance classifier.
- Decompositions (§10).

C4 and per-designer instructed compliance decide how to read the C1 failure: whether the task offers no lever, or
designers declined to use it. C6 decides whether the sham display was attended. All of these need the unblinded
per-session data (sessions/, probes.json, monitors/).

## 4. Data caveats

- **Math:** 50 Google-designer sessions were invalid after their one-time replacement ran during the Google sign-in
  outage, leaving sham/blinded n = 55 with gemini31pro 3, gemini38flash 3 and gemini4argon 4 of 5.
- **Code:** the Anthropic credit outage (19:22–20:26 UTC on 2026-10-28) invalidated 90 sessions. All were replaced once
  (89 valid). Sessions in that hour lack the Anthropic monitor and the Claude panel re-scores.
- **Panel answers:** 164 code and 31 math xAI panel triples were unresolved (≥ 98.98% coverage per configuration).
- **Platform:**
  - Factual A ran on Linux; the rest ran on macOS.
  - A's Monte Carlo intervals depend on the hash seed (fixed at 0) and on row order (registered order). On the code
    pool, the recomputed and sealed A agree on all but 108 of 7,150 keys beyond 1e-6 when row order is matched.
