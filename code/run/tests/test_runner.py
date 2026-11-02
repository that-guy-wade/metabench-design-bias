"""scripts_runner offline tests with a scripted fake LLM: refusal without frozen code, keyring checks, interleaved
plan, one-time replacement, sealing to the registered key (not decryptable here), stdout free of scores."""
import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import scripts_freeze as F  # noqa: E402
import scripts_runner as R  # noqa: E402
from metabench import panel  # noqa: E402
from metabench.llm import LLMResponse, ToolCall  # noqa: E402

DESIGNERS = ["gemini38flash", "grok43"]


class FakeLLM:
    """Scripted designer + evaluee + monitor.  Designer: add_items(n) then submit; sessions whose id contains
    'r1' (and are not replacements) submit one item short -> invalid, so the replacement rule is exercised."""

    def __init__(self, n_items: int, pool_ids: list[str]):
        self.n_items = n_items
        self.pool_ids = pool_ids
        self.totals = {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "errors": 0}
        self.by_tag: dict = {}
        self.steps: dict = {}
        import random
        self.rng = random.Random(0)

    def _resp(self, text="", calls=None, provider="google", model_id="fake"):
        self.totals["calls"] += 1
        return LLMResponse(text=text, tool_calls=calls or [], stop_reason="tool_use" if calls else "end_turn", in_tokens=10, out_tokens=5,
                           latency=0.01, raw_assistant_message={"role": "assistant", "content": text}, provider=provider, model_id=model_id)

    def _bind_loop(self):
        # a loop-bound resource (like the providers' async HTTP clients and locks): use from another loop raises
        if not hasattr(self, "_loop"):
            self._loop = asyncio.get_running_loop()
        if asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("client bound to a different (closed) event loop")

    async def chat(self, spec, system, messages, tools=None, max_tokens=None, tag="", temperature=None, max_attempts=7):
        self._bind_loop()
        if tag.startswith("panel:"):
            letter = "A" if self.rng.random() < (0.3 + 0.04 * (hash(spec.key) % 10)) else "B"
            return self._resp(text=f"Reasoning. Answer: {letter}", provider=spec.provider, model_id=spec.model_id)
        return self._resp(text='{"evidence_score": 7, "favoured_label": null, "disfavoured_label": null, "rationale": "none", "steering_actions": []}',
                          provider=spec.provider, model_id=spec.model_id)

    async def chat_conv(self, spec, system, conv, tools=None, max_tokens=None, tag="", max_attempts=7):
        self._bind_loop()
        sid = tag.split(":", 1)[1]
        k = self.steps[sid] = self.steps.get(sid, 0) + 1
        bt = self.by_tag.setdefault(tag, {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "errors": 0})
        bt["calls"] += 1
        if tag.startswith("probe:"):
            return self._resp(text="MDL-01, MDL-02, MDL-03. Ordinary work.", provider=spec.provider, model_id=spec.model_id)
        short = ("_r1" in sid) and not sid.endswith("_rep1")
        if k == 1:
            n = self.n_items - (1 if short else 0)
            return self._resp(calls=[ToolCall("c1", "add_items", {"ids": self.pool_ids[:n]})], provider=spec.provider, model_id=spec.model_id)
        if k == 2:
            return self._resp(calls=[ToolCall("c2", "request_panel_scores", {})], provider=spec.provider, model_id=spec.model_id)
        if k == 3:
            return self._resp(calls=[ToolCall("c3", "submit", {"final_notes": "done"})], provider=spec.provider, model_id=spec.model_id)
        # after an invalid submit the runner's correction prompt gets no further tool calls -> stays invalid
        return self._resp(text="(no further changes)", provider=spec.provider, model_id=spec.model_id)


