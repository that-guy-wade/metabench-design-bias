"""Build 7: the xAI per-call timeout is overridable by MB_XAI_TIMEOUT_S (float seconds) at client construction.
Default stays 240.0; garbage or non-positive values fall back to the default with exactly one stderr warning per process.
Offline: no key file is read and no request is made."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from metabench import llm as llm_mod  # noqa: E402
from metabench.llm import LLM  # noqa: E402


@pytest.fixture
def keys(monkeypatch):
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY"):
        monkeypatch.setenv(k, "test-key")
    monkeypatch.delenv("MB_XAI_TIMEOUT_S", raising=False)
    monkeypatch.setattr(llm_mod, "_xai_timeout_warned", False)


def test_default_240_when_unset(keys, capsys):
    assert llm_mod.XAI_TIMEOUT_S == 240.0
    assert llm_mod.xai_timeout_s() == 240.0
    assert LLM().xc.timeout == 240.0
    assert capsys.readouterr().err == ""


def test_env_override_600(keys, monkeypatch, capsys):
    monkeypatch.setenv("MB_XAI_TIMEOUT_S", "600")
    assert llm_mod.xai_timeout_s() == 600.0
    xc = LLM().xc
    assert xc.timeout == 600.0 and xc.max_retries == 3
    assert llm_mod.XAI_TIMEOUT_S == 240.0            # the constant itself is untouched
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("bad", ["garbage", "", "0", "-5", "nan", "inf"])
def test_fallback_on_bad_value_warns_once(keys, monkeypatch, capsys, bad):
    monkeypatch.setenv("MB_XAI_TIMEOUT_S", bad)
    assert llm_mod.xai_timeout_s() == 240.0
    assert LLM().xc.timeout == 240.0                 # second read: same fallback, no second warning
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "MB_XAI_TIMEOUT_S" in err and "240.0" in err


def test_client_constructed_with_env_timeout(keys, monkeypatch):
    monkeypatch.setenv("MB_XAI_TIMEOUT_S", "900.5")
    seen = {}

    class FakeClient:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setattr(llm_mod.openai, "AsyncOpenAI", FakeClient)
    llm = LLM()
    assert isinstance(llm.xc, FakeClient) and llm.xc is llm.xc      # cached after first use
    assert seen["timeout"] == 900.5 and seen["max_retries"] == 3 and seen["base_url"] == llm_mod.XAI_BASE_URL
    assert seen["api_key"] == "test-key"


def test_other_providers_unchanged(keys, monkeypatch):
    monkeypatch.setenv("MB_XAI_TIMEOUT_S", "600")
    llm = LLM()
    assert llm.oc.timeout == 600.0 and llm.ac.timeout == 600.0
    assert llm.gc.timeout.read == 600.0
