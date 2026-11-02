# Replication: does gemini4argon track a sham display in factual? (EXPLORATORY, 2026-10-30)

Pre-registration: PREREG.md, written before launch. Script: run_exp.py. Analysis: analyze_exp.py.

## Result: no. The lead does not replicate.

| sessions | n | designer-mean τ(produced, display) | randomisation p (one-sided, 10,000) | t-test p | displayed-leader rank gain vs none [95% boot CI] |
|---|---|---|---|---|---|
| original (confirmatory) | 5 | +0.106 | 0.139 | 0.16 | 0.00 [−0.84, +0.84] |
| **new (replication)** | 12 | **−0.016** | **0.60** | 0.57 | −0.44 [−1.24, +0.33] |
| combined | 17 | +0.020 | 0.36 | 0.39 | −0.31 [−0.94, +0.29] |

- All 12 new sessions were valid.
- Cost:
  - designer sessions: $24.79;
  - all LLM calls, including live panel re-scores of edited items: $37.43.
- The original five-session signal was not significant on its own (p 0.14). The replication puts the effect at zero.
- Every new session's notes describe optimising the spread or separation between the displayed entries (12/12), so the
  strategy that looked like a mechanism is routine for this designer and does not produce tracking.
- The sham-arm monitor flags on the original sessions were therefore false positives prompted by the designer naming the
  displayed top and bottom labels in its spread notes.
