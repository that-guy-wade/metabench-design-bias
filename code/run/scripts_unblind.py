"""Unblinding: rebuild one WORK tree per pool from the decrypted sealed tree, check it, run the frozen analyses, write
REPORT_CONFIRMATORY.md (BLINDING.md section 5; DEVIATIONS 2026-10-29 17:45).  Offline: no network, no model keys.

    python scripts_unblind.py --unsealed ~/Downloads/unsealed --prereg prereg --out ~/Downloads/unblinded \
        [--pools factual,math,code] [--n-perm 10000 --n-boot 10000] [--jobs N]

Why a rebuild: the three pools sealed their tmpfs WORK trees into the same sealed/ directory with the same relative
paths.  Per-pool paths (sessions/T1_<pool>_*, monitors/T1_<pool>_*.json, precompute/<pool>.jsonl) survived for every
pool; pool-level paths (results/*, registration_full.json, run_manifest.json, reference_item_outcomes.jsonl, endpoints/,
health/, llm_calls.jsonl) hold only the last pool sealed (code).  This script rebuilds, for each pool, what the runner's
WORK held just before finish(), using the runner's own code (scripts_runner.Runner: load_pool, load_correctness,
write_reference_outcomes, make_cfg, analysis_commands) and the plaintext registration in prereg/.

Steps, all printed as counts only (never content):
  1. integrity: every MANIFEST.json entry exists under --unsealed with exactly plaintext_bytes bytes (abort otherwise)
  2. rebuild OUT/WORK_<pool>/ per pool; results/*.jsonl rows in the registered order, then the replacements in the order
     of prereg/confirmatory_replacements_<pool>.json (the runner appended rows in completion order, which is not
     recorded for factual and math; section "Row order" of docs/UNBLINDING.md)
  3. registration check per pool (abort on a missing, duplicate or undeclared session or a config hash mismatch)
  4. control (code pool): the rebuilt pool-level files against the sealed code copies (row multisets keyed by id)
  5. the frozen analyses per pool exactly as Runner.run_analyses / run_contamination, --out OUT/<pool>/endpoints/<name>;
     for code also on a copy whose results/*.jsonl rows follow the sealed row order, and both compared with the sealed
     code endpoints
  6. OUT/REPORT_CONFIRMATORY.md, a mechanical assembly
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import math
import os
import resource
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import scripts_runner as R  # noqa: E402
from metabench import panel  # noqa: E402

POOL_FILES = {"factual": "pools/factual_qa/pool.jsonl", "math": "pools/math/pool.jsonl", "code": "pools/code/pool.jsonl"}  # scripts_run_confirmatory.sh
POOL_ORDER = ["factual", "math", "code"]
CONTROL_POOL = "code"            # the last pool sealed: its pool-level sealed files are its own
RESULTS_FILES = ["benchmarks.jsonl", "item_outcomes.jsonl", "monitors.jsonl", "session_log.jsonl", "reference_item_outcomes.jsonl"]
ROW_KEYS: dict[str, Callable[[dict], tuple]] = {
    "benchmarks.jsonl": lambda r: (r["session_id"],),
    "item_outcomes.jsonl": lambda r: (r["session_id"], r["item_id"], r["model_key"]),
    "monitors.jsonl": lambda r: (r["session_id"],),
    "session_log.jsonl": lambda r: (r["session_id"], r.get("attempt")),
    "reference_item_outcomes.jsonl": lambda r: (r["item_id"], r["model_key"]),
}
# run-environment fields of an endpoints.json / contamination.json (key-path suffixes): the input paths (B's and C's
# inputs.results_dir, contamination's inputs.reference) and wall-clock timings differ by construction
ENV_KEYS = {"inputs/results_dir", "inputs/reference", "elapsed_seconds", "elapsed_s", "wall_seconds", "fit_seconds"}
# pools whose run_manifest.json was written before BUILD4: `panel` is the plain list of the 17 keys (BUILD4_REPORT section 2;
# ARTEFACT_SCHEMA section 1).  C reads the manifest panel: a list sends it to its documented fallback (designer keys = the
# sorted intersection of displayed_keys, plus a warning), and that key order enters C's permutation draws, so the shape
# is reproduced rather than modernised
LIST_PANEL_POOLS = {"factual"}
# run_manifest.json fields a rebuild cannot know (wall-clock and process facts); no analysis reads them
MANIFEST_UNKNOWN = ["run_id", "started_at", "ended_at", "concurrency", "api_errors_total"]


class Fatal(SystemExit):
    pass


def say(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def read_jsonl(p: Path) -> list[dict]:
    with open(p) as f:
        return [json.loads(l) for l in f if l.strip()]


def canon(o) -> str:
    return json.dumps(o, sort_keys=True)


def link_or_copy(src: str, dst: str) -> None:
    """Hard link when possible (the rebuild only reads session files), else copy."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


# ----------------------------------------------------------------------------------------------- 1. integrity

