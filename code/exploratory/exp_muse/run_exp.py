"""Muse replication (PREREG.md): 2 Meta designers x 3 pools x 21 sessions, concurrently. Exploratory; never writes into run/.
Usage: run_exp.py [--smoke] [--pools factual,math,code]"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

RUN = Path("/path/to/metabench/run")
sys.path.insert(0, str(RUN))
os.chdir(RUN)

import openai  # noqa: E402
from metabench import panel  # noqa: E402
panel.set_active("confirmatory")
from metabench import llm as L  # noqa: E402
from metabench.llm import LLM, ModelSpec, load_keys_from_env_file  # noqa: E402
from metabench.pool import load_pool  # noqa: E402
from metabench.panel import load_correctness, DISPLAYED_KEYS, PLACEBO_KEYS, HELDOUT_KEYS  # noqa: E402
from metabench.scoring import reference_scores  # noqa: E402
from metabench.arms import make_session_config  # noqa: E402
from metabench.designer import run_session  # noqa: E402
from metabench.briefs import pool_description_for  # noqa: E402
import scripts_runner as SR  # noqa: E402

OUT = Path("/path/to/metabench/analysis/exp_muse")
UNB = Path("/path/to/metabench/unblinded")
POOL_FILE = {"factual": "factual_qa", "math": "math", "code": "code"}
BASE_URL = "https://<openai-compatible-provider>/v1"
DESIGNERS = {"muse_wonder": "muse-wonder", "muse_spark13c": "meta-llama/muse-spark-1.3-contributor"}
MUSE_IDS = set(DESIGNERS.values())
ARMS = [("sham", 10), ("none", 5), ("instructed", 6)]


def meta_key() -> str:
    for line in open("/path/to/model-keys.env"):
        if line.startswith("META_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("META_API_KEY missing")


class MetaLLM(LLM):
    """Routes Muse model ids through the OpenAI-compatible provider on the xAI (chat-completions) code path."""
    _mc = None

    @property
    def mc(self):
        if self._mc is None:
            self._mc = openai.AsyncOpenAI(api_key=meta_key(), base_url=BASE_URL, max_retries=3, timeout=600)
        return self._mc

    async def _xai(self, spec, system, messages, tools, max_tokens, temperature):
        if spec.model_id not in MUSE_IDS:
            return await super()._xai(spec, system, messages, tools, max_tokens, temperature)
        # same request/response handling as LLM._xai, with the Muse client; no awaits between swap and restore
        # except the call itself, so use a dedicated shallow proxy instead of swapping shared state
        proxy = _Proxy(self, self.mc)
        return await LLM._xai(proxy, spec, system, messages, tools, max_tokens, temperature)


class _Proxy:
    """Minimal stand-in so LLM._xai uses the Muse client without mutating the shared LLM object."""
    def __init__(self, llm, client):
        self._llm, self.xc = llm, client

    def __getattr__(self, name):
        return getattr(self._llm, name)


def specs():
    return {k: ModelSpec(k, "xai", mid, "medium", 8000, "meta", "designer (Muse replication)") for k, mid in DESIGNERS.items()}


async def main(a):
    load_keys_from_env_file()
    llm = MetaLLM(**{f"{p}_concurrency": n for p, n in SR.llm_concurrency().items()}, log_path=str(OUT / "llm_calls.jsonl"))
    sp = specs()
    sessions = OUT / ("sessions_smoke" if a.smoke else "sessions")
    sessions.mkdir(exist_ok=True)
    jobs = []
    for pool_name in a.pools.split(","):
        pool = load_pool(RUN / f"pools/{POOL_FILE[pool_name]}/pool.jsonl")
        corr = load_correctness(UNB / f"WORK_{pool_name}/precompute/{pool_name}.jsonl")
        ref = reference_scores(list(pool), DISPLAYED_KEYS + PLACEBO_KEYS + HELDOUT_KEYS, corr)
        arms = [("sham", 1)] if a.smoke else ARMS
        for d in DESIGNERS:
            for arm, n in arms:
                for rep in range(n):
                    seed = SR.session_seed(d, arm, "blinded", rep, f"exp_muse_{pool_name}")
                    sid = f"EXP_muse_{pool_name}_{d}_{arm}_blinded_r{rep}"
                    cfg = make_session_config(sid, d, arm, "blinded", rep, seed, ref, k_rounds=1 if a.smoke else 4,
                                              n_items_required=20 if a.smoke else 100, samples_per_item=5,
                                              pool_name=pool_name, pool_description=pool_description_for(pool_name),
                                              with_monitors=False)
                    jobs.append((cfg, pool, corr, ref, sp[d]))

    async def one(cfg, pool, corr, ref, spec):
        try:
            row = await run_session(cfg, llm, pool, corr, ref, sessions, designer_spec=spec, probes=True, live_wait_s=900.0)
        except Exception as e:  # noqa: BLE001
            row = {"session_id": cfg.session_id, "status": f"exception:{type(e).__name__}", "valid": False, "error": str(e)[:300]}
        with open(OUT / ("rows_smoke.jsonl" if a.smoke else "rows.jsonl"), "a") as f:
            f.write(json.dumps(row, default=str) + "\n")
        print(cfg.session_id, row.get("status"), row.get("valid"), row.get("n_llm_calls"), row.get("wall_s"), flush=True)

    await asyncio.gather(*(one(*j) for j in jobs))
    print("totals", json.dumps(llm.totals, default=str), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--pools", default="factual,math,code")
    asyncio.run(main(ap.parse_args()))
