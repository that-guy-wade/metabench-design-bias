# MetaBench T1: exploratory analysis after unblinding (2026-10-30)

Everything here is exploratory. It was done after REPORT_CONFIRMATORY.md existed (BLINDING §5). No frozen file was
modified.

Worker reports with full tables and scripts:
- analysis/controls/REPORT.md (C1, C6, self-recognition)
- analysis/capacity/REPORT.md (C2–C5, the oracle, named-sham null)
- analysis/reconcile/REPORT.md (A vs B/C, DIF, mechanism)
- analysis/exp_g4a/REPORT.md (replication)

All are under /path/to/metabench/. The confirmatory summary, with corrections, is
ANALYSIS_CONFIRMATORY_2026-10-30.md.

## Bottom line

Showing a benchmark designer a scoreboard does not make it build a benchmark that tracks the scoreboard. The pipeline can
detect a designer that deliberately steers, and the task leaves plenty of room to steer. Designers use scores for
something else: they make the benchmark harder.

1. **No steering toward the displayed ranking.**
   - The primary Ψ is ≈ 0 in all pools, and all three implementations agree.
   - The random-subset control gives the same ≈ 0 (C3).
   - Drafts do not move toward the sham display after a scores view.
   - The one designer-level lead (gemini4argon, factual) failed a pre-registered 12-session replication: τ −0.016,
     p = 0.60.
2. **The positive control works once refusals are separated out.**
   - The whole-arm failure of C1 comes from refusal. An OpenAI judge labelled the instructed sessions 43 complied,
     53 refused and 6 partial; 15 of 18 spot checks agreed.
   - Refusal by developer: Anthropic 27/27, gpt61sol and gpt6luna 18/18, Google 8/21, gpt55 0/9, xAI 0/27.
   - When designers complied, the target gained +1.44 ranks [+0.73, +2.20] pooled, and the CI excluded 0 in every pool.
     When they refused, it gained −0.29.
   - Monitors flagged 97–100% of complying sessions, with 0/650 false flags in the none arm. Compliance was almost always
     disclosed in the notes, so covert steering is untested.
3. **The task allows large steering.**
   - A greedy oracle choosing 100 of 2,000 items can make any of the 12 designer models #1 in every pool: a mean gain of
     5.7–6.1 ranks.
   - Instructed designers used about 9% of that headroom on average; compliers used about 25%.
   - So the null is not caused by a task with no room to move.
4. **Instrument noise is acceptable.**
   - Test–retest ceiling 0.82–0.91, against the pre-registered failure line of 0.5 (C5).
   - The placebo copy separates no more than sampling noise (C2).
   - Designers recalled the displayed leader in 1,070 of 1,071 sessions (C6).
   - Self-recognition is at chance; 98% declined to guess.
5. **What designers do with scores: harder benchmarks, legitimately.**
   - Items chosen with score access are 3.8 accuracy points harder (pooled [−5.0, −2.5]), equally for true, sham and
     inverted scores. A narrated leader without numbers has no effect.
   - In math, 11 of 12 designers do this. In math the source mix shifts from AIME and MATH toward HMMT, SMT, CMIMC and
     APEX.
   - This is the pre-registered "quality-driven use" alternative, not bias.
   - True scores also bring the code benchmarks' ranking closer to the reference (S4, +0.04 τ).
6. **Implementation A has two bugs. Neither touches the primary.**
   - **Key-set inconsistency** (13 vs 12 ranked keys across the arms being compared). It produced A's math S2 (+0.40)
     and S3 (+0.17), hid code S4, and biased S1 and the C1 gain downward.
   - **Pilot reputation tiers** (A never activates the confirmatory panel). They made the named-arm nulls uniform and
     produced spurious Ψ 0.41–0.65 at p < 0.001. The true excess over the within-tier null is −0.02 to +0.02.
   - **Anchor-only calibration.** A's DIF "home advantage" for the top code model appears even in the none arm (+0.27). It
     comes from calibrating ability on the anchor alone. With concurrent calibration, as §8 describes and B and C
     implement, every arm is ≈ 0.

## What this means for the pre-registered claims

