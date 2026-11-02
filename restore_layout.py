#!/usr/bin/env python3
"""Restore the original working layout from this release package, so the frozen code and the
exploratory scripts run unchanged.

    python restore_layout.py --root /some/empty/dir

Creates
    ROOT/run/                    frozen code, tests, pool build code, protocol files, prereg/
    ROOT/run/pools/<pool>/       pool.jsonl for factual_qa and code (math: rebuild, see LICENSES_AND_SOURCES.md)
    ROOT/unblinded/WORK_<pool>/  results/, sessions/, monitors/, precompute/, registration_full.json, run_manifest.json
    ROOT/unblinded/<pool>/       endpoints/ (and endpoints_sealed_order/ for code)
    ROOT/analysis/<name>/        exploratory scripts next to their data

and rewrites the placeholder root "/path/to/metabench" in the restored .py/.sh files to ROOT.
"""
import argparse
import gzip
import shutil
import tarfile
from pathlib import Path

PKG = Path(__file__).resolve().parent
PLACEHOLDER = "/path/to/metabench"
POOL_DIR = {"factual": "factual_qa", "math": "math", "code": "code"}


def copy(src: Path, dst: Path):
    """Copy a file or tree, expanding *.tar.gz (into dst's parent) and *.gz files."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        for p in sorted(src.iterdir()):
            copy(p, dst / p.name)
    elif src.name.endswith(".tar.gz"):
        with tarfile.open(src) as tf:
            tf.extractall(dst.parent, filter="data")
    elif src.name.endswith(".gz"):
        with gzip.open(src, "rb") as fi, open(dst.with_name(src.name[:-3]), "wb") as fo:
            shutil.copyfileobj(fi, fo)
    else:
        shutil.copy2(src, dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    root = ap.parse_args().root.resolve()
    run = root / "run"
    copy(PKG / "code/run", run)
    for f in (PKG / "protocol").glob("*.md"):
        copy(f, run / ("prereg" if f.name == "DEVIATIONS.md" else "") / f.name)
    copy(PKG / "protocol/prereg", run / "prereg")
    copy(PKG / "data/ARTEFACT_SCHEMA.md", run / "docs/ARTEFACT_SCHEMA.md")
    for pool, pdir in POOL_DIR.items():
        src = PKG / "data/confirmatory" / pool
        work = root / "unblinded" / f"WORK_{pool}"
        for name in ("results", "precompute", "registration_full.json", "run_manifest.json",
                     "sessions.tar.gz", "monitors.tar.gz"):
            copy(src / name, work / name)
        shutil.copy2(work / "results/reference_item_outcomes.jsonl", work / "reference_item_outcomes.jsonl")
        for name in ("endpoints", "endpoints_sealed_order"):
            if (src / name).exists():
                copy(src / name, root / "unblinded" / pool / name)
        for name in ("pool.jsonl.gz", "pool.jsonl", "pool_index.jsonl"):
            if (src / "pool" / name).exists():
                copy(src / "pool" / name, run / "pools" / pdir / name)
    copy(PKG / "reports/REPORT_CONFIRMATORY.md", root / "unblinded/REPORT_CONFIRMATORY.md")
    for d in sorted((PKG / "code/exploratory").iterdir()):
        copy(d, root / "analysis" / d.name)
    for d in sorted((PKG / "data/exploratory").iterdir()):
        copy(d, root / "analysis" / d.name)
    n = 0
    for f in list(root.rglob("*.py")) + list(root.rglob("*.sh")):
        t = f.read_text()
        if PLACEHOLDER in t:
            f.write_text(t.replace(PLACEHOLDER, str(root)))
            n += 1
    print(f"restored into {root}; placeholder root rewritten in {n} scripts")
    if not (run / "pools/math/pool.jsonl").exists():
        print("note: run/pools/math/pool.jsonl is not distributed; rebuild it with run/pools/math/scripts "
              "(see LICENSES_AND_SOURCES.md) before running anything that needs math item text")


if __name__ == "__main__":
    main()
