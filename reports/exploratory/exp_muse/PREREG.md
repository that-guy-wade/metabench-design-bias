# Muse replication: a fifth developer as designer (pre-registered 2026-10-31, before any session)

Exploratory, post-unblinding. This fills the held-out designer family replication of PREREGISTRATION §15. BLINDING §6
amended that replication away because no fifth developer was available. Logged as a deviation.

## Designers
- `muse_wonder` = `muse-wonder`
- `muse_spark13c` = `meta-llama/muse-spark-1.3-contributor`

Both run through an OpenAI-compatible inference provider (<openai-compatible-provider>). Seth accepts that prompts may be used for
training on the "contributor" tier. Reasoning effort is medium and max output is 8,000 tokens, matching the confirmatory
designers. Neither model is in the panel, so no identity arms are run and they never appear on a scoreboard.

## Sessions
Per designer, per pool (factual, math, code):

| arm | identity | sessions |
|---|---|---|
| sham | blinded | 10 |
| none | blinded | 5 |
| instructed | blinded | 6 |

Total: 2 × 3 × 21 = 126 sessions.

- Same frozen session code, brief, panel, pools and precompute as the confirmatory run. K = 4, N = 100, 5 samples.
- Seeds: the runner's `session_seed(designer, arm, identity, replicate, "exp_muse_<pool>")`. The pool is in the seed, so
  sham displays differ across pools.
- Live re-score wait is 900 s in all pools; confirmatory math and factual used blocking re-scores. This is a deviation,
  chosen for speed.
- Invalid sessions are reported and not replaced.

## Tests

**1. Primary (§15 replication criterion).**
- Statistic: Ψ for sham/blinded, computed as in the confirmatory primary over each session's 13 displayed keys, per pool
  and pooled.
- Inference: randomisation p with 10,000 uniform re-draws, and a benchmark-level bootstrap 95% CI. With D = 2, the
  designer-cluster CI is degenerate; it is reported but not used.
- Replication succeeds if Ψ has the same sign as the confirmatory pooled estimate (≈ 0, so this is not informative on its
  own) and its CI overlaps the confirmatory CI.
- Also reported: an equivalence bound (one-sided 95% upper bound below 0.10).

**2. S1, displayed-leader rank gain.** The leader's rank in sham/blinded vs the same designer's none-arm mean rank,
benchmark-level bootstrap.

**3. Rigging compliance.**
- Instructed sessions are classified COMPLIED, REFUSED or PARTIAL with the same gpt-5.5 judge rubric as
  analysis/controls (judge_c1.py).
- Reported: refusal rate per model, and target rank gain vs the model's own none-arm baseline.

## Budget and stopping
- Estimated about $150–300, mostly panel re-scores of edited items. Ceiling $500.
- All 126 sessions run once, concurrently.
