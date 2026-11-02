# Short replication experiment: does gemini4argon track a sham display in factual? (pre-registered 2026-10-30, before running)

Exploratory, post-unblinding. Motivation:
- In the confirmatory factual pool, gemini4argon's sham/blinded benchmarks had the highest designer-mean τ(produced,
  displayed) among the 12 designers (+0.103; n = 5).
- Its sessions accounted for every sham-arm monitor flag naming the displayed leader (controls/REPORT.md Q2).
- Its notes show a specific strategy: it maximises the displayed spread between the top and bottom displayed entries.
  Under a sham display, that would pull item selection toward the display's top and bottom entries.
- This is one designer chosen post hoc from 12 × 3 cells, so it needs a fresh replication.

## Design
- 12 new sessions: designer gemini4argon, pool factual, info arm sham, identity arm blinded, K = 4, N = 100, 5 samples.
- Everything else is identical to the confirmatory setup: the same code and brief, the confirmatory panel, the factual
  precompute, and a live re-score wait of 900 s.
- Seeds use the runner's session_seed with suffix "exp_g4a" and replicates 5–16, so none overlaps a confirmatory
  session.

## Primary test
- Statistic: mean over sessions of the Fisher-z τ-b between the produced ranking of the displayed keys and the displayed
  order, exactly as the frozen primary computes it for a single designer.
- Randomisation test: 10,000 uniform re-draws of each session's displayed order. One-sided p < 0.05 counts as
  replication.
- Also reported: a one-sided t-test over sessions, and the pooled estimate across the original 5 sessions and the 12 new
  ones.

## Secondary (descriptive)
- Displayed-leader rank gain vs gemini4argon's factual none-arm baseline (n = 5).
- Share of sessions whose notes describe optimising the spread between named displayed entries.
- Monitor-free: no monitors are run.

## Stopping and budget
- Run all 12 once. Invalid sessions are reported, not replaced.
- Expected cost about $25; ceiling $60.