def check_integrity(unsealed: Path) -> dict:
    mp = unsealed / "MANIFEST.json"
    if not mp.exists():
        raise Fatal(f"integrity: {mp} missing")
    files = json.loads(mp.read_text())["files"]
    missing = [rel for rel in files if not (unsealed / rel).is_file()]
    wrong = [rel for rel in files if (unsealed / rel).is_file() and (unsealed / rel).stat().st_size != files[rel]["plaintext_bytes"]]
    on_disk = {str(p.relative_to(unsealed)) for p in unsealed.rglob("*") if p.is_file()} - {"MANIFEST.json", "MANIFEST.sha256"}
    res = {"manifest_entries": len(files), "ok": len(files) - len(missing) - len(wrong), "missing": len(missing),
           "size_mismatch": len(wrong), "unlisted_files": len(on_disk - set(files))}
    say(f"integrity: {res['manifest_entries']} manifest entries, {res['ok']} present with the listed byte count, "
        f"{res['missing']} missing, {res['size_mismatch']} size mismatches; {res['unlisted_files']} files under --unsealed not in MANIFEST")
    if missing or wrong:
        raise Fatal(f"integrity check failed: {len(missing)} missing, {len(wrong)} size mismatches; nothing was rebuilt")
    return res


# ----------------------------------------------------------------------------------------------- 2. rebuild

def make_runner(pool: str, reg: dict, a, work: Path) -> R.Runner:
    """A scripts_runner.Runner with the pool's registered `run` arguments on the rebuilt working directory (never seals:
    its Sealer points at an empty directory and is not called)."""
    cells = ",".join(f"{arm}:{ident}:{n}" for arm, ident, n in ((*R.split_cell(c), n) for c, n in reg["cells"].items()))
    argv = ["run", "--pool", a.pool_files[pool], "--pool-name", pool, "--samples", str(reg["samples_per_item"]),
            "--n-items", str(reg["n_items"]), "--k-rounds", str(reg["k_rounds"]), "--designers", ",".join(reg["designers"]),
            "--cells", cells, "--work-dir", str(work), "--allow-non-tmpfs", "--prereg-dir", str(a.prereg),
            "--sealed-dir", str(a.out / ".no_sealing"), "--n-perm", str(a.n_perm), "--n-boot", str(a.n_boot),
            "--analysis-timeout", str(a.analysis_timeout), "--analysis-memory-mib", str(a.analysis_memory_mib)]
    if reg.get("live_rescore_wait_s") is not None:
        argv += ["--live-rescore-wait-s", str(reg["live_rescore_wait_s"])]
    return R.Runner(R.build_parser().parse_args(argv))


def load_registration(prereg: Path, pool: str) -> tuple[dict, list[dict]]:
    reg = json.loads((prereg / f"confirmatory_hashes_{pool}.json").read_text())
    rp = prereg / f"confirmatory_replacements_{pool}.json"
    repl = json.loads(rp.read_text())["replacements"] if rp.exists() else []
    return reg, repl


