"""Unified async LLM client for Anthropic, OpenAI, Google (Gemini) and xAI with tool calling, retries and cost logging.

Keys are read from the environment (ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY / XAI_API_KEY), which the
caller loads from /path/to/model-keys.env without printing it.  Nothing in this module prints keys.
Google is called over REST (generativelanguage.googleapis.com); xAI through its OpenAI-compatible chat completions.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import os
import random
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import anthropic
import httpx2 as httpx
import openai

# ----------------------------------------------------------------------------------------------
# Model specs
# ----------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelSpec:
    key: str                 # internal id used in the panel / as designer id
    provider: str            # "anthropic" | "openai" | "google" | "xai"
    model_id: str            # provider model id
    effort: Optional[str] = None   # anthropic output_config.effort / openai+xai reasoning_effort / gemini thinkingLevel
    max_tokens: int = 2048
    family: str = ""         # developer family label
    note: str = ""

# USD per 1M tokens (input, output); cached-input ignored (small).  Anthropic from claude-api skill table
# (2026-10-06); OpenAI prices are approximate public list prices and only used for cost *estimates*.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "gpt-5.5": (5.0, 30.0),
    "gpt-5.4": (2.5, 15.0),
    "gpt-5.4-mini": (0.5, 3.0),
    "gpt-5.4-nano": (0.1, 0.6),
    "gpt-5.1": (1.25, 10.0),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4o-mini": (0.15, 0.6),
    # Google / xAI: placeholders equal to the default fallback; fill in from the providers' price lists.
    # Third-party pricing pages dated October 2026 (not provider pages; see docs/BUILD_REPORT.md). Cost ESTIMATES only.
    "gpt-6.1-sol": (2.0, 10.0),
    "gpt-6-luna": (0.10, 0.50),
    "gemini-4-argon": (2.0, 10.0),          # introductory through 2026-11-30, then (4.0, 20.0)
    "gemini-3.8-flash": (0.75, 3.75),       # introductory through 2026-12-31, then (1.50, 7.50)
    "gemini-3.1-pro-preview": (2.0, 12.0),
    "gemini-3.5-flash": (0.75, 3.75),       # assumed equal to 3.8 Flash (unverified)
    "gemini-2.5-pro": (1.25, 10.0),
    # xAI: from api.x.ai/v1/language-models on 2026-10-25 (prompt/completion price fields in 1e-4 USD per 1M tokens)
    "grok-4.7": (2.0, 6.0),
    "grok-4.6": (2.0, 6.0),
    "grok-4.5": (2.0, 6.0),
    "grok-4.3": (1.25, 2.50),
    "grok-4.20-0309-reasoning": (1.25, 2.50),
}

def est_cost(model_id: str, in_tok: int, out_tok: int) -> float:
    pi, po = PRICES.get(model_id, (3.0, 15.0))
    return (in_tok * pi + out_tok * po) / 1e6

# ----------------------------------------------------------------------------------------------
# Unified response
# ----------------------------------------------------------------------------------------------

@dataclass
class ToolCall:
    id: str
    name: str
    args: dict

@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str
    in_tokens: int
    out_tokens: int
    latency: float
    raw_assistant_message: Any          # provider-native assistant turn, to append to history
    provider: str
    model_id: str

    @property
    def cost(self) -> float:
        return est_cost(self.model_id, self.in_tokens, self.out_tokens)

# ----------------------------------------------------------------------------------------------
# Google / xAI helpers (module-level so the static message builders can use them)
# ----------------------------------------------------------------------------------------------

GOOGLE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Vertex AI transport (default for every Google model since 2026-10-25 08:05 UTC, coordinator decision: the Generative
# Language API-key path returns HTTP 402 "prepayment credits depleted" for this project; Vertex AI on the same project
# bills normally).  Same generateContent body; auth is an OAuth access token from `gcloud auth print-access-token`
# (cached 45 min, refreshed on 401), never logged.  The API-key transport stays selectable (LLM(google_transport="apikey"))
# for offline tests.
VERTEX_PROJECT = "<gcp-project-id>"
VERTEX_LOCATION = "global"
VERTEX_URL = ("https://aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/publishers/google/models/"
              "{model}:generateContent")
GOOGLE_TRANSPORT_DEFAULT = os.environ.get("MB_GOOGLE_TRANSPORT", "vertex")   # "vertex" | "apikey"
VERTEX_TOKEN_TTL_S = 45 * 60
# After a failed gcloud token fetch, Google calls raise the same 401 immediately for this long instead of each running
# gcloud under the token lock (Builder 6, 2026-10-26: the box's OAuth refresh failed with a 503 from the metadata server).
VERTEX_AUTH_RETRY_S = 30.0
XAI_BASE_URL = "https://api.x.ai/v1"
XAI_TIMEOUT_S = 240.0    # per-call; single calls of 600-960 s dominated the precompute estimate (decision 2026-10-25 10:58 UTC)
XAI_TIMEOUT_ENV = "MB_XAI_TIMEOUT_S"   # overrides XAI_TIMEOUT_S for a new process (Builder 7: lengthen it for xAI-bound tail passes)
_xai_timeout_warned = False


def xai_timeout_s() -> float:
    """Per-call xAI timeout: MB_XAI_TIMEOUT_S (positive finite float seconds) if set, else XAI_TIMEOUT_S.
    An unparsable or non-positive value falls back to the default with one stderr warning per process."""
    global _xai_timeout_warned
    raw = os.environ.get(XAI_TIMEOUT_ENV)
    if raw is None:
        return XAI_TIMEOUT_S
    try:
        t = float(raw)
    except ValueError:
        t = 0.0
    if 0.0 < t < float("inf"):
        return t
    if not _xai_timeout_warned:
        print(f"warning: {XAI_TIMEOUT_ENV}={raw!r} is not a positive number of seconds; using {XAI_TIMEOUT_S}", file=sys.stderr)
        _xai_timeout_warned = True
    return XAI_TIMEOUT_S
_RETRY_STATUSES = (429, 500, 502, 503, 504, 529)
# Gemini 2.5 has no thinkingLevel; map effort to a thinkingBudget instead
_GEMINI_25_BUDGET = {"low": 1024, "medium": 8192, "high": 24576}
# xAI model ids that rejected reasoning_effort with a 400 (learned at runtime; the call is retried without it)
XAI_NO_REASONING_EFFORT: set[str] = set()
# Gemini functionCall parts keyed by our ToolCall.id (the API id when given, else a synthesised "gc<n>"),
# so the functionResponse can carry back the name and the exact API id.
_GOOGLE_CALLS: dict[str, dict] = {}
_google_ids = itertools.count(1)


class GoogleAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code


def _strip_schema(schema: Any) -> Any:
    """Recursively drop JSON-schema keywords Gemini's function declarations reject (keeps 'required')."""
    if isinstance(schema, dict):
        return {k: _strip_schema(v) for k, v in schema.items() if k not in ("additionalProperties", "$schema")}
    if isinstance(schema, list):
        return [_strip_schema(v) for v in schema]
    return schema