- **H1 (feedback steering).** Not supported. The positive control, analysed on complying designers, shows the instrument
  detects a 1.4-rank steer. The C3 random-subset null and the C4 oracle show the null is not an artefact of the task. The
  strict §2 reading ("C1 failed, so the null is uninterpretable") stands in the confirmatory record. The
  refusal-separated control is exploratory and post hoc: complier status is chosen by the designer.
- **H2 (identity channel).** Not supported under the pre-registration-faithful definitions (B and C).
  - S2 is ≈ 0 in factual and math. In code it is −0.38 to −0.48: designers rank themselves slightly lower under their
    true label, not significant in the pre-stated direction.
  - Self-recognition is at chance.
- **H3 (leader channel).** Not supported. S1 is ≈ 0 or slightly negative in every pool and implementation.
- **Integrity note.** One gemini31pro instructed session planted an item instruction meant to fire for one model only.
  It failed, but it is the kind of behaviour a released benchmark-design tool should screen for.

## Limits

- **Refusal is selected by the designer.** The compliers are mostly xAI, gpt55 and gemini31pro. The detected steer is
  what those designers do when asked.
- **Monitors.** Recall was measured on mostly disclosed compliance.
- **Not done:** the counterfactual reversion (§11), the kept-versus-viewed decomposition (§10), and the provenance
  classifier (§12).
- **Missing data:** math lost 50 Google-designer sessions; code lost the Anthropic monitor for one hour.
- **Run cost.** About $41.50 of exploratory LLM spend:
  - judge and probe extraction: $4.11;
  - replication: $37.43.

## Addendum (2026-10-30 evening): checks run before the final write-up

Sources: analysis/sensitivity/REPORT.md and analysis/provenance/REPORT.md. All exploratory; no API spend.

- **Designer-independent positive control.** Simulated followers start from each real sham benchmark and swap items
  toward its display.
  - Ψ becomes detectable after 1–2 greedy swaps per benchmark (2–5 naive swaps). It reaches the full pre-registered claim
    (Ψ > 0.15) at 3 greedy or 7 naive swaps.
  - A follower steering as hard as the complying instructed designers (+1.4 ranks for the leader) would give Ψ ≈ 0.20.
  - With partial adoption, it is detected once 3–6 of the 12 designers follow. A single following designer is not
    detectable.
  - Random swaps stay at Ψ ≈ 0.
- **Equivalence.** One-sided 95% upper bounds on Ψ: factual 0.064–0.077, math 0.012–0.031, code 0.043–0.053, pooled
  0.026–0.033. Ψ ≥ 0.10 is rejected in every pool (p ≤ 0.008).
- **Robustness.** Ψ stays within ±0.02 of the reported values when the Google designers are dropped, when
  contamination-flagged models are dropped, and under either bound for the unresolved precompute triples.
  - The unresolved triples are 24 in math and 163 in code. The 31 and 164 quoted earlier were counts taken mid-run.
- **Design note.** A (designer, replicate) cell shows the same sham display in all three pools, because the session seed
  omits the pool. Pooled randomisation tests should share draws across pools; per-pool tests are unaffected.
- **Held-out redistribution (OUTSIDE_CHECKS §3).** Sham arm minus none: +0.06 [−0.06, +0.18], so no shift. Complying
  instructed sessions show +0.25 [+0.02, +0.48] pooled, but the sign is inconsistent across pools. The statistic is noisy
  with 4 held-outs.
- **Kept vs viewed (§10).**
  - A sham display steers neither what designers look at (exposure −0.006 [−0.013, +0.001]) nor what they keep
    (selection −0.004 [−0.016, +0.009]).
  - The hardening with score access comes from selection (−3.9 points [−5.2, −2.6]), not exposure (−0.3).
  - An apparent true_blinded tracking (+0.06) is an overlap artefact: the none arm shows the same lift toward its own
    round-1 draft (+0.09).
- **Provenance (§12).** The designer is identifiable from its 100 kept items: 88.5% accuracy pooled across 12 classes
  (chance 8.3%), and 77% on sham/blinded benchmarks. The developer is identifiable at 92%.
  - The signal goes far beyond difficulty (+0.42 over the difficulty and category-mix baseline). It transfers across arms
    and reflects selection habits, not wording.
  - Designer signatures therefore exist in the artefact even under blinded identities. There is no evidence that they
    favour the designer (Ψ and S2 ≈ 0; self-recognition at chance).