def rebuild_pool(pool: str, a) -> dict:
    """Write OUT/WORK_<pool>/ and return the facts and the registration check counts.  Raises Fatal on any registration
    violation (missing / duplicate / undeclared session, config hash mismatch, pool hash mismatch)."""
    unsealed = a.unsealed
    reg, repl = load_registration(a.prereg, pool)
    work = a.out / f"WORK_{pool}"
    if work.exists():
        shutil.rmtree(work)
    for sub in ("sessions", "monitors", "results", "precompute"):
        (work / sub).mkdir(parents=True)
    r = make_runner(pool, reg, a, work)
    fatal: list[str] = []
    warn: list[str] = []

    # panel precompute, reference scores and reference outcomes through the runner's own methods
    src_pre = unsealed / "precompute" / f"{pool}.jsonl"
    if not src_pre.exists():
        raise Fatal(f"{pool}: precompute/{pool}.jsonl missing under --unsealed")
    link_or_copy(str(src_pre), str(r.precompute_path()))
    r.load_pool()
    if r.pool_sha != reg["pool_sha256"]:
        raise Fatal(f"{pool}: pool file {a.pool_files[pool]} does not match the registered pool sha256")
    precompute_hash_ok = R.sha256_file(r.precompute_path()) == reg.get("panel_correctness_sha256")
    if not precompute_hash_ok:
        warn.append("precompute file sha256 differs from the registered panel_correctness_sha256")
    r.load_correctness()
    r.write_reference_outcomes()          # results/reference_item_outcomes.jsonl + the top-level copy

    # session order: the registered list, then the declared replacements
    registered = [s["session_id"] for s in reg["sessions"]]
    reg_hash = {s["session_id"]: s["config_hash"] for s in reg["sessions"]}
    repl_of = {x["replacement"]: x["original"] for x in repl}
    order = registered + [x["replacement"] for x in repl]
    dup = len(order) - len(set(order))
    if dup:
        fatal.append(f"{dup} duplicate session ids in the registration + replacements")
    prefix = f"T1_{pool}_"
    on_disk = sorted(d.name for d in (unsealed / "sessions").iterdir() if d.is_dir() and d.name.startswith(prefix)) \
        if (unsealed / "sessions").is_dir() else []
    missing = [s for s in order if not (unsealed / "sessions" / s / "benchmark.json").is_file()]
    undeclared = sorted(set(on_disk) - set(order))
    if missing:
        fatal.append(f"{len(missing)} registered/declared sessions without sessions/<id>/benchmark.json")
    if undeclared:
        fatal.append(f"{len(undeclared)} session directories with prefix {prefix} that are neither registered nor declared replacements")
    if fatal:
        raise Fatal(f"{pool}: registration check failed: " + "; ".join(fatal))

    plan_row = {s["session_id"]: s for s in reg["sessions"]}
    by_dev = {"benchmarks": [], "item_outcomes": [], "monitors": [], "session_log": []}
    configs: dict[str, dict] = {}
    n = Counter()
    rows: dict[str, dict] = {}
    for sid in order:
        sdir = work / "sessions" / sid
        shutil.copytree(unsealed / "sessions" / sid, sdir, copy_function=link_or_copy)
        row = json.loads((sdir / "benchmark.json").read_text())
        rows[sid] = row
        cfg = json.loads((sdir / "config.json").read_text()) if (sdir / "config.json").exists() else None
        attempt = 2 if sid in repl_of else 1
        want = reg_hash.get(sid) if attempt == 1 else next(x["config_hash"] for x in repl if x["replacement"] == sid)
        n["config_json_hash_ok"] += bool(cfg and cfg.get("config_hash") == want)
        n["benchmark_hash_ok"] += row.get("config_hash") == want
        n["session_id_field_ok"] += row.get("session_id") == sid and row.get("pool_name") == pool
        n["replacement_of_ok"] += row.get("replacement_of") == repl_of.get(sid)
        # the runner's make_cfg from the registered plan row, seed and reference scores (cmd_run's own check)
        base = plan_row[repl_of.get(sid, sid)]
        rc = R.make_cfg(base, r.ref, pool, r.n_items, r.k_rounds, r.samples, suffix="rep1" if attempt == 2 else "")
        n["make_cfg_hash_ok"] += rc.config_hash == want
        n["make_cfg_config_ok"] += bool(cfg) and same_json(json.loads(rc.to_json()), cfg)
        n["reference_scores_ok"] += same_json(row.get("reference_scores"), {k: round(v, 5) for k, v in r.ref.items()})
        if attempt == 1 and cfg is not None:
            configs[sid] = cfg
        # results/*.jsonl exactly as Runner.run_many appends them for one finished session
        by_dev["benchmarks"].append(json.dumps(row) + "\n")
        io = sdir / "item_outcomes.jsonl"
        if io.exists():
            by_dev["item_outcomes"].append(io.read_text())
        mp = unsealed / "monitors" / f"{sid}.json"
        if mp.exists():
            link_or_copy(str(mp), str(work / "monitors" / f"{sid}.json"))
            by_dev["monitors"].append(json.dumps(json.loads(mp.read_text())) + "\n")
        n["monitors_as_runner_rule"] += mp.exists() == bool(row.get("status") == "ok" and row.get("items"))
        exit_code = 0 if row.get("valid") else (1 if io.exists() else 2)   # 2 = Runner.exception_row (no item outcomes written)
        log = {"session_id": sid, "designer": row.get("designer"), "info_arm": row.get("info_arm"), "identity_arm": row.get("identity_arm"),
               "attempt": attempt, "replacement_of": repl_of.get(sid), "status": row.get("status"), "valid": bool(row.get("valid")),
               "n_items": row.get("n_items"), "api_errors": int(row.get("api_errors") or 0), "n_llm_calls": row.get("n_llm_calls"),
               "wall_s": row.get("wall_s"), "started_at": row.get("started_at"), "ended_at": row["ended_at"], "exit_code": exit_code}
        by_dev["session_log"].append(json.dumps(log) + "\n")
    for name, chunks in by_dev.items():
        with open(work / "results" / f"{name}.jsonl", "w") as f:
            f.writelines(chunks)

    # registration checks that need the rows
    hash_fail = len(order) - n["config_json_hash_ok"] + len(order) - n["benchmark_hash_ok"]
    invalid_registered = [s for s in registered if not rows[s].get("valid")]
    replaced_originals = set(repl_of.values())
    bad_repl = [s for s in replaced_originals if s not in rows or rows[s].get("valid")]
    if hash_fail:
        fatal.append(f"{hash_fail} config hash mismatches (config.json or benchmark.json against the registered/declared hash)")
    if n["session_id_field_ok"] != len(order):
        fatal.append(f"{len(order) - n['session_id_field_ok']} benchmark rows whose session_id/pool_name differ from their directory")
    if n["replacement_of_ok"] != len(order):
        fatal.append(f"{len(order) - n['replacement_of_ok']} benchmark rows whose replacement_of differs from the declaration")
    if bad_repl or set(invalid_registered) != replaced_originals:
        fatal.append(f"replacement rule: {len(invalid_registered)} invalid registered sessions, {len(replaced_originals)} declared originals, "
                     f"{len(bad_repl)} declared originals not invalid")
    if fatal:
        raise Fatal(f"{pool}: registration check failed: " + "; ".join(fatal))
    for k in ("make_cfg_hash_ok", "make_cfg_config_ok", "reference_scores_ok", "monitors_as_runner_rule"):
        if n[k] != len(order):
            warn.append(f"{k}: {n[k]}/{len(order)}")

    # registration_full.json as Runner.cmd_register writes it (configs of the registered list only)
    full = {"registration": reg, "configs": configs, "reference_scores": {k: round(v, 6) for k, v in r.ref.items()}, "coverage": r.cover}
    (work / "registration_full.json").write_text(json.dumps(full, indent=1))
    # run_manifest.json as Runner.cmd_run + finish write it; MANIFEST_UNKNOWN fields cannot be rebuilt (null)
    manifest = {"run_id": None, "started_at": None, "frozen_code_sha256": reg.get("frozen_code_sha256"),
                "registration_sha256": reg["sessions_sha256"], "pool_sha256": r.pool_sha, "n_registered": len(registered),
                "designers": r.designers, "cells": r.cells, "concurrency": None, "live_rescore_wait_s": r.live_wait_s,
                "panel": [s.key for s in panel.PANEL] if pool in LIST_PANEL_POOLS else
                {"name": "confirmatory", "keys": [s.key for s in panel.PANEL], "displayed_keys": list(panel.DISPLAYED_KEYS),
                 "placebo_keys": list(panel.PLACEBO_KEYS), "heldout_keys": list(panel.HELDOUT_KEYS)},
                "substitutes": {}, "ended_at": None, "n_rows": len(order), "n_valid": sum(1 for s in order if rows[s].get("valid")),
                "api_errors_total": None, "rebuilt_by": "scripts_unblind.py (DEVIATIONS 2026-10-29 17:45)"}
    (work / "run_manifest.json").write_text(json.dumps(manifest, indent=1))

    listed = set(json.loads((unsealed / "MANIFEST.json").read_text())["files"])
    used = [str(p.relative_to(work)) for p in (work / "sessions").rglob("*") if p.is_file()] + \
           [f"monitors/{p.name}" for p in (work / "monitors").iterdir()] + [f"precompute/{pool}.jsonl"]
    facts = {"pool": pool, "registered": len(registered), "declared_replacements": len(repl), "rows": len(order),
             "valid": manifest["n_valid"], "valid_registered": sum(1 for s in registered if rows[s].get("valid")),
             "valid_replacements": sum(1 for s in repl_of if rows[s].get("valid")),
             "invalid_by_status": dict(Counter(rows[s].get("status") for s in order if not rows[s].get("valid"))),
             "monitor_files": len(by_dev["monitors"]), "item_outcome_rows": sum(c.count("\n") for c in by_dev["item_outcomes"]),
             "live_rescore_wait_s": r.live_wait_s, "precompute_hash_ok": precompute_hash_ok,
             "precompute_error_last_rows_by_provider": panel.error_counts_by_provider(r.precompute_path(), panel.PANEL),
             "inputs_not_in_manifest": sum(1 for u in used if u not in listed),
             "checks": {k: f"{v}/{len(order)}" for k, v in sorted(n.items())}, "warnings": warn,
             "analysis_commands": r.analysis_commands(), "pool_path": str(r.pool_path)}
    say(f"{pool}: rebuilt WORK_{pool}: {facts['registered']} registered, {facts['declared_replacements']} replacements, "
        f"{facts['rows']} rows, {facts['valid']} valid; registration check passed ({len(order)}/{len(order)} hashes); "
        f"{len(warn)} warnings" + (": " + "; ".join(warn) if warn else ""))
    return facts


