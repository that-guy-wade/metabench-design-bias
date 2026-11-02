"""Host-side sandbox runner: executes a program against a test suite inside bwrap (no network, fresh tmpfs cwd,
ro system dirs), using the system /usr/bin/python3. One bwrap invocation per (program, suite)."""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRIVER = HERE / "sbx_driver.py"
BWRAP = "/usr/bin/bwrap"
TMPFS_BYTES = 256 * 1024 * 1024

SANDBOX_DESCRIPTION = (
    "bwrap --unshare-all --die-with-parent --ro-bind /usr /usr --ro-bind /lib /lib --ro-bind /lib64 /lib64 "
    "--ro-bind /bin /bin --proc /proc --dev /dev --tmpfs /tmp (256 MiB) --ro-bind <job dir> /src "
    "--dir /tmp/w --chdir /tmp/w /usr/bin/python3 -I /src/sbx_driver.py ...; the in-sandbox driver runs "
    "/usr/bin/python3 <solution> per test with stdin from the test input, wall-clock timeout "
    "max(2 s, 3 x time_limit), RLIMIT_AS = max(1 GiB, 2 x memory_limit), RLIMIT_FSIZE 32 MiB, no network, "
    "system Python 3.12.3."
)


def bwrap_cmd(job_dir: Path, args: list[str]) -> list[str]:
    cmd = [BWRAP, "--unshare-all", "--die-with-parent", "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib"]
    if os.path.exists("/lib64"):
        cmd += ["--ro-bind", "/lib64", "/lib64"]
    cmd += ["--ro-bind", "/bin", "/bin", "--proc", "/proc", "--dev", "/dev", "--size", str(TMPFS_BYTES),
            "--tmpfs", "/tmp", "--ro-bind", str(job_dir), "/src", "--dir", "/tmp/w", "--chdir", "/tmp/w",
            "--", "/usr/bin/python3", "-I", "/src/sbx_driver.py"] + args
    return cmd


def run_suite(program: str, tests: list[dict], timeout_s: float, mem_bytes: int, mode: str = "all") -> dict:
    """Return {"results": [...], "max_time": float, "n_pass": int, "n_run": int, "driver_error": str|None}."""
    job = Path(tempfile.mkdtemp(prefix="ccsbx_"))
    try:
        (job / "sol.py").write_text(program)
        (job / "tests.json").write_text(json.dumps(tests))
        shutil.copy(DRIVER, job / "sbx_driver.py")
        os.chmod(job, 0o755)
        for f in job.iterdir():
            os.chmod(f, 0o644)
        total = timeout_s * len(tests) + 60
        cmd = bwrap_cmd(job, ["/src/sol.py", "/src/tests.json", str(timeout_s), str(mem_bytes), mode])
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=total)
        except subprocess.TimeoutExpired:
            return {"results": [], "max_time": total, "n_pass": 0, "n_run": 0, "driver_error": "driver timeout"}
        if p.returncode != 0:
            return {"results": [], "max_time": 0.0, "n_pass": 0, "n_run": 0,
                    "driver_error": f"driver exit {p.returncode}: {p.stderr.decode('utf-8', 'replace')[-300:]}"}
        out = json.loads(p.stdout.decode())
        res = out["results"]
        return {"results": res, "max_time": out["max_time"], "n_pass": sum(r["status"] == "pass" for r in res),
                "n_run": len(res), "driver_error": None}
    finally:
        shutil.rmtree(job, ignore_errors=True)


EMPTY_PROGRAM = ""
WRONG_PROGRAM = "print(0)\n"
