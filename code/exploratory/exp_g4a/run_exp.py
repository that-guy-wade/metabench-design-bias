"""Replication: 12 new gemini4argon factual sham/blinded sessions (see PREREG.md). Exploratory; never writes into run/."""
import asyncio
import json
import os
import sys
from pathlib import Path

RUN = Path("/path/to/metabench/run")
sys.path.insert(0, str(RUN))
os.chdir(RUN)

from metabench import panel  # noqa: E402
panel.set_active("confirmatory")
from metabench.llm import LLM, load_keys_from_env_file  # noqa: E402
from metabench.pool import load_pool  # noqa: E402
from metabench.panel import load_correctness, DISPLAYED_KEYS, PLACEBO_KEYS, HELDOUT_KEYS  # noqa: E402
from metabench.scoring import reference_scores  # noqa: E402
from metabench.arms import make_session_config  # noqa: E402
from metabench.designer import run_session  # noqa: E402
from metabench.briefs import pool_description_for  # noqa: E402
import scripts_runner as SR  # noqa: E402

OUT = Path("/path/to/metabench/analysis/exp_g4a")
WORK = Path("/path/to/metabench/unblinded/WORK_factual")


async def main() -> None:
    load_keys_from_env_file()
    pool = load_pool(RUN / "pools/factual_qa/pool.jsonl")
    corr = load_correctness(WORK / "precompute/factual.jsonl")
    models = DISPLAYED_KEYS + PLACEBO_KEYS + HELDOUT_KEYS
    ref = reference_scores(list(pool), models, corr)
    llm = LLM(**{f"{p}_concurrency": n for p, n in SR.llm_concurrency().items()}, log_path=str(OUT / "llm_calls.jsonl"))
    sessions = OUT / "sessions"
    sessions.mkdir(exist_ok=True)
    cfgs = []
    for rep in range(5, 17):
        seed = SR.session_seed("gemini4argon", "sham", "blinded", rep, "exp_g4a")
        sid = f"EXP_g4a_factual_gemini4argon_sham_blinded_r{rep}"
        cfgs.append(make_session_config(sid, "gemini4argon", "sham", "blinded", rep, seed, ref, k_rounds=4,
                                        n_items_required=100, samples_per_item=5, pool_name="factual",
                                        pool_description=pool_description_for("factual"), with_monitors=False))

    async def one(c):
        try:
            row = await run_session(c, llm, pool, corr, ref, sessions, probes=True, live_wait_s=900.0)
        except Exception as e:  # noqa: BLE001
            row = {"session_id": c.session_id, "status": f"exception:{type(e).__name__}", "valid": False, "error": str(e)[:300]}
        with open(OUT / "rows.jsonl", "a") as f:
            f.write(json.dumps(row, default=str) + "\n")
        print(c.session_id, row.get("status"), row.get("valid"), row.get("est_cost_usd"), row.get("wall_s"), flush=True)
        return row

    await asyncio.gather(*(one(c) for c in cfgs))
    print("totals", json.dumps(llm.totals, default=str), flush=True)


asyncio.run(main())
