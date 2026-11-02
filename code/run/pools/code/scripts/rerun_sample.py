"""Re-execute the reference solutions of 25 seeded-random pool items in the sandbox and assert they still pass
every stored test (and that the empty / print(0) programs still fail at least one). Usage: python -I rerun_sample.py [N]"""
from __future__ import annotations
import hashlib
import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sandbox  # noqa: E402

SEED = 20261025


def main(n: int = 25) -> int:
    items = [json.loads(l) for l in open(HERE.parent / "pool.jsonl")]
    sample = random.Random(SEED).sample(items, n)
    failures = []
    t0 = time.time()
    for it in sample:
        ev = it["verification"]["evidence"]
        timeout, mem = ev["timeout_s"], ev["memory_limit_bytes_sandbox"]
        assert hashlib.sha256(it["reference_solution"].encode()).hexdigest() == ev["solution_sha256"], it["id"]
        r = sandbox.run_suite(it["reference_solution"], it["tests"], timeout, mem, "all")
        e = sandbox.run_suite(sandbox.EMPTY_PROGRAM, it["tests"], timeout, mem, "all")
        w = sandbox.run_suite(sandbox.WRONG_PROGRAM, it["tests"], timeout, mem, "all")
        ok = (r["n_pass"] == len(it["tests"]) and e["n_pass"] < len(it["tests"]) and w["n_pass"] < len(it["tests"]))
        print(f"{it['id']} {it['source_id'][:40]!r:44} ref {r['n_pass']}/{len(it['tests'])} empty {e['n_pass']} "
              f"wrong {w['n_pass']} max_t {r['max_time']:.3f}s {'OK' if ok else 'FAIL'}", flush=True)
        if not ok:
            failures.append(it["id"])
    print(f"{n - len(failures)}/{n} items re-verified in {time.time() - t0:.0f}s; failures: {failures}")
    assert not failures, failures
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 25))