def same_json(x, y, tol: float = 1e-9) -> bool:
    """Equality of parsed JSON values with float tolerance (configs carry raw float offsets)."""
    if isinstance(x, dict) and isinstance(y, dict):
        return x.keys() == y.keys() and all(same_json(x[k], y[k], tol) for k in x)
    if isinstance(x, list) and isinstance(y, list):
        return len(x) == len(y) and all(same_json(u, v, tol) for u, v in zip(x, y))
    if isinstance(x, float) or isinstance(y, float):
        if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return x == y
        return (math.isnan(x) and math.isnan(y)) or abs(x - y) <= tol * max(1.0, abs(x), abs(y))
    return x == y


# ----------------------------------------------------------------------------------------------- 4. control

def compare_rows(rebuilt: Path, sealed: Path, key: Callable[[dict], tuple]) -> dict:
    """Row-multiset comparison keyed by id: the number of rebuilt and sealed rows that have no identical partner."""
    if not sealed.exists():
        return {"status": "sealed copy absent"}
    a, b = read_jsonl(rebuilt), read_jsonl(sealed)
    ca, cb = Counter(canon(r) for r in a), Counter(canon(r) for r in b)
    only_a, only_b = sum((ca - cb).values()), sum((cb - ca).values())
    same_order = [key(r) for r in a] == [key(r) for r in b]
    return {"rows_rebuilt": len(a), "rows_sealed": len(b), "differing_rebuilt": only_a, "differing_sealed": only_b,
            "duplicate_keys_sealed": len(b) - len({key(r) for r in b}), "identical": only_a == 0 and only_b == 0, "same_order": same_order}


def flatten(o, prefix: str = "") -> dict:
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            out.update(flatten(v, f"{prefix}/{k}"))
        return out or {prefix: {}}
    if isinstance(o, list):
        out = {}
        for i, v in enumerate(o):
            out.update(flatten(v, f"{prefix}[{i}]"))
        return out or {prefix: []}
    return {prefix: o}


