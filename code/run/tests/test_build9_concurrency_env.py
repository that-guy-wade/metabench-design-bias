"""Build 9: each per-provider concurrency in scripts_runner.make_llm is overridable by MB_<PROVIDER>_CONCURRENCY
(positive integer).  Unset keeps 40/56/32/64; garbage, zero or negative falls back to the default with one stderr warning
line per variable per process.  Offline: no key file is read and no request is made."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import scripts_runner as R  # noqa: E402

DEFAULTS = {"anthropic": 40, "openai": 56, "google": 32, "xai": 64}
VARS = {p: f"MB_{p.upper()}_CONCURRENCY" for p in DEFAULTS}


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key"); monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(R, "load_keys_from_env_file", lambda *a, **k: None)   # never touch the key file in a test
    for v in VARS.values():
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(R, "_concurrency_warned", set(), raising=False)
    pool = tmp_path / "pool.jsonl"
    pool.write_text(json.dumps({"id": "S0001", "question": "q?", "options": ["one", "two"], "answer": "A",
                                "answer_index": 0, "key_type": "letter"}) + "\n")
    a = R.build_parser().parse_args(["precompute", "--pool", str(pool), "--pool-name", "math", "--samples", "1",
                                     "--work-dir", str(tmp_path / "work"), "--sealed-dir", str(tmp_path / "sealed"),
                                     "--prereg-dir", str(tmp_path / "prereg"), "--health-dir", str(tmp_path / "health"),
                                     "--allow-non-tmpfs", "--keep-work"])
    return R.Runner(a)


def sems(llm):
    return {k: s._value for k, s in llm.sem.items()}


def test_defaults_unchanged_when_unset(runner, capsys):
    llm = runner.make_llm()
    assert sems(llm) == DEFAULTS
    assert llm.log_path == str(runner.work / "llm_calls.jsonl")
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("provider", sorted(DEFAULTS))
def test_each_override_applied_alone(runner, monkeypatch, capsys, provider):
    monkeypatch.setenv(VARS[provider], "177")
    assert sems(runner.make_llm()) == {**DEFAULTS, provider: 177}
    assert capsys.readouterr().err == ""


def test_all_overrides_together(runner, monkeypatch):
    want = {"anthropic": 1, "openai": 200, "google": 9, "xai": 160}
    for p, n in want.items():
        monkeypatch.setenv(VARS[p], str(n))
    assert sems(runner.make_llm()) == want


def test_constructor_arguments(runner, monkeypatch):
    monkeypatch.setenv(VARS["xai"], "128")
    seen = {}
    monkeypatch.setattr(R, "LLM", lambda **kw: seen.update(kw))
    runner.make_llm()
    assert seen == {"anthropic_concurrency": 40, "openai_concurrency": 56, "google_concurrency": 32,
                    "xai_concurrency": 128, "log_path": str(runner.work / "llm_calls.jsonl")}


@pytest.mark.parametrize("bad", ["garbage", "", "0", "-5", "3.5", "1e3", "+8", " 8", "nan"])
def test_bad_value_falls_back_and_warns_once(runner, monkeypatch, capsys, bad):
    monkeypatch.setenv(VARS["xai"], bad)
    monkeypatch.setenv(VARS["google"], "48")                  # a valid sibling still applies
    assert sems(runner.make_llm()) == {**DEFAULTS, "google": 48}
    assert sems(runner.make_llm())["xai"] == 64               # second client in the same process: no second warning
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "MB_XAI_CONCURRENCY" in err and "64" in err


def test_two_bad_variables_one_line_each(runner, monkeypatch, capsys):
    monkeypatch.setenv(VARS["anthropic"], "0"); monkeypatch.setenv(VARS["openai"], "-1")
    assert sems(runner.make_llm()) == DEFAULTS
    runner.make_llm()
    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 2 and "MB_ANTHROPIC_CONCURRENCY" in lines[0] and "MB_OPENAI_CONCURRENCY" in lines[1]
