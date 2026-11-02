import sys, asyncio
sys.path.insert(0, "/path/to/metabench/run")
from pathlib import Path
from metabench.llm import LLM, load_keys_from_env_file
from metabench.pool import load_pool
from metabench.panel import PILOT_PANEL, precompute
load_keys_from_env_file()
K = int(sys.argv[1]) if len(sys.argv) > 1 else 3
pool = load_pool(Path("/path/to/metabench/run/data/pool_pilot.jsonl"))
llm = LLM(anthropic_concurrency=56, openai_concurrency=56, log_path="/path/to/metabench/run/logs/llm_panel.jsonl")
asyncio.run(precompute(pool, PILOT_PANEL, K, Path("/path/to/metabench/run/data/panel_correctness_pilot.jsonl"), llm, concurrency=96))