def compare_json(x, y, ignore: set[str] = frozenset(), rel_tol: float = 1e-6) -> dict:
    """Differing leaf keys of two parsed JSON documents: exact, beyond rel_tol, and how many sit under ignored key names."""
    fx, fy = flatten(x), flatten(y)
    keys = set(fx) | set(fy)
    diff = [k for k in keys if k not in fx or k not in fy or canon(fx[k]) != canon(fy[k])]
    env = [k for k in diff if any(k.endswith("/" + e) for e in ignore)]
    beyond = [k for k in diff if k not in env and not (k in fx and k in fy and same_json(fx[k], fy[k], rel_tol))]
    return {"leaf_keys": len(keys), "differing": len(diff), "differing_run_environment": len(env),
            "differing_beyond_rel_tol": len(beyond), "rel_tol": rel_tol}


def control_pool_files(work: Path, unsealed: Path) -> dict:
    """The rebuilt code tree against the sealed pool-level files (which are the code pool's own)."""
    out = {}
    for name in RESULTS_FILES:
        out[f"results/{name}"] = compare_rows(work / "results" / name, unsealed / "results" / name, ROW_KEYS[name])
    out["reference_item_outcomes.jsonl"] = compare_rows(work / "reference_item_outcomes.jsonl", unsealed / "reference_item_outcomes.jsonl",
                                                        ROW_KEYS["reference_item_outcomes.jsonl"])
    rb, sl = json.loads((work / "registration_full.json").read_text()), _maybe_json(unsealed / "registration_full.json")
    if sl is None:
        out["registration_full.json"] = {"status": "sealed copy absent"}
    else:
        d = {part: compare_json(rb.get(part), sl.get(part)) for part in ("registration", "configs", "reference_scores", "coverage")}
        d["extra_top_level_keys"] = len(set(rb) ^ set(sl))
        ts_only = d["registration"]["differing"] > 0 and compare_json({k: v for k, v in rb["registration"].items() if k != "written_at"},
                                                                       {k: v for k, v in sl["registration"].items() if k != "written_at"})["differing"] == 0
        d["identical"] = all(v["differing"] == 0 for k, v in d.items() if isinstance(v, dict)) and not d["extra_top_level_keys"]
        d["registration_written_at_only"] = ts_only
        out["registration_full.json"] = d
    rm, sm = json.loads((work / "run_manifest.json").read_text()), _maybe_json(unsealed / "run_manifest.json")
    if sm is None:
        out["run_manifest.json"] = {"status": "sealed copy absent"}
    else:
        fields = [k for k in sm if k not in MANIFEST_UNKNOWN]
        bad = [k for k in fields if canon(rm.get(k)) != canon(sm.get(k))]
        out["run_manifest.json"] = {"compared_fields": len(fields), "differing_fields": len(bad), "identical": not bad,
                                    "not_compared": [k for k in MANIFEST_UNKNOWN if k in sm]}
    return out


def attribute_stale_copies(ctrl: dict, a) -> None:
    """Sealer.seal_tree skips a path that is already sealed with the same plaintext size.  A pool-level file whose size
    did not change from pool to pool (the reference outcomes: fixed-width rows, the same pool size and panel) therefore
    still holds an earlier pool's sealed copy, and the code pool's own copy was never sealed.  Such a copy is accepted
    only when it is row-identical to that earlier pool's rebuilt file; anything else still fails the control."""
    for f in ("results/reference_item_outcomes.jsonl", "reference_item_outcomes.jsonl"):
        v = ctrl.get(f)
        if not v or v.get("status") or v.get("identical"):
            continue
        for pool in a.pools:
            if pool == CONTROL_POOL:
                continue
            if compare_rows(a.out / f"WORK_{pool}" / f, a.unsealed / f, ROW_KEYS["reference_item_outcomes.jsonl"]).get("identical"):
                v["sealed_copy_of_pool"] = pool
                break


