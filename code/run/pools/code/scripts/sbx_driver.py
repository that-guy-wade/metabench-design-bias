"""In-sandbox driver (runs INSIDE bwrap with the system python3). Stdlib only; no host imports.

Usage: python3 -I sbx_driver.py SOLUTION TESTS_JSON TIMEOUT_S MEM_BYTES MODE
MODE = "all" (run every test) or "stop" (stop at the first non-pass).
Reads tests [{"input","output"}] and prints one JSON object to stdout:
  {"results": [{"status": pass|fail|timeout|error, "time": float, "exit": int|null}], "max_time": float}
Comparison: whitespace tokens; integer-looking tokens exact; tokens that both parse as finite floats
compared with abs/rel tolerance 1e-6; everything else exact (case-sensitive).
"""
import json
import math
import os
import re
import resource
import signal
import subprocess
import sys
import time

INT_RE = re.compile(r"[+-]?\d+")
TOL = 1e-6
MAX_OUT = 8 * 1024 * 1024


def tokens_match(expected: str, actual: str) -> bool:
    e, a = expected.split(), actual.split()
    if len(e) != len(a):
        return False
    for x, y in zip(e, a):
        if x == y:
            continue
        if INT_RE.fullmatch(x) and INT_RE.fullmatch(y):
            if int(x) != int(y):
                return False
            continue
        try:
            fx, fy = float(x), float(y)
        except ValueError:
            return False
        if not (math.isfinite(fx) and math.isfinite(fy)):
            return False
        if abs(fx - fy) > TOL * max(1.0, abs(fx), abs(fy)):
            return False
    return True


def _limits(mem_bytes):
    def pre():
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUT * 4, MAX_OUT * 4))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.setsid()
    return pre


def run_one(sol, inp, expected, timeout, mem_bytes, idx):
    out_path = f"out_{idx}.txt"
    t0 = time.monotonic()
    with open(out_path, "wb") as out, open(os.devnull, "wb") as devnull:
        p = subprocess.Popen(["/usr/bin/python3", sol], stdin=subprocess.PIPE, stdout=out, stderr=devnull,
                             preexec_fn=_limits(mem_bytes))
        try:
            p.communicate(inp.encode(), timeout=timeout)
            status = None
        except subprocess.TimeoutExpired:
            status = "timeout"
        except BrokenPipeError:
            status = None
            p.wait(timeout=timeout)
        if status == "timeout":
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait()
    dt = time.monotonic() - t0
    if status == "timeout":
        return {"status": "timeout", "time": dt, "exit": None}
    if p.returncode != 0:
        return {"status": "error", "time": dt, "exit": p.returncode}
    if os.path.getsize(out_path) > MAX_OUT:
        return {"status": "fail", "time": dt, "exit": 0}
    with open(out_path, "rb") as f:
        actual = f.read().decode("utf-8", "replace")
    os.unlink(out_path)
    ok = tokens_match(expected, actual)
    return {"status": "pass" if ok else "fail", "time": dt, "exit": 0}


def main():
    sol, tests_path, timeout, mem_bytes, mode = sys.argv[1:6]
    timeout, mem_bytes = float(timeout), int(mem_bytes)
    with open(tests_path) as f:
        tests = json.load(f)
    results = []
    for i, t in enumerate(tests):
        r = run_one(sol, t["input"], t["output"], timeout, mem_bytes, i)
        results.append(r)
        if mode == "stop" and r["status"] != "pass":
            break
    print(json.dumps({"results": results, "max_time": max([r["time"] for r in results], default=0.0)}))


if __name__ == "__main__":
    main()
