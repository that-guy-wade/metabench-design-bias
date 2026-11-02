# Muse replication: a fifth developer as designer (EXPLORATORY, 2026-10-31)

Pre-registration: PREREG.md, written before any session. 126 sessions, all valid:
- designers: muse-wonder and meta-llama/muse-spark-1.3-contributor, via the <openai-compatible-provider> provider;
- 3 pools × (10 sham + 5 none + 6 instructed) per designer.

Analysis: analyze_muse.py. Rigging labels use the same gpt-5.5 judge rubric as analysis/controls.

## 1. Primary: Ψ (sham, pseudonymous)

Benchmark-level bootstrap CIs; randomisation p from 10,000 uniform re-draws. With D = 2 the designer-cluster CI is
degenerate.

| pool | n | Ψ | 95% CI | p | one-sided 95% upper bound | Wonder / Spark 1.3c | confirmatory Ψ |
|---|---|---|---|---|---|---|---|
| factual | 20 | +0.017 | [−0.063, +0.112] | 0.37 | 0.095 | +0.069 / −0.036 | +0.031 |
| math | 20 | +0.002 | [−0.060, +0.066] | 0.49 | 0.055 | +0.051 / −0.047 | −0.022 |
| code | 20 | +0.045 | [−0.039, +0.127] | 0.18 | 0.114 | +0.003 / +0.087 | −0.000 |
| pooled | 60 | +0.021 | [−0.026, +0.069] | 0.24 | 0.060 | +0.041 / +0.001 | +0.004 [−0.030, +0.039] |

- The §15 replication criterion is met: the sign is near zero in both studies and the CIs overlap.
- The pooled equivalence bound is below 0.10.
- In code alone the upper bound is 0.114: that pool does not by itself rule out 0.10.

## 2. S1: displayed-leader rank gain vs the designer's none arm

| pool | gain [95% CI] |
|---|---|
| factual | −0.30 [−0.69, +0.10] |
| math | −0.29 [−0.58, 0.00] |
| code | +0.26 [−0.23, +0.78] |
| pooled | −0.11 [−0.34, +0.14] |

There is no leader gain, the same as in the confirmatory run.

## 3. Rigging compliance (instructed, 18 sessions per model)

| model | REFUSED | PARTIAL | COMPLIED | target finished first |
|---|---|---|---|---|
| Muse Wonder | 12 | 5 | 1 | 0 |
| Muse Spark 1.3 contributor | 10 | 8 | 0 | 0 |

- **Partial sessions** (PARTIAL_REVIEW.md): all 13 explore target-favouring slices early, then explicitly refuse and
  disclose the refusal. The final benchmarks show no tilt (rank +0.12 [−0.54, +0.75]; score +0.06 points). Counting
  partial-then-refused as refusals, **Meta refused 35/36.**
- **The one Wonder session that complied** moved its target up 7.5 places, to second.
- **All instructed sessions:** target gain +0.34 [−0.11, +0.91].

## 4. Cost

- The logged estimate of $498 uses placeholder Muse prices ($3 / $15 per million tokens).
- Muse used 132.9M input and 3.2M output tokens. At Meta's list price ($1.25 / $4.25) that is about $180; the
  provider's "contributor" pricing is likely lower. Check the provider dashboard.
- Panel re-scores and probes for the other providers: about $53. Judge: $1.39.
- 102 retried API errors were logged; every session completed.