def _maybe_json(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


def control_ok(ctrl: dict) -> tuple[bool, list[str]]:
    """Fatal unless every compared file is identical; the one documented content-free exception is a registration
    payload differing only in written_at (a later `register` invocation that found the registration unchanged)."""
    bad = []
    for f, v in ctrl.items():
        if v.get("status") == "sealed copy absent":
            bad.append(f"{f}: sealed copy absent")
        elif not v.get("identical") and not v.get("sealed_copy_of_pool") and not (f == "registration_full.json" and v.get("registration_written_at_only")
                                               and all(v[p]["differing"] == 0 for p in ("configs", "reference_scores", "coverage"))):
            bad.append(f)
    return not bad, bad


def control_line(name: str, v: dict) -> str:
    if v.get("status"):
        return f"control {name}: {v['status']}"
    if name == "registration_full.json":
        if v["identical"]:
            return f"control {name}: identical"
        parts = ", ".join(f"{p} {v[p]['differing']} differing keys" for p in ("registration", "configs", "reference_scores", "coverage"))
        return f"control {name}: {parts}" + (" (registration differs only in written_at)" if v["registration_written_at_only"] else "")
    if name == "run_manifest.json":
        return f"control {name}: " + ("identical" if v["identical"] else f"{v['differing_fields']} differing fields") + \
            f" ({v['compared_fields']} compared; not reproducible, not compared: {', '.join(v['not_compared'])})"
    if v["identical"]:
        return f"control {name}: identical ({v['rows_rebuilt']} rows; row order {'same' if v['same_order'] else 'differs'})"
    if v.get("sealed_copy_of_pool"):
        q = v["sealed_copy_of_pool"]
        return f"control {name}: sealed copy is the {q} pool's, row-identical to rebuilt WORK_{q} ({v['rows_sealed']} rows); " \
               f"the sealer skipped re-sealing this same-size file for later pools, so code's own copy was never sealed"
    return f"control {name}: {v['differing_rebuilt']} rebuilt rows and {v['differing_sealed']} sealed rows without an identical partner " \
           f"({v['rows_rebuilt']} vs {v['rows_sealed']} rows)"


def sealed_order_variant(work: Path, unsealed: Path, dest: Path) -> None:
    """A copy of the rebuilt tree whose results/*.jsonl rows follow the sealed files' row order (code control only; the
    row multisets are identical, checked before).  Everything else is linked from the rebuilt tree."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(work, dest, copy_function=link_or_copy, ignore=shutil.ignore_patterns("results"))
    (dest / "results").mkdir()
    for name in RESULTS_FILES:
        rows = read_jsonl(work / "results" / name)
        pos: dict[str, list[int]] = {}
        for i, r in enumerate(read_jsonl(unsealed / "results" / name)):
            pos.setdefault(canon(r), []).append(i)
        rows.sort(key=lambda r: pos[canon(r)].pop(0) if pos.get(canon(r)) else 1 << 60)
        with open(dest / "results" / name, "w") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)


# ----------------------------------------------------------------------------------------------- 5. analyses

def _cap_address_space(pid: int, mib: int) -> None:
    """The runner's RLIMIT_AS cap, applied to the started child with prlimit (no preexec_fn: analyses run from threads).
    Linux only; macOS has no usable RLIMIT_AS, so the cap is skipped there."""
    if mib <= 0 or not sys.platform.startswith("linux"):
        return
    cap = mib * 1024 * 1024
    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    if hard != resource.RLIM_INFINITY:
        cap = min(cap, hard)
    try:
        resource.prlimit(pid, resource.RLIMIT_AS, (cap, cap))
    except (ValueError, OSError):
        pass


def analysis_jobs(pool: str, facts: dict, work: Path, ep_root: Path, a, with_contamination: bool = True) -> list[tuple]:
    """(label, out_dir, argv): Runner.analysis_commands() with --results pointed at `work` and --out at ep_root/<name>, and
    the Runner.run_contamination() argv."""
    jobs = []
    for name, argv in facts["analysis_commands"]:
        argv = list(argv)
        old_work = str(a.out / f"WORK_{pool}")
        i = argv.index("--results"); argv[i + 1] = argv[i + 1].replace(old_work, str(work), 1)
        j = argv.index("--out"); argv[j + 1] = str(ep_root / name)
        jobs.append((f"{pool}/{ep_root.name}/{name}", ep_root / name, argv))
    if with_contamination and (ROOT / "scripts_contamination.py").exists():
        jobs.append((f"{pool}/{ep_root.name}/contamination", ep_root / "contamination",
                     [sys.executable, str(ROOT / "scripts_contamination.py"), "--reference", str(work / "results" / "reference_item_outcomes.jsonl"),
                      "--pool", facts["pool_path"], "--out", str(ep_root / "contamination"), "--n-boot", str(a.n_boot)]))
    return jobs


THREAD_VARS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS")


def child_env(jobs: int) -> dict:
    """The inherited environment, as the runner passes it, with two additions (variables the user set are kept):
    PYTHONHASHSEED=0, because A iterates sets of designer keys while drawing from its seeded RNG (e.g. analysis.py
    self_rank_by_identity), so its Monte Carlo intervals change from process to process with Python's string-hash
    randomisation; a fixed hash seed makes the recomputed endpoints reproducible (the runner left it random and did not
    record it).  With --jobs > 1, cpu_count // jobs BLAS/OpenMP threads per analysis: N analyses each spinning a
    full-width BLAS pool thrash (synthetic trees: A 30 s alone, over 450 s with 6 in parallel)."""
    env = dict(os.environ)
    env.setdefault("PYTHONHASHSEED", "0")
    if jobs > 1:
        n = str(max(1, (os.cpu_count() or 1) // jobs))
        for v in THREAD_VARS:
            env.setdefault(v, n)
    return env


def run_job(label: str, out: Path, argv: list[str], a, timeout: Optional[float]) -> dict:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    t0 = time.time()
    proc = subprocess.Popen(argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=child_env(a.jobs))
    _cap_address_space(proc.pid, a.analysis_memory_mib)
    try:
        so, se = proc.communicate(timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:      # as the runner: a hung implementation is logged, not waited on
        proc.kill()
        so, se = proc.communicate()
        rc = "timeout"
    (out / "log.txt").write_text(f"rc={rc}\n--- stdout ---\n{so}\n--- stderr ---\n{se}")
    dt = time.time() - t0
    say(f"analysis {label}: rc={rc} in {dt:.0f}s")
    return {"label": label, "rc": rc, "seconds": round(dt)}


def run_all(jobs: list[tuple], a) -> dict[str, dict]:
    with cf.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        futs = {ex.submit(run_job, label, out, argv, a, None if label.endswith("contamination") else a.analysis_timeout): label
                for label, out, argv in jobs}
        return {futs[f]: f.result() for f in cf.as_completed(futs)}


def compare_endpoints(ep_root: Path, sealed_root: Path, names: list[str]) -> dict[str, dict]:
    out = {}
    for name in names:
        fn = "contamination.json" if name == "contamination" else "endpoints.json"
        x, y = _maybe_json(ep_root / name / fn), _maybe_json(sealed_root / name / fn)
        out[name] = {"status": "missing on one side"} if x is None or y is None else compare_json(x, y, ENV_KEYS)
    return out


def endpoint_line(label: str, v: dict) -> str:
    if v.get("status"):
        return f"{label}: {v['status']}"
    if v["differing"] == 0:
        return f"{label}: identical"
    return (f"{label}: {v['differing']} of {v['leaf_keys']} keys differ ({v['differing_run_environment']} run-environment keys: paths/timings; "
            f"{v['differing_beyond_rel_tol']} other keys beyond relative {v['rel_tol']:g})")


# ----------------------------------------------------------------------------------------------- 6. report

def render_impl(ep: Path, name: str) -> str:
    md, js = ep / "endpoints.md", ep / ("contamination.json" if name == "contamination" else "endpoints.json")
    if md.exists():
        return md.read_text()
    if js.exists():
        return f"`{js.name}` (verbatim):\n\n```json\n{js.read_text().rstrip()}\n```\n"
    return "No output file was written; see log.txt.\n"


def write_report(a, integrity: dict, facts: dict[str, dict], ctrl: Optional[dict], runs: dict[str, dict], ep_cmp: dict) -> Path:
    L = ["# MetaBench confirmatory report (mechanical assembly by scripts_unblind.py)", "",
         f"Written {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}. No interpretation: run facts, checks, then each frozen "
         "implementation's output verbatim.", "",
         "The math and factual endpoints were recomputed at unblinding from the per-session sealed files (DEVIATIONS 2026-10-29 17:45). "
         "The pool-level sealed paths held only the last pool sealed. The code endpoints were both sealed at run time and recomputed; both "
         "are compared below. Each pool's tree was rebuilt by scripts_unblind.py from sessions/, monitors/ and precompute/ with the "
         "runner's own code and checked against the plaintext registration in prereg/.", "",
         f"Arguments: --n-perm {a.n_perm} --n-boot {a.n_boot}; pools {', '.join(a.pools)}; results rows in registered order, then "
         "replacements (the runner's completion order was not recorded for factual and math).", "",
         f"Analysis environment: PYTHONHASHSEED={child_env(a.jobs)['PYTHONHASHSEED']} (A's interval draws depend on it; the runner left it "
         "random); run_manifest.json panel list-shaped for " + ", ".join(sorted(LIST_PANEL_POOLS)) + " as in that pool's run (C's documented "
         "fallback), dict-shaped otherwise.", "",
         "## Integrity", "",
         f"{integrity['manifest_entries']} MANIFEST entries; {integrity['ok']} present with the listed plaintext byte count; "
         f"{integrity['missing']} missing; {integrity['size_mismatch']} size mismatches; {integrity['unlisted_files']} decrypted files not "
         "listed in MANIFEST.", ""]
    for pool in a.pools:
        f = facts[pool]
        L += [f"## Pool: {pool}", "", "### Run facts (from the rebuilt tree)", "",
              "| fact | value |", "|---|---|",
              f"| sessions registered | {f['registered']} |", f"| replacements declared | {f['declared_replacements']} |",
              f"| benchmark rows (registered + replacements) | {f['rows']} |", f"| valid rows | {f['valid']} |",
              f"| valid registered sessions | {f['valid_registered']} |", f"| valid replacements | {f['valid_replacements']} |",
              f"| invalid rows by status | {canon(f['invalid_by_status'])} |", f"| monitor files | {f['monitor_files']} |",
              f"| item outcome rows | {f['item_outcome_rows']} |", f"| live_rescore_wait_s | {f['live_rescore_wait_s']} |",
              f"| precompute sha256 equals registered panel_correctness_sha256 | {f['precompute_hash_ok']} |",
              f"| precompute error last-rows by provider (excluded from reference scores) | {canon(f['precompute_error_last_rows_by_provider'])} |",
              f"| rebuild input files not listed in MANIFEST | {f['inputs_not_in_manifest']} |", "",
              "### Registration check", "", "Every registered session present once, replacements as declared, config hashes equal to the "
              "registered hashes (fatal otherwise). Per-session checks:", ""]
        L += [f"- {k}: {v}" for k, v in f["checks"].items()]
        L += [f"- WARNING {w}" for w in f["warnings"]] + [""]
        if pool == CONTROL_POOL and ctrl is not None:
            L += ["### Control: rebuilt code tree vs the sealed code pool-level files", ""]
            L += [f"- {control_line(k, v)}" for k, v in ctrl.items()] + [""]
            for variant, d in ep_cmp.items():
                L += [f"- endpoints ({variant}) vs sealed: " + "; ".join(endpoint_line(n, v) for n, v in d.items())]
            L += [""]
        L += ["### Analysis runs", ""]
        L += [f"- {lab}: rc={v['rc']} in {v['seconds']} s" for lab, v in sorted(runs.items()) if lab.startswith(f"{pool}/")] + [""]
        ep_root = a.out / pool / "endpoints"
        for name, _ in f["analysis_commands"]:
            L += [f"### {pool}: {name}", "", render_impl(ep_root / name, name), ""]
        L += [f"### {pool}: contamination", "", render_impl(ep_root / "contamination", "contamination"), ""]
        if pool == CONTROL_POOL and (a.unsealed / "endpoints").is_dir():
            L += [f"### {pool}: endpoints sealed at run time", ""]
            for name, _ in f["analysis_commands"]:
                L += [f"#### sealed {name}", "", render_impl(a.unsealed / "endpoints" / name, name), ""]
            L += ["#### sealed contamination", "", render_impl(a.unsealed / "endpoints" / "contamination", "contamination"), ""]
    p = a.out / "REPORT_CONFIRMATORY.md"
    p.write_text("\n".join(L) + "\n")
    return p


# ----------------------------------------------------------------------------------------------- main

def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--unsealed", required=True, type=Path, help="the decrypted mirror of run/sealed/ (with MANIFEST.json)")
    ap.add_argument("--prereg", required=True, type=Path, help="run/prereg (confirmatory_hashes_<pool>.json, confirmatory_replacements_<pool>.json)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--pools", default="factual,math,code")
    ap.add_argument("--n-perm", type=int, default=10000)
    ap.add_argument("--n-boot", type=int, default=10000)
    ap.add_argument("--jobs", type=int, default=1, help="analysis processes in parallel (A peaks near 11 GB each at full size)")
    ap.add_argument("--pool-file", action="append", default=[], help="name=path override of the pool file (tests)")
    ap.add_argument("--analysis-timeout", type=float, default=4 * 3600, help="seconds per analysis (runner default)")
    ap.add_argument("--analysis-memory-mib", type=int, default=20480, help="RLIMIT_AS per analysis on Linux (runner default; ignored on macOS)")
    ap.add_argument("--no-order-control", action="store_true", help="skip the code analyses on the sealed-row-order copy")
    ap.add_argument("--skip-analyses", action="store_true", help="rebuild and check only")
    a = ap.parse_args(argv)
    a.pools = [p for p in POOL_ORDER if p in a.pools.split(",")] + [p for p in a.pools.split(",") if p not in POOL_ORDER]
    a.pool_files = dict(POOL_FILES, **{k: str(Path(v).resolve()) for k, v in (kv.split("=", 1) for kv in a.pool_file)})
    a.unsealed, a.prereg, a.out = a.unsealed.resolve(), a.prereg.resolve(), a.out.resolve()
    return a


def main(argv=None) -> int:
    a = parse_args(argv)
    os.chdir(ROOT)                          # the runner's cwd: relative pool paths and every analysis subprocess
    a.out.mkdir(parents=True, exist_ok=True)
    integrity = check_integrity(a.unsealed)
    facts = {pool: rebuild_pool(pool, a) for pool in a.pools}
    ctrl, jobs, ep_cmp = None, [], {}
    if CONTROL_POOL in a.pools:
        ctrl = control_pool_files(a.out / f"WORK_{CONTROL_POOL}", a.unsealed)
        attribute_stale_copies(ctrl, a)
        for k, v in ctrl.items():
            say(control_line(k, v))
        ok, bad = control_ok(ctrl)
        if not ok:
            raise Fatal(f"control failed for {len(bad)} files: {', '.join(bad)}; no analysis was run")
    if a.skip_analyses:
        say("analyses skipped (--skip-analyses); no report written")
        return 0
    for pool in a.pools:
        jobs += analysis_jobs(pool, facts[pool], a.out / f"WORK_{pool}", a.out / pool / "endpoints", a)
    order_variant = CONTROL_POOL in a.pools and not a.no_order_control
    if order_variant:
        v = a.out / f"WORK_{CONTROL_POOL}_sealed_order"
        sealed_order_variant(a.out / f"WORK_{CONTROL_POOL}", a.unsealed, v)
        jobs += analysis_jobs(CONTROL_POOL, facts[CONTROL_POOL], v, a.out / CONTROL_POOL / "endpoints_sealed_order", a, with_contamination=False)
    runs = run_all(jobs, a)
    if CONTROL_POOL in a.pools and (a.unsealed / "endpoints").is_dir():
        names = [n for n, _ in facts[CONTROL_POOL]["analysis_commands"]]
        ep_cmp["registered row order"] = compare_endpoints(a.out / CONTROL_POOL / "endpoints", a.unsealed / "endpoints", names + ["contamination"])
        if order_variant:
            ep_cmp["sealed row order"] = compare_endpoints(a.out / CONTROL_POOL / "endpoints_sealed_order", a.unsealed / "endpoints", names)
        for variant, d in ep_cmp.items():
            for n, v in d.items():
                say(endpoint_line(f"control endpoints {n} ({variant}) vs sealed", v))
    p = write_report(a, integrity, facts, ctrl, runs, ep_cmp)
    (a.out / "unblind_summary.json").write_text(json.dumps({"integrity": integrity, "control": ctrl, "endpoint_control": ep_cmp,
                                                             "runs": runs, "facts": {k: {kk: vv for kk, vv in v.items() if kk != "analysis_commands"}
                                                                                     for k, v in facts.items()}}, indent=1, default=str))
    failed = [lab for lab, v in runs.items() if v["rc"] != 0]
    say(f"report written: {p} ({len(runs)} analysis runs, {len(failed)} with rc != 0)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
