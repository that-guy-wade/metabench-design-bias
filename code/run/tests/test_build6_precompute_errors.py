"""Builder 6 (2026-10-26): the panel precompute's failure handling.

Defect: `panel.precompute` wrote an error row when `score_item` raised after the client's retries, but the resume path
counted every row as done, so a failed (item, model, sample) triple was never retried and `load_correctness` silently
dropped it (fewer samples or missing items for that model).  Offline: fake clients, no key file, no network.

Rule under test: the LAST row per triple wins (append-only; a retry's row supersedes the error row it follows)."""
import asyncio
import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import scripts_runner as R  # noqa: E402
from metabench import llm as llm_mod  # noqa: E402
from metabench import panel  # noqa: E402
from metabench.llm import LLM, GoogleAPIError, LLMResponse, ModelSpec  # noqa: E402

SPECS = [ModelSpec("a_g", "google", "gem", "low", 2048, "google"), ModelSpec("a_o", "openai", "gpt", "low", 2048, "openai"),
         ModelSpec("a_x", "xai", "grk", "low", 2048, "xai"), ModelSpec("a_a", "anthropic", "cla", "low", 2048, "anthropic")]


def _pool(n: int) -> dict[str, dict]:
    pool = {}
    for i in range(n):
        iid = f"S{i+1:04d}"
        pool[iid] = {"id": iid, "question": f"Question {i}?", "options": ["one", "two", "three", "four"], "answer": "A", "answer_index": 0,
                     "key_type": "letter", "category": "alpha"}
    return pool


class DeterministicLLM:
    """Answer depends only on (prompt, model id), never on call order; `down` providers raise a non-retryable error."""

    def __init__(self, down: set[str] = frozenset()):
        self.down = set(down)
        self.totals = {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "errors": 0}
        self.order: list[tuple[str, str]] = []
        self.auth_failures: dict[str, int] = {}

    async def chat(self, spec, system, messages, tools=None, max_tokens=None, tag="", temperature=None, max_attempts=7):
        item = messages[0]["content"].split("Question ")[1].split("?")[0]
        self.order.append((item, spec.key))
        if spec.provider in self.down:
            self.auth_failures[spec.provider] = self.auth_failures.get(spec.provider, 0) + 1
            raise GoogleAPIError(401, "gcloud auth print-access-token failed (rc=1)")
        self.totals["calls"] += 1
        h = hashlib.sha256((messages[0]["content"] + spec.model_id).encode()).digest()[0]
        return LLMResponse(text=f"Reasoning. Answer: {'ABCD'[h % 4]}", tool_calls=[], stop_reason="end_turn", in_tokens=10, out_tokens=5,
                           latency=0.0, raw_assistant_message={}, provider=spec.provider, model_id=spec.model_id)


@pytest.fixture
def frozen_clock(monkeypatch):
    """grade_s is wall time; freeze it so rows of the same triple are byte-identical across runs."""
    monkeypatch.setattr(panel, "time", types.SimpleNamespace(time=lambda: 1_000_000.0))


def _run(pool, out, llm, k=2, providers=None, concurrency=4):
    return asyncio.run(panel.precompute(pool, SPECS, k, out, llm, concurrency=concurrency, max_tokens=4096, providers=providers))


def _triples(path):
    return [(r["item"], r["model"], r["sample"]) for r in map(json.loads, path.read_text().splitlines())]


# ---- 1. resume semantics -------------------------------------------------------------------------------------------

