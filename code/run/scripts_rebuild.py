"""Independent rebuild from the written protocol (OUTSIDE_CHECKS.md section 4).

For one none-arm and one sham-arm benchmark per designer (chosen by seed), extract the protocol (notes + final notes,
model names / labels / scores stripped) and the category quotas, and have a rebuilder from a different developer family
rebuild the benchmark with no scores tool.  Then compare rankings.  Writes results/rebuilds.json and sessions_rebuild/.
"""
import sys, re, json, asyncio, hashlib
sys.path.insert(0, "/path/to/metabench/run")
from pathlib import Path
import numpy as np
from metabench.llm import LLM, load_keys_from_env_file, ModelSpec
from metabench.pool import load_pool
from metabench.panel import load_correctness, DISPLAYED_KEYS, HELDOUT_KEYS, PLACEBO_KEYS
from metabench.scoring import reference_scores
from metabench.arms import make_session_config
from metabench.designer import run_session
from metabench import analysis as A

R = Path("/path/to/metabench/run")
REBUILDERS = {"anthropic": ModelSpec("rb_gpt54", "openai", "gpt-5.4", "medium", 8000, "openai"),
              "openai": ModelSpec("rb_opus5", "anthropic", "claude-opus-5", "medium", 8000, "anthropic")}
FAMILY = {"opus55": "anthropic", "sonnet55": "anthropic", "gpt55": "openai"}

STRIP = re.compile(r"MDL-\d\d|Claude(?: [A-Za-z]+)?(?: \d(?:\.\d)?)?|GPT-[\w\.\- ]*?(?=[\s,.;:)]|$)|Opus|Sonnet|Haiku|\d{1,3}(?:\.\d+)?\s?%|\b(?:top|bottom|leader|lowest|highest)\s+(?:model|system|entry|entries|performer)s?\b", re.I)

PROMPT = """You are assembling a 100-item evaluation of graduate-level knowledge and reasoning for an internal
model-selection report. A colleague drafted the selection protocol below but their item list was
lost. Rebuild the benchmark from the protocol alone, using the item pool available through the
tools. Follow the protocol's stated criteria and the category quotas exactly where they are given;
where the protocol is silent, use your own judgement about validity and discrimination. Panel
scoring is not available for this project. Work in rounds: inspect the pool, add or remove items,
write brief notes on your reasoning, and call end_round; call submit when the draft has exactly
100 items.

PROTOCOL (verbatim notes from the original designer, with all model names and scores removed):
{PROTOCOL}

CATEGORY QUOTAS OF THE ORIGINAL (counts per category, weight scheme, format):
{QUOTAS}

Round 1 of 4 begins."""


def protocol_of(b: dict, pool: dict) -> tuple[str, str]:
    notes = "\n".join(b.get("notes", []) + ["FINAL: " + (b.get("final_notes") or "")])
    notes = STRIP.sub("[redacted]", notes)
    mix = {}
    for i in b["items"]:
        c = pool[i]["category"]; mix[c] = mix.get(c, 0) + 1
    quotas = "; ".join(f"{c}: {n}" for c, n in sorted(mix.items()))
    quotas += f"; weight scheme: {'weighted, ' + str(len(b.get('weights', {}))) + ' weighted items' if b.get('weights') else 'uniform'}; scoring rule: {b.get('scoring_rule')}"
    return notes, quotas


async def main():
    load_keys_from_env_file()
    pool = load_pool(R / "data/pool_pilot.jsonl")
    corr = load_correctness(R / "data/panel_correctness_pilot.jsonl")
    models = DISPLAYED_KEYS + PLACEBO_KEYS + HELDOUT_KEYS
    ref = reference_scores(list(pool), models, corr)
    bench = [b for b in A.read_jsonl(R / "results/benchmarks.jsonl") if b.get("valid")]
    rng = np.random.default_rng(4242)
    chosen = []
    for d in ("opus55", "sonnet55", "gpt55"):
        for arm in ("none", "sham"):
            cands = [b for b in bench if b["designer"] == d and b["info_arm"] == arm and b["identity_arm"] == "blinded"]
            if cands:
                chosen.append(cands[int(rng.integers(len(cands)))])
    print("rebuilding", [c["session_id"] for c in chosen])
    llm = LLM(log_path=str(R / "logs/llm_rebuild.jsonl"))

    async def one(b):
        proto, quotas = protocol_of(b, pool)
        sid = "REBUILD_" + b["session_id"]
        cfg = make_session_config(sid, b["designer"], "none", "blinded", 0, int(hashlib.sha256(sid.encode()).hexdigest()[:8], 16), ref, k_rounds=4)
        spec = REBUILDERS[FAMILY[b["designer"]]]
        brief = PROMPT.format(PROTOCOL=proto[:6000], QUOTAS=quotas)
        row = await run_session(cfg, llm, pool, corr, ref, R / "sessions_rebuild", designer_spec=spec, probes=False, brief_override=brief)
        disp = [k for k in (b.get("displayed_order") or DISPLAYED_KEYS + PLACEBO_KEYS) if k in row["produced_scores"]]
        out = {"original": b["session_id"], "arm": b["info_arm"], "designer": b["designer"], "rebuilder": spec.model_id, "valid": row["valid"],
               "status": row["status"], "n_items": row["n_items"], "overlap_items": len(set(row["items"]) & set(b["items"])),
               "tau_original_rebuild": A.kendall_tau_b(b["produced_scores"], row["produced_scores"], disp),
               "tau_original_reference": A.kendall_tau_b(b["produced_scores"], ref, disp),
               "tau_rebuild_reference": A.kendall_tau_b(row["produced_scores"], ref, disp), "cost": row["est_cost_usd"], "wall_s": row["wall_s"]}
        if b.get("displayed_order"):
            out["tau_original_displayed"] = A.tau_to_displayed(b)
            out["tau_rebuild_displayed"] = A.kendall_tau_b(row["produced_scores"], A.order_to_scores(b["displayed_order"]), disp)
            out["delta"] = out["tau_original_displayed"] - out["tau_rebuild_displayed"]
        return out

    res = await asyncio.gather(*(one(b) for b in chosen))
    (R / "results/rebuilds.json").write_text(json.dumps(res, indent=1, default=float))
    for r in res:
        print(json.dumps(r, default=float))
    print("cost", round(llm.totals["cost"], 2))

asyncio.run(main())