def _pool(tmp_path: Path, n=40) -> Path:
    p = tmp_path / "pool.jsonl"
    with open(p, "w") as f:
        for i in range(n):
            f.write(json.dumps({"id": f"S{i+1:04d}", "source": "synthetic", "source_id": i, "category": ["alpha", "beta", "gamma"][i % 3],
                                "question": f"Question {i}?", "options": ["one", "two", "three", "four"], "answer": "A", "answer_index": 0, "src": "t",
                                "source_date": f"20{15 + i % 12:02d}-06-01", "post_cutoff": False,
                                "post_cutoff_by_developer": {"anthropic": False, "openai": i % 12 >= 11, "google": i % 12 >= 10, "xai": False}}) + "\n")
    return p


def _args(tmp_path: Path, pool: Path, cmd: str, **kw):
    argv = [cmd, "--pool", str(pool), "--pool-name", "smoke", "--samples", "1", "--n-items", "8", "--k-rounds", "1",
            "--designers", ",".join(DESIGNERS), "--cells", "sham:blinded:2,true_named:true:1", "--concurrency", "4",
            "--work-dir", str(tmp_path / "work"), "--sealed-dir", str(tmp_path / "sealed"), "--prereg-dir", str(tmp_path / "prereg"),
            "--health-dir", str(tmp_path / "health"), "--frozen-code", str(tmp_path / "prereg" / "frozen_code.json"),
            "--pilot-sessions-dir", str(tmp_path / "no_pilot"), "--allow-non-tmpfs", "--n-perm", "50", "--n-boot", "20", "--keep-work"]
    for k, v in kw.items():
        argv += [f"--{k.replace('_', '-')}"] + ([] if v is True else [str(v)])
    return argv


def _runner(tmp_path, pool, cmd, llm=None, **kw):
    """`llm` is a factory kwargs-less callable returning a fresh fake per command (as the real runner builds a fresh
    client set per asyncio.run), or a single fake object (reused: a cross-loop reuse then raises in the fake)."""
    r = R.Runner(R.build_parser().parse_args(_args(tmp_path, pool, cmd, **kw)))
    if llm is not None:
        r.llm_factory = llm if callable(llm) else (lambda: llm)
    return r


def test_run_refuses_without_frozen_code(tmp_path):
    pool = _pool(tmp_path)
    (tmp_path / "prereg").mkdir()
    r = _runner(tmp_path, pool, "run")
    with pytest.raises(SystemExit, match="frozen code"):
        r.cmd_run()


def test_sealer_refuses_secret_key(tmp_path):
    home = tmp_path / "gnupg"; home.mkdir(mode=0o700)
    env = {**os.environ, "GNUPGHOME": str(home)}
    subprocess.run(["gpg", "--batch", "--quiet", "--passphrase", "", "--pinentry-mode", "loopback", "--quick-gen-key", "test <t@example.com>", "ed25519", "cert,sign", "0"],
                   env=env, check=True, capture_output=True)
    fpr = [l.split(":")[9] for l in subprocess.run(["gpg", "--batch", "--list-keys", "--with-colons"], env=env, capture_output=True, text=True).stdout.splitlines() if l.startswith("fpr:")][0]
    kf = tmp_path / "key.json"; kf.write_text(json.dumps({"unblinding_key_fingerprint": fpr}))
    s = R.Sealer(sealed_dir=tmp_path / "sealed", gnupghome=home, key_file=kf)
    with pytest.raises(SystemExit, match="SECRET key"):
        s.check_keyring()
    # and the real keyring: public key only, registered fingerprint present
    R.Sealer(sealed_dir=tmp_path / "sealed2").check_keyring()


def test_plan_is_interleaved_and_complete():
    plan = R.build_plan(["a", "b", "c"], {"sham_blinded": 2, "none_blinded": 2, "inverted_blinded": 1}, "p")
    assert len(plan) == 3 * 5
    ids = [p["session_id"] for p in plan]
    assert len(set(ids)) == len(ids)
    # replicate-major: every replicate-0 session precedes every replicate-1 session
    reps = [p["replicate"] for p in plan]
    assert reps == sorted(reps)
    # within the first block, designers and arms are not run in contiguous runs
    first = plan[:9]
    assert len({p["designer"] for p in first[:3]}) > 1 or len({p["info_arm"] for p in first[:3]}) > 1
    assert build_plan_is_deterministic(plan)


