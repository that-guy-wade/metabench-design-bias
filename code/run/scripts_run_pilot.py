"""T1 pilot: generate session configs (deterministic seeds), write pre-registration hashes BEFORE any session runs,
then run phases.  Phase A = blind (none) sessions for the power analysis; Phase B = sham / blinded-identity /
instructed / named / inverted / narrative arms.  Pilot data are excluded from the confirmatory analysis.

usage: scripts_run_pilot.py hash            # generate configs + hashes (requires complete precompute)
       scripts_run_pilot.py run A [--concurrency 12]
       scripts_run_pilot.py run B [--concurrency 12] [--only sham,true_blinded,...]
"""
import sys, asyncio, json, hashlib, time, argparse
sys.path.insert(0, "/path/to/metabench/run")
from pathlib import Path
from metabench.llm import LLM, load_keys_from_env_file
from metabench.pool import load_pool
from metabench.panel import load_correctness, DISPLAYED_KEYS, HELDOUT_KEYS, PLACEBO_KEYS, PILOT_PANEL
from metabench.scoring import reference_scores
from metabench.arms import make_session_config, SessionConfig
from metabench.designer import run_batch, DESIGNER_SPECS

R = Path("/path/to/metabench/run")
MASTER_SEED = 20261025
DESIGNERS = ["opus55", "sonnet55", "gpt55"]
K_ROUNDS = 4

# (info_arm, identity_arm, replicates)
PHASE_A = [("none", "blinded", 4)]
PHASE_B = [("sham", "blinded", 3), ("true_blinded", "blinded", 2), ("instructed", "blinded", 2), ("true_named", "true", 2),
           ("sham", "true", 1), ("sham", "false", 1), ("inverted", "blinded", 1), ("narrative", "blinded", 1)]


def session_seed(designer, arm, ident, rep):
    h = hashlib.sha256(f"{MASTER_SEED}|{designer}|{arm}|{ident}|{rep}".encode()).hexdigest()
    return int(h[:8], 16)


def load_reference():
    pool = load_pool(R / "data/pool_pilot.jsonl")
    corr = load_correctness(R / "data/panel_correctness_pilot.jsonl")
    models = DISPLAYED_KEYS + PLACEBO_KEYS + HELDOUT_KEYS
    n_expected = len(pool) * 3
    cover = {m: sum(len(corr.get((i, m), [])) for i in pool) for m in models}
    short = {m: n for m, n in cover.items() if n < 0.98 * n_expected}
    if short:
        raise SystemExit(f"precompute incomplete: {short} (expected {n_expected} per model)")
    ref = reference_scores(list(pool), models, corr)
    return pool, corr, ref, cover


def make_configs(phase, ref, only=None):
    plan = PHASE_A if phase == "A" else PHASE_B
    cfgs = []
    for arm, ident, reps in plan:
        if only and arm not in only:
            continue
        for d in DESIGNERS:
            for rep in range(reps):
                sid = f"T1_{d}_{arm}_{ident}_r{rep}"
                cfgs.append(make_session_config(sid, d, arm, ident, rep, session_seed(d, arm, ident, rep), ref, k_rounds=K_ROUNDS))
    return cfgs


def write_hashes(ref, cover):
    pool_hash = hashlib.sha256((R / "data/pool_pilot.jsonl").read_bytes()).hexdigest()
    corr_hash = hashlib.sha256((R / "data/panel_correctness_pilot.jsonl").read_bytes()).hexdigest()
    code_hash = hashlib.sha256(b"".join(sorted((R / "metabench" / f).read_bytes() for f in ["llm.py", "pool.py", "panel.py", "arms.py", "interface.py", "designer.py", "scoring.py"]))).hexdigest()
    out = {"written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "master_seed": MASTER_SEED, "k_rounds": K_ROUNDS,
           "pool_sha256": pool_hash, "panel_correctness_sha256": corr_hash, "pipeline_code_sha256": code_hash,
           "panel": [{"key": s.key, "model_id": s.model_id, "effort": s.effort, "role": s.note} for s in PILOT_PANEL],
           "samples_per_item": 3, "coverage": cover, "reference_scores": {k: round(v, 5) for k, v in ref.items()},
           "reference_ranking": sorted(ref, key=lambda k: -ref[k]),
           "sessions": []}
    for phase in ("A", "B"):
        for c in make_configs(phase, ref):
            out["sessions"].append({"session_id": c.session_id, "phase": phase, "designer": c.designer, "info_arm": c.info_arm,
                                    "identity_arm": c.identity_arm, "seed": c.seed, "config_hash": c.config_hash,
                                    "displayed_order": c.displayed_order, "displayed_leader": c.displayed_leader,
                                    "target_model": c.target_model, "false_identity": c.false_identity})
    out["sessions_sha256"] = hashlib.sha256(json.dumps(out["sessions"], sort_keys=True).encode()).hexdigest()
    (R / "prereg/pilot_hashes.json").write_text(json.dumps(out, indent=1))
    print(f"wrote prereg/pilot_hashes.json: {len(out['sessions'])} sessions; sessions_sha256={out['sessions_sha256']}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["hash", "run"])
    ap.add_argument("phase", nargs="?", default="A")
    ap.add_argument("--concurrency", type=int, default=12)
    ap.add_argument("--only", default=None)
    ap.add_argument("--no-probes", action="store_true")
    a = ap.parse_args()
    load_keys_from_env_file()
    pool, corr, ref, cover = load_reference()
    if a.cmd == "hash":
        write_hashes(ref, cover)
        return
    hashes = json.loads((R / "prereg/pilot_hashes.json").read_text())
    registered = {s["session_id"]: s["config_hash"] for s in hashes["sessions"]}
    cfgs = make_configs(a.phase, ref, only=a.only.split(",") if a.only else None)
    for c in cfgs:
        assert registered.get(c.session_id) == c.config_hash, f"config hash mismatch for {c.session_id}: re-registration required"
    done = set()
    bpath = R / "results/benchmarks.jsonl"
    if bpath.exists():
        for line in open(bpath):
            r = json.loads(line)
            if r.get("status") == "ok":
                done.add(r["session_id"])
    cfgs = [c for c in cfgs if c.session_id not in done]
    print(f"phase {a.phase}: {len(cfgs)} sessions to run ({len(done)} already done)")
    llm = LLM(anthropic_concurrency=40, openai_concurrency=56, log_path=str(R / "logs/llm_pilot.jsonl"))
    t0 = time.time()
    rows = asyncio.run(run_batch(cfgs, llm, pool, corr, ref, R / "sessions", R / "results", concurrency=a.concurrency, probes=not a.no_probes))
    ok = sum(1 for r in rows if r["status"] == "ok" and r["valid"])
    print(f"phase {a.phase} finished: {ok}/{len(rows)} valid in {time.time()-t0:.0f}s; est cost ${llm.totals['cost']:.2f}; errors {llm.totals['errors']}")


if __name__ == "__main__":
    main()