def _google_contents(messages: list) -> list:
    """Accept native Gemini contents or the {"role","content"} shorthand used by single-turn callers."""
    out = []
    for m in messages:
        if "parts" in m:
            out.append(m)
        else:
            out.append({"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]})
    return out


def _google_function_response(cid: str, txt: str) -> dict:
    fc = _GOOGLE_CALLS.get(cid, {"name": cid})
    fr: dict[str, Any] = {"name": fc["name"], "response": {"result": txt}}
    if fc.get("id"):
        fr["id"] = fc["id"]
    return {"functionResponse": fr}


def parse_google_response(data: dict, spec: ModelSpec) -> LLMResponse:
    cand = (data.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if "text" in p and not p.get("thought"))
    calls = []
    for p in parts:
        fc = p.get("functionCall")
        if fc:
            cid = fc.get("id") or f"gc{next(_google_ids)}"
            _GOOGLE_CALLS[cid] = fc
            calls.append(ToolCall(id=cid, name=fc["name"], args=dict(fc.get("args") or {})))
    finish = cand.get("finishReason") or ""
    if calls:
        stop = "tool_use"
    else:
        stop = {"STOP": "end_turn", "MAX_TOKENS": "max_tokens", "SAFETY": "refusal", "PROHIBITED_CONTENT": "refusal",
                "BLOCKLIST": "refusal", "RECITATION": "refusal"}.get(finish, finish.lower())
    um = data.get("usageMetadata") or {}
    prompt = um.get("promptTokenCount") or 0
    cached = um.get("cachedContentTokenCount") or 0          # included in promptTokenCount; billed at ~0.1x
    in_equiv = int((prompt - cached) + 0.1 * cached)
    out = (um.get("candidatesTokenCount") or 0) + (um.get("thoughtsTokenCount") or 0)
    # the model's own parts (incl. thoughtSignature) go back verbatim; Gemini 3+ validates signatures on tool calls
    raw = {"role": "model", "parts": parts or [{"text": ""}]}
    return LLMResponse(text=text, tool_calls=calls, stop_reason=stop, in_tokens=in_equiv, out_tokens=out, latency=0.0,
                       raw_assistant_message=raw, provider="google", model_id=spec.model_id)

# ----------------------------------------------------------------------------------------------
# Client
# ----------------------------------------------------------------------------------------------

class LLM:
    """One shared client per process.  Concurrency is limited per provider with semaphores."""

    def __init__(self, anthropic_concurrency: int = 24, openai_concurrency: int = 32, log_path: Optional[str] = None,
                 google_concurrency: int = 24, xai_concurrency: int = 24, google_transport: Optional[str] = None):
        self.google_transport = google_transport or GOOGLE_TRANSPORT_DEFAULT
        assert self.google_transport in ("vertex", "apikey"), self.google_transport
        self._vertex_tok: Optional[str] = None
        self._vertex_token_t: float = 0.0
        self._vertex_fail_t: float = -1e9
        self._vertex_lock = asyncio.Lock()
        self.ac = anthropic.AsyncAnthropic(max_retries=3, timeout=600.0)
        self.oc = openai.AsyncOpenAI(max_retries=3, timeout=600.0)
        self.gc = httpx.AsyncClient(timeout=600.0)
        self._xc: Optional[openai.AsyncOpenAI] = None     # created on first use (needs XAI_API_KEY)
        self.sem = {"anthropic": asyncio.Semaphore(anthropic_concurrency), "openai": asyncio.Semaphore(openai_concurrency),
                    "google": asyncio.Semaphore(google_concurrency), "xai": asyncio.Semaphore(xai_concurrency)}
        self.log_path = log_path
        self.totals = {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "errors": 0}
        self.by_tag: dict[str, dict] = {}
        self.auth_failures: dict[str, int] = {}     # provider -> calls that failed on authentication (never retried)
        self._lock = asyncio.Lock()

    @property
    def xc(self) -> openai.AsyncOpenAI:
        if self._xc is None:
            self._xc = openai.AsyncOpenAI(api_key=os.environ["XAI_API_KEY"], base_url=XAI_BASE_URL, max_retries=3, timeout=xai_timeout_s())
        return self._xc

    # -- accounting ---------------------------------------------------------------------------
    async def _account(self, resp: LLMResponse, tag: str):
        async with self._lock:
            self.totals["calls"] += 1
            self.totals["in"] += resp.in_tokens
            self.totals["out"] += resp.out_tokens
            self.totals["cost"] += resp.cost
            bt = self.by_tag.setdefault(tag, {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "errors": 0})
            bt["calls"] += 1; bt["in"] += resp.in_tokens; bt["out"] += resp.out_tokens; bt["cost"] += resp.cost
            if self.log_path:
                with open(self.log_path, "a") as f:
                    f.write(json.dumps({"t": time.time(), "tag": tag, "model": resp.model_id, "in": resp.in_tokens,
                                        "out": resp.out_tokens, "cost": round(resp.cost, 6), "latency": round(resp.latency, 2),
                                        "stop": resp.stop_reason}) + "\n")

    async def _note_auth_failure(self, provider: str) -> None:
        async with self._lock:
            self.auth_failures[provider] = self.auth_failures.get(provider, 0) + 1

    # -- tool schema conversion -------------------------------------------------------------------
    @staticmethod
    def _anthropic_tools(tools):
        out = []
        for t in tools:
            schema = dict(t["input_schema"])
            schema.setdefault("additionalProperties", False)
            out.append({"name": t["name"], "description": t["description"], "input_schema": schema})
        return out

    @staticmethod
    def _openai_tools(tools):
        out = []
        for t in tools:
            schema = dict(t["input_schema"])
            schema.setdefault("additionalProperties", False)
            out.append({"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": schema}})
        return out

    @staticmethod
    def _google_tools(tools):
        return [{"name": t["name"], "description": t["description"], "parameters": _strip_schema(t["input_schema"])} for t in tools]

    # -- main entry ------------------------------------------------------------------------------
    async def chat(self, spec: ModelSpec, system: Optional[str], messages: list, tools: Optional[list] = None,
                   max_tokens: Optional[int] = None, tag: str = "", temperature: Optional[float] = None,
                   max_attempts: int = 7) -> LLMResponse:
        """messages: provider-native history (list of dicts).  Returns unified response."""
        max_tokens = max_tokens or spec.max_tokens
        attempt = 0
        while True:
            attempt += 1
            t0 = time.time()
            try:
                async with self.sem[spec.provider]:
                    if spec.provider == "anthropic":
                        resp = await self._anthropic(spec, system, messages, tools, max_tokens, temperature)
                    elif spec.provider == "google":
                        resp = await self._google(spec, system, messages, tools, max_tokens, temperature)
                    elif spec.provider == "xai":
                        resp = await self._xai(spec, system, messages, tools, max_tokens, temperature)
                    else:
                        resp = await self._openai(spec, system, messages, tools, max_tokens, temperature)
                resp.latency = time.time() - t0
                await self._account(resp, tag)
                return resp
            except (anthropic.AuthenticationError, openai.AuthenticationError):
                await self._note_auth_failure(spec.provider)
                raise
            except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError, anthropic.APITimeoutError,
                    openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError, openai.APITimeoutError,
                    httpx.TransportError, GoogleAPIError) as e:
                if isinstance(e, GoogleAPIError) and e.status_code not in _RETRY_STATUSES:
                    if e.status_code in (401, 403):
                        await self._note_auth_failure(spec.provider)
                    raise
                async with self._lock:
                    self.totals["errors"] += 1
                    bt = self.by_tag.setdefault(tag, {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "errors": 0})
                    bt["errors"] = bt.get("errors", 0) + 1
                if attempt >= max_attempts:
                    raise
                delay = min(60.0, (2 ** attempt) + random.uniform(0, 2))
                await asyncio.sleep(delay)
            except anthropic.APIStatusError as e:
                # 529 overloaded comes through here on some SDK versions
                if getattr(e, "status_code", 0) in (429, 500, 502, 503, 529) and attempt < max_attempts:
                    await asyncio.sleep(min(60.0, (2 ** attempt) + random.uniform(0, 2)))
                    continue
                raise

    async def _anthropic(self, spec, system, messages, tools, max_tokens, temperature) -> LLMResponse:
        kw: dict[str, Any] = dict(model=spec.model_id, max_tokens=max_tokens, messages=messages)
        if tools:
            kw["cache_control"] = {"type": "ephemeral"}
        if system:
            kw["system"] = system
        if spec.effort:
            kw["output_config"] = {"effort": spec.effort}
        if tools:
            kw["tools"] = self._anthropic_tools(tools)
            kw["tool_choice"] = {"type": "auto"}
        # temperature is not sent to Anthropic (rejected by SDK 2.x on this path); default sampling gives independent draws
        r = await self.ac.messages.create(**kw)
        text = "".join(b.text for b in r.content if b.type == "text")
        calls = [ToolCall(id=b.id, name=b.name, args=dict(b.input)) for b in r.content if b.type == "tool_use"]
        cr = getattr(r.usage, "cache_read_input_tokens", 0) or 0
        cw = getattr(r.usage, "cache_creation_input_tokens", 0) or 0
        # bill cache reads at 0.1x and cache writes at 1.25x by folding them into an input-token equivalent
        in_equiv = int(r.usage.input_tokens + 0.1 * cr + 1.25 * cw)
        return LLMResponse(text=text, tool_calls=calls, stop_reason=r.stop_reason or "", in_tokens=in_equiv,
                           out_tokens=r.usage.output_tokens, latency=0.0,
                           raw_assistant_message={"role": "assistant", "content": [b.model_dump() for b in r.content]},
                           provider="anthropic", model_id=spec.model_id)

    async def _openai(self, spec, system, messages, tools, max_tokens, temperature) -> LLMResponse:
        msgs = ([{"role": "system", "content": system}] if system else []) + messages
        kw: dict[str, Any] = dict(model=spec.model_id, messages=msgs)
        reasoning = spec.model_id.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4"))   # reasoning models take max_completion_tokens
        if reasoning:
            kw["max_completion_tokens"] = max_tokens
            if spec.effort:
                kw["reasoning_effort"] = spec.effort
        else:
            kw["max_tokens"] = max_tokens
            if temperature is not None:
                kw["temperature"] = temperature
        if tools:
            kw["tools"] = self._openai_tools(tools)
            kw["tool_choice"] = "auto"
        r = await self.oc.chat.completions.create(**kw)
        m = r.choices[0].message
        text = m.content or ""
        calls = []
        for tc in (m.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_invalid_json": tc.function.arguments}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, args=args))
        raw = {"role": "assistant", "content": m.content}
        if m.tool_calls:
            raw["tool_calls"] = [{"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in m.tool_calls]
        u = r.usage
        return LLMResponse(text=text, tool_calls=calls, stop_reason=r.choices[0].finish_reason or "", in_tokens=u.prompt_tokens,
                           out_tokens=u.completion_tokens, latency=0.0, raw_assistant_message=raw, provider="openai", model_id=spec.model_id)

    async def _google(self, spec, system, messages, tools, max_tokens, temperature) -> LLMResponse:
        gen: dict[str, Any] = {"maxOutputTokens": max_tokens}
        if temperature is not None:
            gen["temperature"] = temperature
        if spec.effort:
            if spec.model_id.startswith("gemini-2.5"):
                gen["thinkingConfig"] = {"thinkingBudget": _GEMINI_25_BUDGET[spec.effort]}
            else:
                gen["thinkingConfig"] = {"thinkingLevel": spec.effort}
        body: dict[str, Any] = {"contents": _google_contents(messages), "generationConfig": gen}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            body["tools"] = [{"functionDeclarations": self._google_tools(tools)}]
        if self.google_transport == "vertex":
            r = await self._vertex_post(spec.model_id, body)
        else:
            r = await self.gc.post(GOOGLE_URL.format(model=spec.model_id), json=body,
                                   headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"], "Content-Type": "application/json"})
        if r.status_code != 200:
            raise GoogleAPIError(r.status_code, r.text[:600])   # error bodies never echo the key/token (they travel in a header)
        return parse_google_response(r.json(), spec)

    # -- Vertex AI transport -----------------------------------------------------------------------
    @staticmethod
    def _gcloud_access_token() -> str:
        """Fresh OAuth access token from the gcloud credential on this box.  Never printed or logged.  Every failure
        (non-zero exit, empty output, timeout, gcloud missing) is a GoogleAPIError 401 "gcloud auth print-access-token
        failed ...", which the retry loops raise at once instead of retrying (its output never enters the message)."""
        try:
            r = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True, timeout=60)
        except (subprocess.TimeoutExpired, OSError) as e:
            raise GoogleAPIError(401, "gcloud auth print-access-token failed (%s)" % type(e).__name__) from None
        tok = r.stdout.strip()
        if r.returncode != 0 or not tok:
            raise GoogleAPIError(401, "gcloud auth print-access-token failed (rc=%d)" % r.returncode)
        return tok

    async def _vertex_token(self, force: bool = False) -> str:
        async with self._vertex_lock:
            if force or self._vertex_tok is None or time.time() - self._vertex_token_t > VERTEX_TOKEN_TTL_S:
                if time.time() - self._vertex_fail_t < VERTEX_AUTH_RETRY_S:
                    raise GoogleAPIError(401, "gcloud auth print-access-token failed within the last %ds; not retried" % VERTEX_AUTH_RETRY_S)
                try:
                    self._vertex_tok = await asyncio.to_thread(self._gcloud_access_token)
                except GoogleAPIError:
                    self._vertex_fail_t = time.time()
                    raise
                self._vertex_token_t = time.time()
            return self._vertex_tok

    async def _vertex_post(self, model_id: str, body: dict):
        url = VERTEX_URL.format(project=VERTEX_PROJECT, location=VERTEX_LOCATION, model=model_id)
        tok = await self._vertex_token()
        r = await self.gc.post(url, json=body, headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
        if r.status_code == 401:            # expired/revoked token: refresh once and retry
            tok = await self._vertex_token(force=True)
            r = await self.gc.post(url, json=body, headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
        return r

    async def _xai(self, spec, system, messages, tools, max_tokens, temperature) -> LLMResponse:
        msgs = ([{"role": "system", "content": system}] if system else []) + messages
        kw: dict[str, Any] = dict(model=spec.model_id, messages=msgs, max_tokens=max_tokens)
        if temperature is not None:
            kw["temperature"] = temperature
        if tools:
            kw["tools"] = self._openai_tools(tools)
            kw["tool_choice"] = "auto"
        if spec.effort and spec.model_id not in XAI_NO_REASONING_EFFORT:
            try:
                r = await self.xc.chat.completions.create(**kw, reasoning_effort=spec.effort)
            except openai.BadRequestError as e:
                if "reasoning" not in str(e).replace("_", "").lower():   # xAI reports "reasoningEffort" (camelCase) on some models
                    raise
                XAI_NO_REASONING_EFFORT.add(spec.model_id)
                r = await self.xc.chat.completions.create(**kw)
        else:
            r = await self.xc.chat.completions.create(**kw)
        m = r.choices[0].message
        calls = []
        for tc in (m.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_invalid_json": tc.function.arguments}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, args=args))
        raw = {"role": "assistant", "content": m.content}
        if m.tool_calls:
            raw["tool_calls"] = [{"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in m.tool_calls]
        u = r.usage
        cached = int(getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0)
        in_equiv = int((u.prompt_tokens - cached) + 0.1 * cached)
        # reasoning tokens are billed as output; count them once whether or not completion_tokens already includes them
        out = max(u.completion_tokens, (u.total_tokens or 0) - u.prompt_tokens)
        return LLMResponse(text=m.content or "", tool_calls=calls, stop_reason=r.choices[0].finish_reason or "", in_tokens=in_equiv,
                           out_tokens=out, latency=0.0, raw_assistant_message=raw, provider="xai", model_id=spec.model_id)

    # -- helpers to build the tool-result turn in each provider's format ---------------------------
    @staticmethod
    def tool_results_message(provider: str, results: list[tuple[str, str]]) -> list:
        """results: list of (tool_call_id, result_text). Returns list of messages to append."""
        if provider == "anthropic":
            return [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": cid, "content": txt} for cid, txt in results]}]
        if provider == "google":
            return [{"role": "user", "parts": [_google_function_response(cid, txt) for cid, txt in results]}]
        return [{"role": "tool", "tool_call_id": cid, "content": txt} for cid, txt in results]

    @staticmethod
    def user_message(provider: str, text: str) -> dict:
        if provider == "google":
            return {"role": "user", "parts": [{"text": text}]}
        return {"role": "user", "content": text}


# ----------------------------------------------------------------------------------------------
# Conversation abstraction (provider-specific storage) for multi-turn tool use
#   anthropic: full message list, assistant content appended verbatim (thinking blocks preserved)
#   openai:    Responses API with server-side state (previous_response_id); only new items are sent
#   google:    full contents list, model parts appended verbatim (thought signatures preserved)
#   xai:       full chat-completions message list (user/assistant/tool)
# ----------------------------------------------------------------------------------------------

class Conversation:
    def __init__(self, provider: str):
        self.provider = provider
        self.messages: list = []        # anthropic/google/xai: full history; openai: pending input items for the next call
        self.previous_response_id: Optional[str] = None

    def add_user(self, text: str):
        self.messages.append(LLM.user_message(self.provider, text))

    def add_assistant(self, resp: "LLMResponse"):
        if self.provider == "openai":
            self.previous_response_id = resp.raw_assistant_message["response_id"]
            self.messages = []          # consumed server-side
        else:
            self.messages.append(resp.raw_assistant_message)

    def add_tool_results(self, results: list[tuple[str, str]]):
        if self.provider == "openai":
            for cid, txt in results:
                self.messages.append({"type": "function_call_output", "call_id": cid, "output": txt})
        else:
            self.messages.extend(LLM.tool_results_message(self.provider, results))


async def _openai_responses(self: "LLM", spec: ModelSpec, system: Optional[str], conv: Conversation, tools: Optional[list],
                            max_tokens: int) -> LLMResponse:
    kw: dict[str, Any] = dict(model=spec.model_id, input=conv.messages, max_output_tokens=max_tokens, store=True)
    if system:
        kw["instructions"] = system
    if spec.effort:
        kw["reasoning"] = {"effort": spec.effort}
    if tools:
        kw["tools"] = [{"type": "function", "name": t["name"], "description": t["description"],
                        "parameters": {**t["input_schema"], "additionalProperties": False}, "strict": False} for t in tools]
        kw["tool_choice"] = "auto"
    if conv.previous_response_id:
        kw["previous_response_id"] = conv.previous_response_id
    r = await self.oc.responses.create(**kw)
    text_parts, calls, refusal = [], [], False
    for item in r.output:
        if item.type == "message":
            for c in item.content:
                if c.type == "output_text":
                    text_parts.append(c.text)
                elif c.type == "refusal":
                    refusal = True
                    text_parts.append(getattr(c, "refusal", ""))
        elif item.type == "function_call":
            try:
                args = json.loads(item.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_invalid_json": item.arguments}
            calls.append(ToolCall(id=item.call_id, name=item.name, args=args))
    stop = "refusal" if refusal else ("tool_use" if calls else (r.status or "completed"))
    u = r.usage
    cached = 0
    try:
        cached = int(getattr(u.input_tokens_details, "cached_tokens", 0) or 0)
    except AttributeError:
        cached = 0
    # OpenAI bills cached input at a discount (90% off for the GPT-5 family); fold into an input-token equivalent
    in_equiv = int((u.input_tokens - cached) + 0.1 * cached)
    return LLMResponse(text="".join(text_parts), tool_calls=calls, stop_reason=stop, in_tokens=in_equiv,
                       out_tokens=u.output_tokens, latency=0.0, raw_assistant_message={"response_id": r.id},
                       provider="openai", model_id=spec.model_id)


async def chat_conv(self: "LLM", spec: ModelSpec, system: Optional[str], conv: Conversation, tools: Optional[list] = None,
                    max_tokens: Optional[int] = None, tag: str = "", max_attempts: int = 7) -> LLMResponse:
    """Multi-turn step on a Conversation. The caller appends the response with conv.add_assistant(resp)."""
    max_tokens = max_tokens or spec.max_tokens
    attempt = 0
    while True:
        attempt += 1
        t0 = time.time()
        try:
            async with self.sem[spec.provider]:
                if spec.provider == "anthropic":
                    resp = await self._anthropic(spec, system, conv.messages, tools, max_tokens, None)
                elif spec.provider == "google":
                    resp = await self._google(spec, system, conv.messages, tools, max_tokens, None)
                elif spec.provider == "xai":
                    resp = await self._xai(spec, system, conv.messages, tools, max_tokens, None)
                else:
                    resp = await _openai_responses(self, spec, system, conv, tools, max_tokens)
            resp.latency = time.time() - t0
            await self._account(resp, tag)
            return resp
        except (anthropic.AuthenticationError, openai.AuthenticationError):
            await self._note_auth_failure(spec.provider)
            raise
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError, anthropic.APITimeoutError,
                openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError, openai.APITimeoutError,
                httpx.TransportError, GoogleAPIError) as e:
            if isinstance(e, GoogleAPIError) and e.status_code not in _RETRY_STATUSES:
                if e.status_code in (401, 403):
                    await self._note_auth_failure(spec.provider)
                raise
            async with self._lock:
                self.totals["errors"] += 1
                bt = self.by_tag.setdefault(tag, {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "errors": 0})
                bt["errors"] = bt.get("errors", 0) + 1
            if attempt >= max_attempts:
                raise
            await asyncio.sleep(min(60.0, (2 ** attempt) + random.uniform(0, 2)))
        except anthropic.APIStatusError as e:
            if getattr(e, "status_code", 0) in (429, 500, 502, 503, 529) and attempt < max_attempts:
                await asyncio.sleep(min(60.0, (2 ** attempt) + random.uniform(0, 2)))
                continue
            raise

LLM.chat_conv = chat_conv


def load_keys_from_env_file(path: str = "/path/to/model-keys.env") -> None:
    """Load KEY=VALUE lines into os.environ without printing anything."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() and k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip().strip('"').strip("'")
