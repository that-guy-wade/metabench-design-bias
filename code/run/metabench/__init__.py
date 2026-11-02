"""MetaBench: does showing a benchmark-designing LLM the scoreboard change the benchmark it designs?

Package layout
  llm.py        provider clients (Anthropic, OpenAI), unified chat + tool calling, retries, cost accounting
  pool.py       T1 item pools (pilot domain: MMLU-Pro non-math)
  panel.py      evaluee panel definition and per-item x per-model x per-sample correctness precompute
  arms.py       information arms, identity arms, sham generators, hashing
  interface.py  T1 design interface (tools, state, action log, scores view)
  designer.py   designer session runner (K rounds)
  scoring.py    scoring produced benchmarks from precomputed correctness
  analysis.py   endpoints: tau-b, Fisher-z, randomisation test, cluster bootstrap, DIF model
  power.py      power simulation (extends digests/E-power-sim.py)
  monitors.py   intent layer: artifact-only / full-trace monitors, probes, provenance classifier
"""
