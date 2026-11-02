"""Offline unit tests for the Google (Gemini REST) and xAI provider paths in metabench.llm (no network)."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import openai
import httpx2 as httpx
import pytest

from metabench import llm as llm_mod
from metabench.interface import T1_TOOLS
from metabench.llm import LLM, Conversation, ModelSpec, parse_google_response, _strip_schema

GSPEC = ModelSpec(key="g", provider="google", model_id="gemini-test", effort="low")
XSPEC = ModelSpec(key="x", provider="xai", model_id="grok-test", effort="low")


# -- (a) tool-schema conversion ---------------------------------------------------------------------------------------

def test_google_tools_strip_additional_properties_at_all_depths_and_keep_required():
    nested = {"name": "deep", "description": "d", "input_schema": {
        "type": "object", "additionalProperties": False,
        "properties": {"m": {"type": "object", "additionalProperties": {"type": "number"}},
                       "arr": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                          "properties": {"k": {"type": "string"}}, "required": ["k"]}}},
        "required": ["m"]}}
    decls = LLM._google_tools(T1_TOOLS + [nested])
    assert "additionalProperties" not in json.dumps(decls)
    by_name = {d["name"]: d for d in decls}
    assert by_name["set_weights"]["parameters"]["required"] == ["weights"]
    assert by_name["set_weights"]["parameters"]["properties"]["weights"] == {"type": "object"}
    assert by_name["deep"]["parameters"]["required"] == ["m"]
    assert by_name["deep"]["parameters"]["properties"]["arr"]["items"]["required"] == ["k"]
    assert set(decls[0]) == {"name", "description", "parameters"}


def test_strip_schema_does_not_mutate_input():
    s = {"type": "object", "additionalProperties": False, "properties": {}}
    _strip_schema(s)
    assert "additionalProperties" in s


# -- (b) Gemini response parsing ------------------------------------------------------------------------------------

def _gemini_payload(with_id=True, finish="STOP"):
    fc = {"name": "ping", "args": {"x": 7}}
    if with_id:
        fc["id"] = "fc-123"
    return {"candidates": [{"content": {"role": "model", "parts": [
                {"text": "calling"}, {"text": "hidden", "thought": True},
                {"functionCall": fc, "thoughtSignature": "sig=="}]}, "finishReason": finish}],
            "usageMetadata": {"promptTokenCount": 100, "cachedContentTokenCount": 50, "candidatesTokenCount": 10,
                              "thoughtsTokenCount": 30, "totalTokenCount": 140}}


def test_parse_google_response_function_call_usage_and_verbatim_parts():
    r = parse_google_response(_gemini_payload(), GSPEC)
    assert r.text == "calling"                     # thought parts are not user-visible text
    assert [(c.id, c.name, c.args) for c in r.tool_calls] == [("fc-123", "ping", {"x": 7})]
    assert r.stop_reason == "tool_use"
    assert r.in_tokens == 55                       # 50 uncached + 0.1 * 50 cached
    assert r.out_tokens == 40                      # candidates + thoughts
    assert r.provider == "google" and r.model_id == "gemini-test"
    assert r.raw_assistant_message["role"] == "model"
    assert r.raw_assistant_message["parts"][2]["thoughtSignature"] == "sig=="


def test_parse_google_response_synthesises_ids_and_maps_finish_reason():
    r1 = parse_google_response(_gemini_payload(with_id=False), GSPEC)
    r2 = parse_google_response(_gemini_payload(with_id=False), GSPEC)
    assert r1.tool_calls[0].id.startswith("gc") and r1.tool_calls[0].id != r2.tool_calls[0].id
    plain = {"candidates": [{"content": {"parts": [{"text": "OK"}]}, "finishReason": "MAX_TOKENS"}],
             "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 1}}
    r3 = parse_google_response(plain, GSPEC)
    assert (r3.text, r3.stop_reason, r3.in_tokens, r3.out_tokens, r3.tool_calls) == ("OK", "max_tokens", 5, 1, [])
    assert parse_google_response({"candidates": [{"finishReason": "SAFETY"}]}, GSPEC).stop_reason == "refusal"


# -- (c) Conversation formats ---------------------------------------------------------------------------------------

def test_conversation_google_history_and_tool_results():
    conv = Conversation("google")
    conv.add_user("hi")
    assert conv.messages == [{"role": "user", "parts": [{"text": "hi"}]}]
    resp = parse_google_response(_gemini_payload(), GSPEC)
    conv.add_assistant(resp)
    assert conv.messages[1] is resp.raw_assistant_message
    conv.add_tool_results([(resp.tool_calls[0].id, "pong")])
    assert conv.messages[2] == {"role": "user", "parts": [
        {"functionResponse": {"name": "ping", "response": {"result": "pong"}, "id": "fc-123"}}]}
    # synthesised id: name is carried, no id field is sent back
    resp2 = parse_google_response(_gemini_payload(with_id=False), GSPEC)
    conv.add_assistant(resp2)
    conv.add_tool_results([(resp2.tool_calls[0].id, "pong2")])
    assert conv.messages[-1]["parts"] == [{"functionResponse": {"name": "ping", "response": {"result": "pong2"}}}]


def test_conversation_xai_history_and_tool_results():
    conv = Conversation("xai")
    conv.add_user("hi")
    raw = {"role": "assistant", "content": None,
           "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "ping", "arguments": "{\"x\": 7}"}}]}
    resp = llm_mod.LLMResponse(text="", tool_calls=[llm_mod.ToolCall("call_1", "ping", {"x": 7})], stop_reason="tool_calls",
                               in_tokens=1, out_tokens=1, latency=0.0, raw_assistant_message=raw, provider="xai", model_id="grok-test")
    conv.add_assistant(resp)
    conv.add_tool_results([("call_1", "pong")])
    assert conv.messages == [{"role": "user", "content": "hi"}, raw, {"role": "tool", "tool_call_id": "call_1", "content": "pong"}]
    assert conv.previous_response_id is None


def test_conversation_anthropic_and_openai_formats_unchanged():
    a = Conversation("anthropic"); a.add_user("hi"); a.add_tool_results([("tu_1", "r")])
    assert a.messages == [{"role": "user", "content": "hi"},
                          {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "r"}]}]
    o = Conversation("openai"); o.add_user("hi"); o.add_tool_results([("call_1", "r")])
    assert o.messages == [{"role": "user", "content": "hi"}, {"type": "function_call_output", "call_id": "call_1", "output": "r"}]


# -- (d) xAI reasoning_effort fallback ---------------------------------------------------------------------------------

def _fake_completion(prompt=31, completion=1, total=699, cached=0, reasoning=668):
    tc = SimpleNamespace(id="call_9", function=SimpleNamespace(name="ping", arguments="{\"x\": 7}"))
    msg = SimpleNamespace(content=None, tool_calls=[tc])
    usage = SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
                            completion_tokens_details=SimpleNamespace(reasoning_tokens=reasoning))
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="tool_calls")], usage=usage)


class _StubCompletions:
    def __init__(self, reject_effort_times: int, message: str):
        self.calls: list[dict] = []
        self.reject = reject_effort_times
        self.message = message

    async def create(self, **kw):
        self.calls.append(kw)
        if "reasoning_effort" in kw and self.reject > 0:
            self.reject -= 1
            req = httpx.Request("POST", "https://api.x.ai/v1/chat/completions")
            raise openai.BadRequestError(self.message, response=httpx.Response(400, request=req), body=None)
        return _fake_completion()


def _llm_with_stub(stub):
    llm = LLM()
    llm._xc = SimpleNamespace(chat=SimpleNamespace(completions=stub))
    return llm


@pytest.fixture(autouse=True)
def _clear_xai_memo(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY"):   # SDK clients need a value at construction; no network
        monkeypatch.setenv(k, "test-key")
    llm_mod.XAI_NO_REASONING_EFFORT.discard("grok-test")
    yield
    llm_mod.XAI_NO_REASONING_EFFORT.discard("grok-test")


def test_xai_reasoning_effort_fallback_and_memo():
    asyncio.run(_test_xai_reasoning_effort_fallback_and_memo())


async def _test_xai_reasoning_effort_fallback_and_memo():
    stub = _StubCompletions(1, "Argument not supported on this model: reasoning_effort")
    llm = _llm_with_stub(stub)
    r = await llm.chat(XSPEC, "sys", [{"role": "user", "content": "hi"}], tools=[{"name": "ping", "description": "p",
                       "input_schema": {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}}])
    assert len(stub.calls) == 2
    assert stub.calls[0]["reasoning_effort"] == "low" and "reasoning_effort" not in stub.calls[1]
    assert stub.calls[1]["messages"][0] == {"role": "system", "content": "sys"}
    assert stub.calls[1]["tools"][0]["function"]["name"] == "ping" and stub.calls[1]["max_tokens"] == 2048
    assert "grok-test" in llm_mod.XAI_NO_REASONING_EFFORT
    assert [(c.id, c.name, c.args) for c in r.tool_calls] == [("call_9", "ping", {"x": 7})]
    assert r.stop_reason == "tool_calls" and r.provider == "xai"
    # reasoning tokens not included in completion_tokens on this response: out = total - prompt, counted once
    assert (r.in_tokens, r.out_tokens) == (31, 668)
    assert r.raw_assistant_message["tool_calls"][0]["function"]["arguments"] == "{\"x\": 7}"
    # memoised: the next call skips reasoning_effort without a probe
    await llm.chat(XSPEC, None, [{"role": "user", "content": "hi"}])
    assert len(stub.calls) == 3 and "reasoning_effort" not in stub.calls[2]
    assert llm.totals["calls"] == 2 and llm.totals["errors"] == 0


def test_xai_unrelated_400_is_raised():
    asyncio.run(_test_xai_unrelated_400_is_raised())


async def _test_xai_unrelated_400_is_raised():
    stub = _StubCompletions(1, "Invalid request: presence_penalty not supported")
    llm = _llm_with_stub(stub)
    with pytest.raises(openai.BadRequestError):
        await llm.chat(XSPEC, None, [{"role": "user", "content": "hi"}])
    assert len(stub.calls) == 1 and "grok-test" not in llm_mod.XAI_NO_REASONING_EFFORT


def test_xai_cached_tokens_folded_and_completion_tokens_kept_when_inclusive():
    asyncio.run(_test_xai_cached_tokens_folded_and_completion_tokens_kept_when_inclusive())


async def _test_xai_cached_tokens_folded_and_completion_tokens_kept_when_inclusive():
    class _Stub:
        async def create(self, **kw):
            return _fake_completion(prompt=1000, completion=700, total=1700, cached=400, reasoning=600)
    llm = _llm_with_stub(_Stub())
    r = await llm.chat(ModelSpec(key="x", provider="xai", model_id="grok-test"), None, [{"role": "user", "content": "hi"}])
    assert (r.in_tokens, r.out_tokens) == (640, 700)   # 600 + 0.1*400 ; reasoning already inside completion_tokens


# -- Google request body (monkeypatched HTTP) ---------------------------------------------------------------------------

def test_google_request_body_thinking_level_vs_budget(monkeypatch):
    asyncio.run(_test_google_request_body_thinking_level_vs_budget(monkeypatch))


async def _test_google_request_body_thinking_level_vs_budget(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    sent = []

    class _Resp:
        status_code = 200
        text = ""
        def json(self):
            return _gemini_payload()

    async def fake_post(url, json=None, headers=None):
        sent.append((url, json, headers))
        return _Resp()

    llm = LLM(google_transport="apikey")
    monkeypatch.setattr(llm.gc, "post", fake_post)
    conv = Conversation("google"); conv.add_user("call ping")
    tools = [{"name": "ping", "description": "p", "input_schema": {"type": "object", "additionalProperties": False,
                                                                    "properties": {"x": {"type": "integer"}}, "required": ["x"]}}]
    r = await llm.chat_conv(ModelSpec(key="g", provider="google", model_id="gemini-4-argon", effort="high"), "sys", conv, tools=tools)
    url, body, headers = sent[0]
    assert url.endswith("/models/gemini-4-argon:generateContent") and headers["x-goog-api-key"] == "test-key"
    assert body["systemInstruction"] == {"parts": [{"text": "sys"}]}
    assert body["generationConfig"] == {"maxOutputTokens": 2048, "thinkingConfig": {"thinkingLevel": "high"}}
    assert body["tools"] == [{"functionDeclarations": [{"name": "ping", "description": "p", "parameters":
                              {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}}]}]
    assert r.tool_calls[0].name == "ping" and llm.totals["calls"] == 1
    conv.add_assistant(r); conv.add_tool_results([(r.tool_calls[0].id, "pong")])
    await llm.chat_conv(ModelSpec(key="g", provider="google", model_id="gemini-2.5-pro", effort="medium"), None, conv, tools=tools)
    body2 = sent[1][1]
    assert body2["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 8192}
    assert "systemInstruction" not in body2
    assert body2["contents"][1]["parts"][2]["thoughtSignature"] == "sig=="      # echoed verbatim
    assert body2["contents"][2]["parts"][0]["functionResponse"]["id"] == "fc-123"
    await llm.chat(ModelSpec(key="g", provider="google", model_id="gemini-3.8-flash"), None, [{"role": "user", "content": "q"}], temperature=1.0)
    body3 = sent[2][1]
    assert body3["contents"] == [{"role": "user", "parts": [{"text": "q"}]}]
    assert body3["generationConfig"] == {"maxOutputTokens": 2048, "temperature": 1.0}


def test_google_retries_5xx_and_raises_4xx(monkeypatch):
    asyncio.run(_test_google_retries_5xx_and_raises_4xx(monkeypatch))


async def _test_google_retries_5xx_and_raises_4xx(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_mod.asyncio, "sleep", _no_sleep)
    codes = iter([503, 200])

    class _Resp:
        def __init__(self, code):
            self.status_code, self.text = code, "server error"
        def json(self):
            return _gemini_payload()

    async def fake_post(url, json=None, headers=None):
        return _Resp(next(codes))

    llm = LLM(google_transport="apikey")
    monkeypatch.setattr(llm.gc, "post", fake_post)
    r = await llm.chat(GSPEC, None, [{"role": "user", "content": "q"}])
    assert r.text == "calling" and llm.totals["errors"] == 1 and llm.totals["calls"] == 1

    async def bad_post(url, json=None, headers=None):
        return _Resp(400)
    monkeypatch.setattr(llm.gc, "post", bad_post)
    with pytest.raises(llm_mod.GoogleAPIError) as ei:
        await llm.chat(GSPEC, None, [{"role": "user", "content": "q"}])
    assert ei.value.status_code == 400 and llm.totals["errors"] == 1


async def _no_sleep(_):
    return None


# ---- learned from the live probe of the confirmatory ids (2026-10-25) ----

def test_xai_camelcase_reasoning_rejection_triggers_fallback():
    """grok-4.20-0309-reasoning rejects with 'does not support parameter reasoningEffort' (camelCase)."""
    asyncio.run(_test_xai_camelcase())


async def _test_xai_camelcase():
    stub = _StubCompletions(1, "Error code: 400 - {'code': 'invalid-argument', 'error': 'Model grok-test does not support parameter reasoningEffort.'}")
    llm = _llm_with_stub(stub)
    r = await llm.chat(XSPEC, None, [{"role": "user", "content": "hi"}])
    assert len(stub.calls) == 2 and "reasoning_effort" not in stub.calls[1]
    assert "grok-test" in llm_mod.XAI_NO_REASONING_EFFORT and r.provider == "xai"


def test_openai_gpt6_chat_uses_max_completion_tokens():
    """gpt-6.x models reject max_tokens ('use max_completion_tokens'); the single-turn evaluee path must send the latter."""
    asyncio.run(_test_openai_gpt6())


async def _test_openai_gpt6():
    calls = []

    class _Stub:
        async def create(self, **kw):
            calls.append(kw)
            return _fake_completion()

    llm = LLM()
    llm.oc = SimpleNamespace(chat=SimpleNamespace(completions=_Stub()))
    for mid in ("gpt-6.1-sol", "gpt-6-luna", "gpt-5.5"):
        await llm.chat(ModelSpec("k", "openai", mid, "low", 2048, "openai"), None, [{"role": "user", "content": "hi"}])
    assert all("max_completion_tokens" in c and "max_tokens" not in c and c["reasoning_effort"] == "low" for c in calls)
    await llm.chat(ModelSpec("k", "openai", "gpt-4.1", None, 2048, "openai"), None, [{"role": "user", "content": "hi"}], temperature=1.0)
    assert "max_tokens" in calls[-1] and "max_completion_tokens" not in calls[-1]


# ---- Vertex AI transport (default for Google since 2026-10-25 08:05 UTC; the API-key path returns HTTP 402) ----

def test_vertex_transport_url_bearer_cache_and_401_refresh(monkeypatch):
    asyncio.run(_test_vertex_transport(monkeypatch))


async def _test_vertex_transport(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)        # Vertex must not need the API key
    sent, tokens = [], iter(["tok-A", "tok-B"])
    gcloud_calls = []

    def fake_gcloud():
        gcloud_calls.append(1)
        return next(tokens)

    class _Resp:
        def __init__(self, code):
            self.status_code, self.text = code, "unauthorised" if code == 401 else ""
        def json(self):
            return _gemini_payload()

    codes = iter([200, 200, 401, 200])

    async def fake_post(url, json=None, headers=None):
        sent.append((url, json, headers))
        return _Resp(next(codes))

    llm = LLM()                                                # default transport
    assert llm.google_transport == "vertex"
    monkeypatch.setattr(llm, "_gcloud_access_token", fake_gcloud)
    monkeypatch.setattr(llm.gc, "post", fake_post)
    spec = ModelSpec(key="g", provider="google", model_id="gemini-4-argon", effort="low")
    await llm.chat(spec, "sys", [{"role": "user", "content": "q"}])
    await llm.chat(spec, None, [{"role": "user", "content": "q"}])
    url, body, headers = sent[0]
    assert url == ("https://aiplatform.googleapis.com/v1/projects/" + llm_mod.VERTEX_PROJECT + "/locations/"
                   + llm_mod.VERTEX_LOCATION + "/publishers/google/models/gemini-4-argon:generateContent")
    assert headers["Authorization"] == "Bearer tok-A" and "x-goog-api-key" not in headers
    assert body["systemInstruction"] == {"parts": [{"text": "sys"}]} and body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
    assert len(gcloud_calls) == 1                              # cached across calls
    # third call gets a 401: the token is refreshed once and the request retried with the new token, no error counted
    r = await llm.chat(spec, None, [{"role": "user", "content": "q"}])
    assert r.text == "calling" and len(gcloud_calls) == 2 and sent[-1][2]["Authorization"] == "Bearer tok-B"
    assert llm.totals["errors"] == 0 and llm.totals["calls"] == 3
    # expiry: an old timestamp forces a refresh on the next call
    llm._vertex_token_t -= llm_mod.VERTEX_TOKEN_TTL_S + 1
    codes = iter([200]); monkeypatch.setattr(llm.gc, "post", fake_post)
    tokens = iter(["tok-C"]); monkeypatch.setattr(llm, "_gcloud_access_token", lambda: next(tokens))
    await llm.chat(spec, None, [{"role": "user", "content": "q"}])
    assert sent[-1][2]["Authorization"] == "Bearer tok-C"


def test_vertex_error_message_never_carries_the_token(monkeypatch):
    asyncio.run(_test_vertex_error_message(monkeypatch))


async def _test_vertex_error_message(monkeypatch):
    class _Resp:
        status_code, text = 400, "bad request body"
        def json(self):
            return {}

    async def fake_post(url, json=None, headers=None):
        return _Resp()

    llm = LLM(google_transport="vertex")
    monkeypatch.setattr(llm, "_gcloud_access_token", lambda: "SECRET-TOKEN-VALUE")
    monkeypatch.setattr(llm.gc, "post", fake_post)
    with pytest.raises(llm_mod.GoogleAPIError) as ei:
        await llm.chat(GSPEC, None, [{"role": "user", "content": "q"}])
    assert "SECRET-TOKEN-VALUE" not in str(ei.value) and ei.value.status_code == 400
    assert LLM(google_transport="apikey").google_transport == "apikey"


# ---- regression (Google Vertex designer smoke, 2026-10-25 08:14 UTC): a retried API error on a tag that already had a
# successful call raised KeyError('errors') inside the retry path and killed the session -----------------------------

def test_retry_after_a_successful_call_on_the_same_tag_does_not_raise():
    asyncio.run(_test_retry_after_success(monkeypatch=None))


async def _test_retry_after_success(monkeypatch):
    import metabench.llm as M
    orig_sleep = M.asyncio.sleep
    M.asyncio.sleep = _no_sleep
    try:
        codes = iter([200, 503, 200, 503, 200])

        class _Resp:
            def __init__(self, code):
                self.status_code, self.text = code, "err"
            def json(self):
                return _gemini_payload()

        async def fake_post(url, json=None, headers=None):
            return _Resp(next(codes))

        llm = LLM(google_transport="apikey")
        import os
        os.environ.setdefault("GEMINI_API_KEY", "test-key")
        llm.gc.post = fake_post
        await llm.chat(GSPEC, None, [{"role": "user", "content": "q"}], tag="designer:s1")       # success creates the tag
        await llm.chat(GSPEC, None, [{"role": "user", "content": "q"}], tag="designer:s1")       # 503 then 200: must not raise
        conv = Conversation("google"); conv.add_user("q")
        await llm.chat_conv(GSPEC, None, conv, tag="designer:s1")                                 # same on the multi-turn path
        assert llm.by_tag["designer:s1"]["errors"] == 2 and llm.by_tag["designer:s1"]["calls"] == 3 and llm.totals["errors"] == 2
    finally:
        M.asyncio.sleep = orig_sleep
