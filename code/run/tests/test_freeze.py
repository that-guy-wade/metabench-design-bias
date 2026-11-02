"""scripts_freeze: freeze writes hashes for the frozen file set; verify fails on any modification, missing file or
unfrozen pool/analysis file added after freezing."""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scripts_freeze as F  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _mini_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "metabench").mkdir(parents=True)
    (root / "prereg").mkdir()
    for rel in F.FROZEN_FILES:
        src = ROOT / rel
        if src.exists():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, root / rel)
    return root


def test_freeze_then_verify_ok(tmp_path):
    root = _mini_root(tmp_path)
    out = F.freeze(root, "test")
    assert "scripts_runner.py" in out["files"] and "metabench/arms.py" in out["files"]
    assert "pool.jsonl" not in json.dumps(out["files"])  # no pool item file hashed while none is present (the sandbox scripts are frozen files)
    ok, rep = F.verify(root)
    assert ok, rep
    assert rep["combined_sha256"] == out["combined_sha256"]


def test_verify_fails_on_modification_missing_and_unfrozen(tmp_path):
    root = _mini_root(tmp_path)
    F.freeze(root)
    # modification of arm logic
    p = root / "metabench/arms.py"
    p.write_text(p.read_text() + "\n# tampered\n")
    ok, rep = F.verify(root)
    assert not ok and rep["mismatched"] == ["metabench/arms.py"]
    F.freeze(root)
    # missing frozen file
    (root / "metabench/briefs.py").unlink()
    ok, rep = F.verify(root)
    assert not ok and "metabench/briefs.py" in rep["missing"]
    # a pool added after freezing is reported as unfrozen
    shutil.copy(root / "metabench/arms.py", root / "metabench/briefs.py")
    F.freeze(root)
    (root / "pools").mkdir(exist_ok=True)
    (root / "pools/math.jsonl").write_text('{"id": "P0001"}\n')
    ok, rep = F.verify(root)
    assert not ok and rep["unfrozen"] == ["pools/math.jsonl"]
    F.freeze(root)
    ok, rep = F.verify(root)
    assert ok and "pools/math.jsonl" in json.loads((root / "prereg/frozen_code.json").read_text())["files"]


def test_verify_missing_frozen_file(tmp_path):
    root = _mini_root(tmp_path)
    ok, rep = F.verify(root)
    assert not ok and "missing" in rep["error"]