def test_error_rows_are_retried_and_the_retry_supersedes_them(tmp_path, frozen_clock):
    pool = _pool(5)
    out = tmp_path / "pc.jsonl"
    first = DeterministicLLM(down={"google"})
    counts = _run(pool, out, first)
    lines1 = out.read_text().splitlines()
    assert counts["api_error"] == 10 and len(lines1) == 40
    err_triples = {(r["item"], r["model"], r["sample"]) for r in map(json.loads, lines1) if r.get("error")}
    assert len(err_triples) == 10 and {m for _, m, _ in err_triples} == {"a_g"}
    corr1 = panel.load_correctness(out)
    assert all((i, "a_g") not in corr1 for i in pool)                       # the defect's symptom: google missing entirely
    # resume with google back: exactly the 10 error triples are re-run, nothing else
    second = DeterministicLLM()
    counts2 = _run(pool, out, second)
    lines2 = out.read_text().splitlines()
    assert lines2[:40] == lines1                                            # existing rows byte-identical, nothing rewritten
    assert second.totals["calls"] == 10 and counts2["api_error"] == 0 and len(lines2) == 50
    assert {(r["item"], r["model"], r["sample"]) for r in map(json.loads, lines2[40:])} == err_triples
    # readers: last row per triple wins; a retried triple is counted once, never both its error row and its retry
    latest = panel.latest_rows(out)
    assert len(latest) == 40 and not any(r.get("error") for r in latest.values())
    corr2 = panel.load_correctness(out)
    assert all(len(corr2[(i, s.key)]) == 2 for i in pool for s in SPECS)
    assert {k: v for k, v in corr2.items() if k[1] != "a_g"} == corr1
    assert panel.error_counts_by_provider(out, SPECS) == {"anthropic": 0, "openai": 0, "google": 0, "xai": 0}
    # the retried rows are what a run with google up from the start would have written for those triples
    clean = DeterministicLLM()
    _run(pool, tmp_path / "clean.jsonl", clean)
    by_triple = {(r["item"], r["model"], r["sample"]): l for l, r in ((l, json.loads(l)) for l in (tmp_path / "clean.jsonl").read_text().splitlines())}
    assert all(by_triple[(json.loads(l)["item"], json.loads(l)["model"], json.loads(l)["sample"])] == l for l in lines2[40:])
    # a third run with google still down appends fresh error rows for the same triples ...
    third = DeterministicLLM(down={"google"})
    _run(pool, tmp_path / "again.jsonl", third)
    _run(pool, tmp_path / "again.jsonl", DeterministicLLM(down={"google"}))
    assert len((tmp_path / "again.jsonl").read_text().splitlines()) == 50
    # ... and the readers still see each triple once, with the error count unchanged
    assert panel.error_counts_by_provider(tmp_path / "again.jsonl", SPECS) == {"anthropic": 0, "openai": 0, "google": 10, "xai": 0}
    assert panel.error_counts_by_provider(tmp_path / "again.jsonl") == {"anthropic": 0, "openai": 0, "google": 0, "xai": 0, "unknown": 10}
    assert len(panel.latest_rows(tmp_path / "again.jsonl")) == 40


def test_load_correctness_follows_last_row_per_triple():
    rows = [{"item": "I1", "model": "m", "sample": 0, "correct": 1, "parsed": 1},
            {"item": "I1", "model": "m", "sample": 1, "pred": None, "correct": 0, "parsed": 0, "error": "HTTP 401: x"},
            {"item": "I1", "model": "m", "sample": 1, "correct": 1, "parsed": 1},            # retry supersedes the error row
            {"item": "I2", "model": "m", "sample": 0, "correct": 1, "parsed": 1},
            {"item": "I2", "model": "m", "sample": 0, "pred": None, "correct": 0, "parsed": 0, "error": "late error"},   # last wins: excluded
            {"item": "I3", "model": "m", "sample": 0, "correct": 0, "parsed": 1}]
    p = Path("/tmp") / f"b6_lc_{hashlib.sha256(json.dumps(rows).encode()).hexdigest()[:8]}.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n" + '{"item": "I3", "model": "m", "sam')   # partial last line (crash)
    try:
        assert panel.load_correctness(p) == {("I1", "m"): [1, 1], ("I3", "m"): [0]}
        assert panel.latest_rows(p, lambda r: bool(r.get("error"))) == {("I1", "m", 0): False, ("I1", "m", 1): False, ("I2", "m", 0): True, ("I3", "m", 0): False}
        assert panel.error_counts_by_provider(p) == {"anthropic": 0, "openai": 0, "google": 0, "xai": 0, "unknown": 1}
    finally:
        p.unlink()


