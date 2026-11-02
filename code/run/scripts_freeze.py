"""Freeze the confirmatory code: write prereg/frozen_code.json with the sha256 of every file whose behaviour the
pre-registration commits to (runner, interface, arm logic, prompt templates, provider configs, pools when present,
both analysis implementations when present), and verify it (the runner refuses to start unless `verify` passes).

usage: scripts_freeze.py freeze [--note TEXT]
       scripts_freeze.py verify            # exit 0 iff every frozen hash matches and no frozen file is missing
Importable: freeze(root) -> dict, verify(root) -> (ok: bool, report: dict)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent

# Files whose bytes are frozen.  Globs are expanded at freeze time; missing optional entries are recorded as absent.
FROZEN_FILES = [
    "scripts_runner.py", "scripts_freeze.py", "scripts_health_view.py", "scripts_health_check.py",
    "metabench/llm.py", "metabench/pool.py", "metabench/panel.py", "metabench/arms.py", "metabench/interface.py",
    "metabench/designer.py", "metabench/briefs.py", "metabench/scoring.py", "metabench/monitors.py",
    "metabench/graders.py", "metabench/contamination.py", "scripts_contamination.py", "scripts_run_confirmatory.sh",
    "pools/code/scripts/sandbox.py", "pools/code/scripts/sbx_driver.py", "pools/factual_qa/scripts/verify.py",   # graders execute these
    "metabench/analysis.py",          # analysis implementation A (the original)
    "metabench/synthetic.py",
    "prereg/frozen_sizes.json", "prereg/sealing_key.json", "prereg/pools_hash.json",
]
FROZEN_GLOBS = [
    "pools/*.jsonl",                  # main-study pools (built by the pool author); hashed when present
    "pools/*.json",
    "pools/*/pool.jsonl",             # per-directory main-study pools (pools/<domain>/pool.jsonl)
    "analysis_impls/*/*.py",          # independent analysis implementations (two authors); hashed when present
    "analysis_impls/*/*.json",
]
FROZEN_PATH = "prereg/frozen_code.json"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def frozen_file_list(root: Path) -> tuple[list[str], list[str]]:
    """(present files, absent optional files), relative paths, sorted."""
    present, absent = [], []
    for rel in FROZEN_FILES:
        (present if (root / rel).exists() else absent).append(rel)
    for g in FROZEN_GLOBS:
        present += sorted(str(p.relative_to(root)) for p in root.glob(g) if p.is_file())
    return sorted(set(present)), sorted(absent)


def freeze(root: Path = ROOT, note: str = "", frozen_path: Optional[Path] = None) -> dict:
    present, absent = frozen_file_list(root)
    files = {rel: sha256_file(root / rel) for rel in present}
    combined = hashlib.sha256("".join(f"{k}:{v}\n" for k, v in sorted(files.items())).encode()).hexdigest()
    sys.path.insert(0, str(root))
    from metabench import panel
    panel.set_active("confirmatory")
    out = {"frozen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "note": note, "files": files,
           "absent_optional": absent, "combined_sha256": combined,
           "panel": [{"key": s.key, "provider": s.provider, "model_id": s.model_id, "effort": s.effort, "max_tokens": s.max_tokens, "role": s.note} for s in panel.PANEL],
           "displayed_keys": list(panel.DISPLAYED_KEYS), "placebo_keys": list(panel.PLACEBO_KEYS), "heldout_keys": list(panel.HELDOUT_KEYS),
           "tiers": dict(panel.TIERS)}
    (frozen_path or root / FROZEN_PATH).write_text(json.dumps(out, indent=1))
    return out


def verify(root: Path = ROOT, frozen_path: Optional[Path] = None) -> tuple[bool, dict]:
    p = frozen_path or root / FROZEN_PATH
    if not p.exists():
        return False, {"error": f"{FROZEN_PATH} missing"}
    frozen = json.loads(p.read_text())
    mismatched, missing = [], []
    for rel, h in frozen["files"].items():
        q = root / rel
        if not q.exists():
            missing.append(rel)
        elif sha256_file(q) != h:
            mismatched.append(rel)
    present, _ = frozen_file_list(root)
    unfrozen = [rel for rel in present if rel not in frozen["files"]]   # e.g. a pool or analysis impl added after freezing
    ok = not mismatched and not missing and not unfrozen
    return ok, {"frozen_at": frozen.get("frozen_at"), "combined_sha256": frozen.get("combined_sha256"),
                "n_files": len(frozen["files"]), "mismatched": mismatched, "missing": missing, "unfrozen": unfrozen}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["freeze", "verify"])
    ap.add_argument("--note", default="")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--frozen-path", default=None)
    a = ap.parse_args(argv)
    root = Path(a.root)
    fp = Path(a.frozen_path) if a.frozen_path else None
    if a.cmd == "freeze":
        out = freeze(root, a.note, fp)
        print(f"froze {len(out['files'])} files; combined_sha256={out['combined_sha256']}; absent optional: {out['absent_optional']}")
        return 0
    ok, rep = verify(root, fp)
    print(json.dumps(rep, indent=1))
    print("FROZEN CODE VERIFIED" if ok else "FROZEN CODE MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
