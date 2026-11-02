"""Smoke test: short sessions (20 items, 1 round) on both providers against whatever correctness exists so far.
Not part of the pilot; written to sessions_smoke/.  Uses a cheap OpenAI designer (gpt-5.4-mini) and Sonnet 5.5 at low effort."""
import sys, asyncio, json, shutil
sys.path.insert(0, "/path/to/metabench/run")
from pathlib import Path
from metabench.llm import LLM, load_keys_from_env_file, ModelSpec
from metabench.pool import load_pool
from metabench.panel import load_correctness, DISPLAYED_KEYS, HELDOUT_KEYS, PLACEBO_KEYS
from metabench.scoring import reference_scores
from metabench.arms import make_session_config
from metabench.designer import run_session
load_keys_from_env_file()
R = Path("/path/to/metabench/run")
pool = load_pool(R / "data/pool_pilot.jsonl")
corr = load_correctness(R / "data/panel_correctness_pilot.jsonl")
models = DISPLAYED_KEYS + PLACEBO_KEYS + HELDOUT_KEYS
ref = reference_scores(list(pool), models, corr)
print("reference (partial precompute):", {k: round(v, 3) for k, v in ref.items()})
shutil.rmtree(R / "sessions_smoke", ignore_errors=True)
llm = LLM(log_path=str(R / "logs/llm_smoke.jsonl"))
async def main():
    cfgs = [
        (make_session_config("smoke_sonnet_sham", "sonnet55", "sham", "blinded", 0, 1, ref, k_rounds=1), ModelSpec("sonnet55", "anthropic", "claude-sonnet-5-5", "low", 6000)),
        (make_session_config("smoke_gptmini_instr", "gpt55", "instructed", "true", 0, 2, ref, k_rounds=1), ModelSpec("gpt54mini", "openai", "gpt-5.4-mini", "low", 6000)),
    ]
    for c, _ in cfgs:
        c.n_items_required = 20
    rows = await asyncio.gather(*(run_session(c, llm, pool, corr, ref, R / "sessions_smoke", designer_spec=s) for c, s in cfgs))
    for r in rows:
        print(r["session_id"], r["status"], r["n_items"], r["valid"], r["n_llm_calls"], r["est_cost_usd"], r["wall_s"], r["displayed_order"])
        print("  produced:", {k: round(v, 3) for k, v in r["produced_scores"].items()})
    print("totals", llm.totals)
asyncio.run(main())