# ---- 2. provider filter --------------------------------------------------------------------------------------------

def test_two_step_precompute_with_provider_filter_equals_one_full_run(tmp_path, frozen_clock):
    pool = _pool(12)
    full = DeterministicLLM()
    _run(pool, tmp_path / "full.jsonl", full, concurrency=1)
    step = tmp_path / "step.jsonl"
    skip_google = {"anthropic", "openai", "xai"}
    first = DeterministicLLM()
    _run(pool, step, first, providers=skip_google, concurrency=1)
    lines1 = step.read_text().splitlines()
    assert len(lines1) == 12 * 3 * 2 and not any(json.loads(l)["model"] == "a_g" for l in lines1)
    # same plan and shuffle: the filtered call order is the full run's order restricted to those providers
    assert first.order == [c for c in full.order if c[1] != "a_g"]
    second = DeterministicLLM()
    _run(pool, step, second, concurrency=1)
    lines2 = step.read_text().splitlines()
    assert lines2[: len(lines1)] == lines1                                   # first step's rows untouched
    assert second.totals["calls"] == 12 * 2 and all(json.loads(l)["model"] == "a_g" for l in lines2[len(lines1):])
    assert sorted(second.order) == sorted(c for c in full.order if c[1] == "a_g")   # a resumed list is reshuffled, as before
    # same set of triples and byte-identical rows as the one full run
    assert set(_triples(step)) == set(_triples(tmp_path / "full.jsonl")) and len(_triples(step)) == 12 * 4 * 2
    assert sorted(lines2) == sorted((tmp_path / "full.jsonl").read_text().splitlines())
    assert panel.load_correctness(step) == panel.load_correctness(tmp_path / "full.jsonl")
    # --only-providers form through the runner's filter: identical set semantics
    only = tmp_path / "only.jsonl"
    _run(pool, only, DeterministicLLM(), providers={"google"}, concurrency=1)
    assert {m for _, m, _ in _triples(only)} == {"a_g"} and len(_triples(only)) == 24


def _runner_args(tmp_path, cmd, extra=()):
    pool = tmp_path / "pool.jsonl"
    if not pool.exists():
        tmp_path.mkdir(exist_ok=True)
        pool.write_text("".join(json.dumps(it) + "\n" for it in _pool(4).values()))
    return R.build_parser().parse_args([cmd, "--pool", str(pool), "--pool-name", "smoke", "--samples", "1",
                                        "--work-dir", str(tmp_path / "work"), "--sealed-dir", str(tmp_path / "sealed"),
                                        "--prereg-dir", str(tmp_path / "prereg"), "--health-dir", str(tmp_path / "health"),
                                        "--allow-non-tmpfs", "--keep-work", *extra])


def _runner(tmp_path, cmd, llm, extra=()):
    r = R.Runner(_runner_args(tmp_path, cmd, extra))
    r.llm_factory = lambda: llm
    r.sealer.check_keyring = lambda: None
    r.sealer.seal = lambda *a, **k: None
    return r