def build_plan_is_deterministic(plan):
    return plan == R.build_plan(["a", "b", "c"], {"sham_blinded": 2, "none_blinded": 2, "inverted_blinded": 1}, "p")


def test_full_path_fake_llm(tmp_path, capsys):
    pytest.importorskip("scripts_health_view")
    pool = _pool(tmp_path)
    (tmp_path / "prereg").mkdir()
    pool_ids = [json.loads(l)["id"] for l in open(pool)]
    made = []

    def factory():
        made.append(FakeLLM(n_items=8, pool_ids=pool_ids))
        return made[-1]

    F.freeze(ROOT, "test", tmp_path / "prereg" / "frozen_code.json")
    r = _runner(tmp_path, pool, "all", llm=factory)
    r.cmd_precompute()
    r.cmd_register()
    reg = json.loads((tmp_path / "prereg" / "confirmatory_hashes_smoke.json").read_text())
    assert len(reg["sessions"]) == len(DESIGNERS) * 3
    assert all(set(s) == {"session_id", "designer", "info_arm", "identity_arm", "replicate", "config_hash"} for s in reg["sessions"])
    assert "reference_scores" not in json.dumps(reg) and "displayed_order" not in json.dumps(reg) and "offsets" not in json.dumps(reg)
    r.cmd_run()
    assert len(made) == 2          # a fresh client set for precompute and for run (each asyncio.run is its own loop)
    out = capsys.readouterr().out
    # stdout: session ids, exit codes, validity, api errors, timings only -> no percentages / score-like decimals
    assert "produced" not in out and "MDL-" not in out
    assert not re.search(r"\b0\.\d{3,}\b", out), out
    work = tmp_path / "work"
    rows = [json.loads(l) for l in open(work / "results" / "benchmarks.jsonl")]
    # 6 registered + replacements for the two invalid r1 sham sessions
    invalid = [x for x in rows if not x["valid"] and x["replacement_of"] is None]
    reps = [x for x in rows if x["replacement_of"]]
    assert len(invalid) == 2 and len(reps) == 2 and all(x["valid"] for x in reps)
    assert all(x["session_id"].endswith("_rep1") for x in reps)
    assert not any(x["session_id"].endswith("_rep1_rep1") for x in rows)
    repl = json.loads((tmp_path / "prereg" / "confirmatory_replacements_smoke.json").read_text())
    assert len(repl["replacements"]) == 2
    # sealing: every work file sealed, ciphertext not decryptable here, manifest complete
    sealed = tmp_path / "sealed"
    for p in work.rglob("*"):
        if p.is_file():
            assert (sealed / (str(p.relative_to(work)) + ".gpg")).exists(), p
    man = json.loads((sealed / "MANIFEST.json").read_text())
    assert len(man["files"]) >= sum(1 for p in work.rglob("*") if p.is_file())
    one = next(sealed.rglob("benchmark.json.gpg"))
    dec = subprocess.run(["gpg", "--batch", "--decrypt", str(one)], env={**os.environ, "GNUPGHOME": str(ROOT / "sealing" / "gnupg")}, capture_output=True, text=True)
    assert dec.returncode != 0 and "produced_scores" not in dec.stdout
    assert b"produced_scores" not in one.read_bytes()
    # health view written in plaintext outside the sealed tree, secret only inside work (sealed)
    hv = tmp_path / "health" / "health_view_smoke.jsonl"
    assert hv.exists() and (work / "health" / "health_secret.json").exists()
    vrows = [json.loads(l) for l in open(hv)]
    assert len(vrows) > len(rows)
    assert not any(k in vrows[0] for k in ("session_id", "designer", "info_arm", "label_map"))
    # monitors ran for valid sessions with two developers each
    mons = [json.loads(l) for l in open(work / "results" / "monitors.jsonl")]
    assert all(len(m["monitors"]) == 2 for m in mons)
    assert all(m["monitor_developers"][0] != m["monitor_developers"][1] for m in mons)
    # endpoints from analysis implementation A exist (sealed), log not printed
    assert (work / "endpoints" / "A_metabench_analysis" / "log.txt").exists()
    assert "Psi" not in out
    # contamination check ran on the reference outcomes after the sessions, its output is sealed with the endpoints and
    # nothing but rc/timing reached stdout
    cj = work / "endpoints" / "contamination" / "contamination.json"
    assert cj.exists() and (sealed / "endpoints" / "contamination" / "contamination.json.gpg").exists()
    assert "contamination: rc=0" in out and "flag" not in out.lower()


