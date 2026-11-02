"""Build 3 (pre-session, 2026-10-25 10:58 UTC decisions): per-pool evaluee output cap exposed by metabench.panel and
passed through by the precompute and the runner; xAI per-call timeout 240 s with retries unchanged; xAI concurrency 64
in scripts_runner.make_llm.  Offline: a fake LLM records the max_tokens it receives; no key file is read."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import scripts_runner as R  # noqa: E402
from metabench import panel  # noqa: E402
from metabench import llm as llm_mod  # noqa: E402
from metabench.llm import LLM, LLMResponse, ModelSpec  # noqa: E402


class RecordingLLM:
    def __init__(self):
        self.max_tokens: list = []
        self.totals = {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "errors": 0}

    async def chat(self, spec, system, messages, tools=None, max_tokens=None, tag="", temperature=None, max_attempts=7):
        self.max_tokens.append(max_tokens)
        return LLMResponse(text="Answer: A", tool_calls=[], stop_reason="end_turn", in_tokens=1, out_tokens=1, latency=0.0,
                           raw_assistant_message={}, provider=spec.provider, model_id=spec.model_id)


ITEM = {"id": "S0001", "question": "q?", "options": ["one", "two"], "answer": "A", "answer_index": 0, "key_type": "letter"}
SPEC = ModelSpec("k", "openai", "m", "low", 2048, "openai")


@pytest.fixture(autouse=True)
def _reset_pool():
    panel.set_pool(None)
    yield
    panel.set_pool(None)


def test_registered_caps():
    assert panel.EVALUEE_MAX_TOKENS == {"math": 4096, "factual": 4096, "code": 8192}
    assert [panel.evaluee_max_tokens(p) for p in ("math", "factual", "code", "pilot", "smoke", None)] == [4096, 4096, 8192, None, None, None]
    # designer and monitor settings untouched
    from metabench import designer, monitors
    assert designer.DESIGNER_MAX_TOKENS == 8000
    assert all(s.max_tokens == 4000 for s in monitors.MONITORS_BY_DEVELOPER.values())
    assert all(s.max_tokens == 2048 for s in panel.CONFIRMATORY_PANEL)   # the ModelSpec fallback is unchanged


def test_precompute_passes_the_pool_cap_through(tmp_path):
    llm = RecordingLLM()
    out = tmp_path / "pc.jsonl"
    asyncio.run(panel.precompute({ITEM["id"]: ITEM}, [SPEC], 2, out, llm, concurrency=2, max_tokens=8192))
    assert llm.max_tokens == [8192, 8192]
    assert len(out.read_text().splitlines()) == 2
    llm2 = RecordingLLM()
    asyncio.run(panel.precompute({ITEM["id"]: ITEM}, [SPEC], 1, tmp_path / "pc2.jsonl", llm2, concurrency=2))
    assert llm2.max_tokens == [None]          # no cap given and no active pool: the LLM falls back to spec.max_tokens


def test_score_item_uses_the_active_pool_cap_for_the_live_rescore():
    """designer.make_live_scorer calls score_item without a cap: the active pool's cap must apply there too, so that
    edited items are re-scored under the same cap as the precompute."""
    llm = RecordingLLM()
    panel.set_pool("code")
    asyncio.run(panel.score_item(llm, SPEC, ITEM, 0))
    panel.set_pool("math")
    asyncio.run(panel.score_item(llm, SPEC, ITEM, 0))
    panel.set_pool("pilot")
    asyncio.run(panel.score_item(llm, SPEC, ITEM, 0))
    asyncio.run(panel.score_item(llm, SPEC, ITEM, 0, max_tokens=123))   # explicit argument wins
    assert llm.max_tokens == [8192, 4096, None, 123]


def test_real_llm_applies_spec_cap_when_no_pool_cap(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key"); monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    calls = []

    class Stub:
        async def create(self, **kw):
            calls.append(kw)
            from types import SimpleNamespace as NS
            return NS(choices=[NS(message=NS(content="Answer: A", tool_calls=None), finish_reason="stop")],
                      usage=NS(prompt_tokens=1, completion_tokens=1, total_tokens=2, prompt_tokens_details=None))
    from types import SimpleNamespace
    llm = LLM()
    llm.oc = SimpleNamespace(chat=SimpleNamespace(completions=Stub()))
    panel.set_pool("factual")
    asyncio.run(panel.score_item(llm, ModelSpec("k", "openai", "gpt-4.1", None, 2048, "openai"), ITEM, 0))
    panel.set_pool("smoke")
    asyncio.run(panel.score_item(llm, ModelSpec("k", "openai", "gpt-4.1", None, 2048, "openai"), ITEM, 0))
    assert [c["max_tokens"] for c in calls] == [4096, 2048]


def _runner_args(tmp_path, pool_name):
    pool = tmp_path / "pool.jsonl"
    pool.write_text(json.dumps(ITEM) + "\n")
    return R.build_parser().parse_args(["precompute", "--pool", str(pool), "--pool-name", pool_name, "--samples", "1",
                                        "--work-dir", str(tmp_path / "work"), "--sealed-dir", str(tmp_path / "sealed"),
                                        "--prereg-dir", str(tmp_path / "prereg"), "--health-dir", str(tmp_path / "health"),
                                        "--allow-non-tmpfs", "--keep-work"])


@pytest.mark.parametrize("pool_name,cap", [("code", 8192), ("math", 4096), ("factual", 4096), ("smoke", None)])
def test_runner_sets_the_pool_cap_and_passes_it_to_precompute(tmp_path, pool_name, cap, monkeypatch):
    seen = {}

    async def fake_precompute(pool, specs, k, out_path, llm, concurrency=48, max_tokens=None, providers=None):
        seen["max_tokens"] = max_tokens
        out_path.write_text("")
        return {}
    monkeypatch.setattr(panel, "precompute", fake_precompute)
    r = R.Runner(_runner_args(tmp_path, pool_name))
    assert panel.ACTIVE_POOL == {"name": pool_name, "max_tokens": cap}
    r.llm_factory = RecordingLLM
    r.sealer.check_keyring = lambda: None
    r.sealer.seal = lambda *a, **k: None
    r.cmd_precompute()
    assert seen["max_tokens"] == cap


def test_xai_timeout_240_retries_unchanged(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key"); monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    assert llm_mod.XAI_TIMEOUT_S == 240.0
    xc = LLM().xc
    assert xc.timeout == 240.0 and xc.max_retries == 3
    assert LLM().oc.timeout == 600.0            # other providers unchanged
    import inspect
    assert inspect.signature(LLM.chat).parameters["max_attempts"].default == 7


def test_make_llm_xai_concurrency_64(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key"); monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(R, "load_keys_from_env_file", lambda *a, **k: None)   # never touch the key file in a test
    r = R.Runner(_runner_args(tmp_path, "math"))
    llm = r.make_llm()
    assert {k: s._value for k, s in llm.sem.items()} == {"anthropic": 40, "openai": 56, "google": 32, "xai": 64}