def test_runner_provider_flags(tmp_path, capsys, frozen_clock):
    for cmd in ("register", "run", "all"):
        with pytest.raises(SystemExit, match="precompute. only"):
            R.Runner(_runner_args(tmp_path, cmd, ["--skip-providers", "google"]))
        with pytest.raises(SystemExit, match="precompute. only"):
            R.Runner(_runner_args(tmp_path, cmd, ["--only-providers", "google"]))
    with pytest.raises(SystemExit, match="unknown providers"):
        R.Runner(_runner_args(tmp_path, "precompute", ["--skip-providers", "gogle"]))
    assert R.Runner(_runner_args(tmp_path, "precompute")).providers is None
    assert R.Runner(_runner_args(tmp_path, "precompute", ["--skip-providers", "google,xai"])).providers == {"anthropic", "openai"}
    assert R.Runner(_runner_args(tmp_path, "precompute", ["--only-providers", "google,xai", "--skip-providers", "xai"])).providers == {"google"}
    # two-step through the runner with the confirmatory panel: skip google, then full
    n_google = sum(1 for s in panel.CONFIRMATORY_PANEL if s.provider == "google")
    first = DeterministicLLM()
    r1 = _runner(tmp_path, "precompute", first, ["--skip-providers", "google"])
    r1.cmd_precompute()
    out = r1.precompute_path()
    rows1 = out.read_text().splitlines()
    assert len(rows1) == 4 * (len(panel.CONFIRMATORY_PANEL) - n_google)
    assert not any(panel.spec_by_key(json.loads(l)["model"]).provider == "google" for l in rows1)
    second = DeterministicLLM()
    r2 = _runner(tmp_path, "precompute", second)
    r2.cmd_precompute()
    rows2 = out.read_text().splitlines()
    assert rows2[: len(rows1)] == rows1 and second.totals["calls"] == 4 * n_google
    assert len(set(_triples(out))) == 4 * len(panel.CONFIRMATORY_PANEL) == len(rows2)
    full = DeterministicLLM()
    r3 = _runner(tmp_path / "full", "precompute", full)
    r3.cmd_precompute()
    assert sorted(r3.precompute_path().read_text().splitlines()) == sorted(rows2)
    out_txt = capsys.readouterr().out
    assert "providers ['anthropic', 'openai', 'xai']" in out_txt
    assert 'error rows remaining by provider: {"anthropic": 0, "google": 0, "openai": 0, "xai": 0}' in out_txt


# ---- 3. fast failure on Google auth loss ---------------------------------------------------------------------------

def test_vertex_gcloud_failure_is_a_401_not_retried_and_counted(monkeypatch):
    asyncio.run(_test_vertex_gcloud_failure(monkeypatch))


async def _test_vertex_gcloud_failure(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):   # SDK clients need a value at construction; no network
        monkeypatch.setenv(k, "test-key")
    monkeypatch.setattr(llm_mod.asyncio, "sleep", _no_sleep)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    gcloud_runs, posted = [], []

    def fake_run(cmd, **kw):
        gcloud_runs.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="ERROR: metadata server 503; Google Cloud sign-in needs to be renewed")
    monkeypatch.setattr(llm_mod.subprocess, "run", fake_run)

    class _Resp:
        def __init__(self, code):
            self.status_code, self.text = code, "server error" if code != 200 else ""
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "Answer: A"}]}, "finishReason": "STOP"}],
                    "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1}}
    codes = iter([503, 200])

    async def fake_post(url, json=None, headers=None):
        posted.append(headers["Authorization"])
        return _Resp(next(codes))

    llm = LLM(google_transport="vertex")
    monkeypatch.setattr(llm.gc, "post", fake_post)
    spec = ModelSpec("g", "google", "gemini-4-argon", "low", 2048, "google")
    with pytest.raises(GoogleAPIError) as ei:
        await llm.chat(spec, None, [{"role": "user", "content": "q"}])
    assert ei.value.status_code == 401 and str(ei.value) == "HTTP 401: gcloud auth print-access-token failed (rc=1)"
    assert "metadata" not in str(ei.value) and "503" not in str(ei.value)       # gcloud's output never enters the message
    assert len(gcloud_runs) == 1 and posted == [] and llm.totals["errors"] == 0   # one attempt, no request, no retry counted
    assert llm.auth_failures == {"google": 1}
    # a second call inside the negative-cache window fails at once without running gcloud again
    with pytest.raises(GoogleAPIError) as ei2:
        await llm.chat(spec, None, [{"role": "user", "content": "q"}])
    assert ei2.value.status_code == 401 and "gcloud auth print-access-token failed" in str(ei2.value)
    assert len(gcloud_runs) == 1 and llm.auth_failures == {"google": 2}
    # the same for a timeout or a missing binary
    def raising_run(cmd, **kw):
        gcloud_runs.append(cmd)
        raise subprocess.TimeoutExpired(cmd, 60)
    monkeypatch.setattr(llm_mod.subprocess, "run", raising_run)
    llm._vertex_fail_t = -1e9
    with pytest.raises(GoogleAPIError, match="HTTP 401: gcloud auth print-access-token failed \\(TimeoutExpired\\)"):
        await llm.chat(spec, None, [{"role": "user", "content": "q"}])
    assert len(gcloud_runs) == 2 and posted == [] and llm.auth_failures == {"google": 3}
    # auth back: the token is fetched, and a 503 from Vertex is still retried as before (retry behaviour unchanged)
    monkeypatch.setattr(llm_mod.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="tok-Z\n", stderr=""))
    llm._vertex_fail_t = -1e9
    r = await llm.chat(spec, None, [{"role": "user", "content": "q"}])
    assert r.text == "Answer: A" and posted == ["Bearer tok-Z", "Bearer tok-Z"] and llm.totals["errors"] == 1
    assert llm.auth_failures == {"google": 3} and llm.totals["calls"] == 1
    # chat_conv shares the rule
    monkeypatch.setattr(llm_mod.subprocess, "run", fake_run)
    llm._vertex_token_t = 0.0
    conv = llm_mod.Conversation("google"); conv.add_user("q")
    with pytest.raises(GoogleAPIError, match="gcloud auth print-access-token failed"):
        await llm.chat_conv(spec, None, conv)
    assert llm.auth_failures == {"google": 4}