def test_run_refuses_on_config_mismatch(tmp_path):
    pytest.importorskip("scripts_health_view")
    pool = _pool(tmp_path)
    (tmp_path / "prereg").mkdir()
    pool_ids = [json.loads(l)["id"] for l in open(pool)]
    fake = FakeLLM(n_items=8, pool_ids=pool_ids)
    F.freeze(ROOT, "test", tmp_path / "prereg" / "frozen_code.json")
    r = _runner(tmp_path, pool, "all", llm=fake)
    r.cmd_precompute(); r.cmd_register()
    regp = tmp_path / "prereg" / "confirmatory_hashes_smoke.json"
    reg = json.loads(regp.read_text()); reg["sessions"][0]["config_hash"] = "0" * 64; regp.write_text(json.dumps(reg))
    with pytest.raises(SystemExit, match="registered commitments"):
        r.cmd_run()


def test_substitute_infers_provider():
    assert [R.infer_provider(m) for m in ("gpt-5.4-mini", "claude-sonnet-5-5", "gemini-3.5-flash", "grok-4.3")] == ["openai", "anthropic", "google", "xai"]
    with pytest.raises(SystemExit):
        R.infer_provider("llama-9")


def test_all_command_does_not_reuse_one_client_across_event_loops(tmp_path):
    """Regression (smoke attempt 4): precompute and run are separate asyncio.run loops; a client object shared across
    them raises once its locks are contended in the second loop. The fake raises on any cross-loop use."""
    pytest.importorskip("scripts_health_view")
    pool = _pool(tmp_path)
    (tmp_path / "prereg").mkdir()
    pool_ids = [json.loads(l)["id"] for l in open(pool)]
    F.freeze(ROOT, "test", tmp_path / "prereg" / "frozen_code.json")
    shared = FakeLLM(n_items=8, pool_ids=pool_ids)
    r = _runner(tmp_path, pool, "all", llm=shared)     # a single object, as the old runner did
    r.cmd_precompute(); r.cmd_register()
    r.cmd_run()
    rows = [json.loads(l) for l in open(tmp_path / "work" / "results" / "benchmarks.jsonl")]
    assert any("RuntimeError" in str(x.get("status")) for x in rows)       # the shared object fails across loops ...
    r2 = _runner(tmp_path / "b", pool, "all", llm=lambda: FakeLLM(n_items=8, pool_ids=pool_ids))
    (tmp_path / "b" / "prereg").mkdir(parents=True)
    F.freeze(ROOT, "test", tmp_path / "b" / "prereg" / "frozen_code.json")
    r2.cmd_precompute(); r2.cmd_register(); r2.cmd_run()
    rows2 = [json.loads(l) for l in open(tmp_path / "b" / "work" / "results" / "benchmarks.jsonl")]
    assert not any("RuntimeError" in str(x.get("status")) for x in rows2)   # ... and a fresh client set per command does not
