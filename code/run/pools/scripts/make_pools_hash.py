"""Write prereg/pools_hash.json: sha256 of every pool file, PROVENANCE.md, schema files and build scripts."""
import hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
POOLS = ROOT / "pools"
out = {"written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "files": {}, "pools": {}}
def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()
for p in sorted(POOLS.rglob("*")):
    if not p.is_file() or "_work" in p.parts or "__pycache__" in p.parts or ".pytest_cache" in p.parts:
        continue
    out["files"][str(p.relative_to(ROOT))] = {"sha256": sha(p), "bytes": p.stat().st_size}
for d in sorted(POOLS.iterdir()):
    if d.is_dir() and (d / "pool.jsonl").exists():
        n = sum(1 for line in open(d / "pool.jsonl") if line.strip())
        out["pools"][d.name] = {"pool_jsonl_sha256": sha(d / "pool.jsonl"), "n_items": n,
                               "provenance_sha256": sha(d / "PROVENANCE.md") if (d / "PROVENANCE.md").exists() else None}
(ROOT / "prereg" / "pools_hash.json").write_text(json.dumps(out, indent=1) + "\n")
print(json.dumps(out["pools"], indent=1))