async def _no_sleep(_):
    return None


def test_provider_authentication_errors_are_counted_and_not_retried(monkeypatch):
    asyncio.run(_test_provider_auth_errors(monkeypatch))


async def _test_provider_auth_errors(monkeypatch):
    import httpx2 as httpx
    import openai
    monkeypatch.setenv("OPENAI_API_KEY", "test-key"); monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key"); monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setattr(llm_mod.asyncio, "sleep", _no_sleep)
    calls = []

    class Stub:
        async def create(self, **kw):
            calls.append(kw)
            req = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
            raise openai.AuthenticationError("bad key", response=httpx.Response(401, request=req), body=None)
    from types import SimpleNamespace
    llm = LLM()
    llm._xc = SimpleNamespace(chat=SimpleNamespace(completions=Stub()))
    with pytest.raises(openai.AuthenticationError):
        await llm.chat(ModelSpec("x", "xai", "grok-4.3", None, 2048, "xai"), None, [{"role": "user", "content": "q"}])
    assert len(calls) == 1 and llm.totals["errors"] == 0 and llm.auth_failures == {"xai": 1}


# ---- 4. the runner's end-of-precompute lines -------------------------------------------------------------------------

def test_runner_prints_auth_and_error_row_counts_per_provider_only(tmp_path, capsys, frozen_clock):
    r = _runner(tmp_path, "precompute", DeterministicLLM(down={"google"}))
    r.cmd_precompute()
    out = capsys.readouterr().out
    n_google = 4 * sum(1 for s in panel.CONFIRMATORY_PANEL if s.provider == "google")
    assert f'precompute auth failures (calls refused on provider authentication, not retried): {{"google": {n_google}}}' in out
    assert f'precompute error rows remaining by provider: {{"anthropic": 0, "google": {n_google}, "openai": 0, "xai": 0}}' in out
    assert not any(k in out for k in panel.all_panel_keys()) and "correct" not in out    # counts only: no model keys, no correctness
    r2 = _runner(tmp_path, "precompute", DeterministicLLM())
    r2.cmd_precompute()
    out2 = capsys.readouterr().out
    assert "auth failures" not in out2
    assert 'precompute error rows remaining by provider: {"anthropic": 0, "google": 0, "openai": 0, "xai": 0}' in out2
    assert f"{n_google} error rows to retry" in out2
