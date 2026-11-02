"""Blinded health view of a confirmatory WORK/ tree (docs/ARTEFACT_SCHEMA.md section 7, BLINDING.md section 4).

Reads results/session_log.jsonl, results/benchmarks.jsonl and the per-session files; writes
  - the view: one row per real session attempt plus decoys, shuffled, with secret designer / arm / evaluee codes and
    per-evaluee-shifted scores; nothing else;
  - the secret: the permutations, offsets, decoy ids, view-id -> session-id map and the seed that generated them.

CLI:  python scripts_health_view.py --work WORK --view health_view.jsonl --secret health_secret.json
          [--registered prereg/confirmatory_hashes.json] [--decoys-per-designer 3] [--decoy-sources rows.jsonl]
          [--code-hash-ok {true,false}]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metabench import panel  # noqa: E402
from metabench.arms import IDENTITY_ARMS  # noqa: E402

FROZEN_SIZES = Path(__file__).resolve().parent / "prereg" / "frozen_sizes.json"
SESSION_FILES = ["config", "actions", "transcript", "scores_views", "benchmark", "item_outcomes", "probes"]
SESSION_FILE_NAMES = {"config": "config.json", "actions": "actions.jsonl", "transcript": "transcript.jsonl",
                      "scores_views": "scores_views.jsonl", "benchmark": "benchmark.json",
                      "item_outcomes": "item_outcomes.jsonl", "probes": "probes.json"}
STRUCTURAL = ["status", "valid", "exit_code", "n_items", "n_llm_calls", "api_errors", "wall_s",
              "n_score_requests", "n_edits", "files", "parse"]
# the documented row, in this key order for every row (real or decoy)
ROW_KEYS = ["view_id", "designer_code", "arm_code", "identity_code", "status", "valid", "exit_code", "n_items",
            "n_llm_calls", "api_errors", "wall_s", "started_at", "ended_at", "n_score_requests", "n_edits", "files",
            "parse", "hash_ok", "code_hash_ok", "scores_shifted"]


def load_frozen_cells(path: Path = FROZEN_SIZES) -> dict[str, int]:
    """The 9 registered (info_arm, identity_arm) cells and their per-designer counts, in file order."""
    return dict(json.loads(Path(path).read_text())["sessions_per_designer_confirmatory"])


def parse_cell(name: str) -> tuple[str, str]:
    """'true_named_true' -> ('true_named', 'true'): the identity arm is the last underscore field."""
    info, identity = name.rsplit("_", 1)
    assert identity in IDENTITY_ARMS, name
    return info, identity


def panel_keys() -> list[str]:
    panel.set_active("confirmatory")
    return panel.all_panel_keys()


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _count_lines(path: Path) -> int:
    return sum(1 for line in path.read_text().splitlines() if line.strip()) if path.exists() else 0


def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _format_like(example: str, dt: datetime) -> str:
    """Render dt in the same ISO-8601 flavour as the real rows (Z suffix / offset, with or without microseconds)."""
    dt = dt.astimezone(timezone.utc)
    if "." not in example:
        dt = dt.replace(microsecond=0)
    out = dt.isoformat()
    return out.replace("+00:00", "Z") if example.endswith("Z") else out


def session_structure(work: Path, session_id: str) -> tuple[dict, dict]:
    """files / parse blocks computed from the actual per-session files."""
    sdir = work / "sessions" / session_id
    files = {k: (sdir / SESSION_FILE_NAMES[k]).exists() for k in SESSION_FILES}
    mon_path = work / "monitors" / f"{session_id}.json"
    verdicts: list = []
    n_monitors = 0
    if mon_path.exists():
        for m in json.loads(mon_path.read_text()).get("monitors", []):
            n_monitors += 1
            for part in ("artifact", "trace"):
                verdicts.append((m.get(part) or {}).get("evidence_score"))
    files["monitors"] = n_monitors
    actions = _read_jsonl(sdir / "actions.jsonl")
    ok = [not str(a.get("result_summary", "")).startswith("ERROR") for a in actions]
    json_ok = [isinstance(v, int) and not isinstance(v, bool) for v in verdicts]
    parse = {"actions_ok_rate": (sum(ok) / len(ok)) if ok else 0.0,
             "monitor_json_rate": (sum(json_ok) / len(json_ok)) if json_ok else 0.0,
             "item_outcomes_rows": _count_lines(sdir / "item_outcomes.jsonl")}
    return files, parse


def _exit_code(row: dict) -> int:
    if "exit_code" in row:
        return int(row["exit_code"])
    return 0 if row.get("valid") else (2 if str(row.get("status", "")).startswith("exception") else 1)


def build_health_view(work_dir: Path, out_view: Path, out_secret: Path, *, run_seed_bytes: bytes | None = None,
                      registered: dict | None = None, decoys_per_designer: int = 3,
                      decoy_sources: list[dict] | None = None, code_hash_ok: bool = True,
                      hash_ok_by_session: dict[str, bool] | None = None) -> dict:
    work = Path(work_dir)
    seed = os.urandom(32) if run_seed_bytes is None else bytes(run_seed_bytes)
    rng = np.random.default_rng(int.from_bytes(seed, "big"))
    keys = panel_keys()
    cells = [parse_cell(c) for c in load_frozen_cells()]
    log = _read_jsonl(work / "results" / "session_log.jsonl")
    bench = {b["session_id"]: b for b in _read_jsonl(work / "results" / "benchmarks.jsonl")}
    registered_hash = {s["session_id"]: s["config_hash"] for s in (registered or {}).get("sessions", [])}
    hash_ok_by_session = hash_ok_by_session or {}

    # --- secrets: three permutations and the per-evaluee offsets, all from the run seed, in a fixed draw order ---
    designers = sorted({r["designer"] for r in log})
    designer_perm = {d: f"D{i + 1:02d}" for d, i in zip(designers, rng.permutation(len(designers)))}
    identity_perm = {a: f"I{i + 1}" for a, i in zip(IDENTITY_ARMS, rng.permutation(len(IDENTITY_ARMS)))}
    cell_perm = {f"{info}_{ident}": {"arm_code": f"A{i + 1}", "identity_code": identity_perm[ident]}
                 for (info, ident), i in zip(cells, rng.permutation(len(cells)))}
    evaluee_perm = {k: f"E{i + 1:02d}" for k, i in zip(keys, rng.permutation(len(keys)))}
    offsets = {k: float(v) for k, v in zip(keys, rng.uniform(-0.25, 0.25, size=len(keys)))}

    def shifted(scores: dict | None) -> dict:
        scores = scores or {}
        return {evaluee_perm[k]: (scores[k] + offsets[k] if k in scores else None) for k in keys}

    # --- real rows ---
    real: list[tuple[str, dict]] = []
    for r in log:
        sid = r["session_id"]
        b = bench.get(sid, {})
        cell = f"{r['info_arm']}_{r['identity_arm']}"
        if cell not in cell_perm:
            raise ValueError(f"session {sid} is in an unregistered cell {cell}")
        files, parse = session_structure(work, sid)
        if sid in hash_ok_by_session:
            hash_ok = bool(hash_ok_by_session[sid])
        elif registered is not None:
            hash_ok = sid in registered_hash and registered_hash[sid] == b.get("config_hash")
        else:
            hash_ok = True
        real.append((sid, {
            "designer_code": designer_perm[r["designer"]], **cell_perm[cell],
            "status": r["status"], "valid": bool(r["valid"]), "exit_code": _exit_code(r),
            "n_items": int(r["n_items"]), "n_llm_calls": int(r["n_llm_calls"]), "api_errors": int(r["api_errors"]),
            "wall_s": float(r["wall_s"]), "started_at": r["started_at"], "ended_at": r["ended_at"],
            "n_score_requests": int(b.get("n_score_requests", 0)), "n_edits": int(b.get("n_edits", 0)),
            "files": files, "parse": parse, "hash_ok": hash_ok, "code_hash_ok": bool(code_hash_ok),
            "scores_shifted": shifted(b.get("produced_scores")),
        }))

    # --- decoys: decoys_per_designer per designer code, spread evenly over the 9 cells ---
    n_dec = decoys_per_designer * len(designers)
    dec_cells = [cells[i % len(cells)] for i in range(n_dec)]
    dec_cells = [dec_cells[i] for i in rng.permutation(n_dec)]
    per_key = {k: [bench[s]["produced_scores"][k] for s, _ in real
                   if s in bench and k in (bench[s].get("produced_scores") or {})] for k in keys}
    ref_like = {k: float(np.mean(v)) for k, v in per_key.items() if v}
    starts = [_parse_dt(row["started_at"]) for _, row in real]
    t0, t1 = (min(starts), max(starts)) if starts else (datetime.now(timezone.utc),) * 2
    example = real[0][1]["started_at"] if real else "1970-01-01T00:00:00Z"
    decoys = []
    for i in range(n_dec):
        if decoy_sources:
            src = decoy_sources[int(rng.integers(len(decoy_sources)))]
        else:
            src = real[int(rng.integers(len(real)))][1]
        start = t0 + timedelta(seconds=float(rng.uniform(0.0, (t1 - t0).total_seconds())))
        info, ident = dec_cells[i]
        row = {"designer_code": f"D{i // decoys_per_designer + 1:02d}", **cell_perm[f"{info}_{ident}"]}
        for f in STRUCTURAL:
            row[f] = _exit_code(src) if f == "exit_code" else json.loads(json.dumps(src[f]))
        row["started_at"] = _format_like(example, start)
        row["ended_at"] = _format_like(example, start + timedelta(seconds=row["wall_s"]))
        row["hash_ok"] = True
        row["code_hash_ok"] = bool(code_hash_ok)
        if "scores_shifted" in src:   # resampled real row: follow its score presence
            has_scores = any(v is not None for v in src["scores_shifted"].values())
        else:                         # explicit structural source: optional flag, default present
            has_scores = bool(src.get("scores_present", True))
        noise = rng.normal(0.0, 0.02, size=len(keys))
        row["scores_shifted"] = {evaluee_perm[k]: (ref_like[k] + float(noise[j]) + offsets[k]
                                                   if has_scores and k in ref_like else None)
                                 for j, k in enumerate(keys)}
        decoys.append(row)

    # --- shuffle, assign view ids, write ---
    rows = [(sid, row) for sid, row in real] + [(None, row) for row in decoys]
    order = rng.permutation(len(rows))
    view_rows, view_to_session, decoy_ids = [], {}, []
    for n, idx in enumerate(order, start=1):
        sid, row = rows[idx]
        vid = f"HV-{n:04d}"
        row["view_id"] = vid
        view_rows.append({k: row[k] for k in ROW_KEYS})
        if sid is None:
            decoy_ids.append(vid)
        else:
            view_to_session[vid] = sid
    out_view, out_secret = Path(out_view), Path(out_secret)
    out_view.parent.mkdir(parents=True, exist_ok=True)
    out_secret.parent.mkdir(parents=True, exist_ok=True)
    out_view.write_text("".join(json.dumps(r) + "\n" for r in view_rows))
    out_secret.write_text(json.dumps({"designer_perm": designer_perm, "cell_perm": cell_perm, "evaluee_perm": evaluee_perm,
                                      "offsets": offsets, "decoy_view_ids": decoy_ids,
                                      "view_id_to_session_id": view_to_session, "seed_hex": seed.hex()}, indent=1))
    return {"n_real": len(real), "n_decoys": len(decoys), "n_rows": len(view_rows),
            "n_designers": len(designers), "n_cells": len(cells)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--view", required=True, type=Path)
    ap.add_argument("--secret", required=True, type=Path)
    ap.add_argument("--registered", type=Path, default=None, help="prereg/confirmatory_hashes.json (sets hash_ok)")
    ap.add_argument("--decoys-per-designer", type=int, default=3)
    ap.add_argument("--decoy-sources", type=Path, default=None, help="jsonl of structural rows to replay as decoys")
    ap.add_argument("--code-hash-ok", choices=["true", "false"], default="true")
    a = ap.parse_args(argv)
    registered = json.loads(a.registered.read_text()) if a.registered else None
    sources = _read_jsonl(a.decoy_sources) if a.decoy_sources else None
    summary = build_health_view(a.work, a.view, a.secret, registered=registered, decoys_per_designer=a.decoys_per_designer,
                                decoy_sources=sources, code_hash_ok=a.code_hash_ok == "true")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
