"""Smoke-test every provider path in metabench.llm with one tiny call and one two-turn tool-calling exchange per model.

Prints only metadata (provider, model id, status, tool-call flag, token counts, latency, reasoning parameter used).
Never prints response text or keys.  Run: .venv/bin/python scripts_smoke_providers.py
"""
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from metabench.interface import t1_tools
from metabench.llm import LLM, Conversation, ModelSpec, XAI_NO_REASONING_EFFORT, load_keys_from_env_file

CANDIDATES = {   # every confirmatory panel / designer / monitor id (override with argv: provider:model_id ...)
    "anthropic": ["claude-fable-5-1", "claude-sonnet-5-5", "claude-opus-5", "claude-sonnet-4-6"],
    "openai": ["gpt-6.1-sol", "gpt-6-luna", "gpt-5.5", "gpt-5.4"],
    "google": ["gemini-3.8-flash", "gemini-4-argon", "gemini-3.1-pro-preview", "gemini-3.5-flash"],
    "xai": ["grok-4.7", "grok-4.5", "grok-4.3", "grok-4.20-0309-reasoning"],
}
if len(sys.argv) > 1:
    CANDIDATES = {}
    for arg in sys.argv[1:]:
        prov, mid = arg.split(":", 1)
        CANDIDATES.setdefault(prov, []).append(mid)
PING = {"name": "ping", "description": "Ping the harness with an integer x. Returns 'pong'.",
        "input_schema": {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}}
KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY")


def _safe(e: Exception) -> str:
    msg = str(e).replace("\n", " ")
    for k in KEYS:                                   # belt and braces: never let a key value reach stdout
        v = os.environ.get(k)
        if v:
            msg = msg.replace(v, "***")
    return msg[:160]


def _reasoning_param(spec: ModelSpec) -> str:
    if spec.provider == "google":
        return "thinkingBudget" if spec.model_id.startswith("gemini-2.5") else f"thinkingLevel={spec.effort}"
    if spec.provider == "xai":
        return "reasoning_effort=rejected" if spec.model_id in XAI_NO_REASONING_EFFORT else f"reasoning_effort={spec.effort}"
    return f"effort={spec.effort}"


async def one(llm: LLM, spec: ModelSpec) -> dict:
    row = {"provider": spec.provider, "model": spec.model_id, "status": "ok", "tool_call": None, "turn2": None,
           "in": 0, "out": 0, "latency": 0.0, "reasoning": None, "t1_schema": None}
    t0 = time.time()
    try:
        r = await llm.chat(spec, None, [{"role": "user", "content": "Reply with the single word OK."}], tag="smoke", max_attempts=2)
        row.update({"in": r.in_tokens, "out": r.out_tokens, "stop": r.stop_reason, "text_ok": r.text.strip().upper().startswith("OK")})
        conv = Conversation(spec.provider)
        conv.add_user("Call the ping tool with x=7. After you receive its result, reply with the single word OK.")
        r1 = await llm.chat_conv(spec, "You are a test harness.", conv, tools=[PING], tag="smoke", max_attempts=2)
        conv.add_assistant(r1)
        row["tool_call"] = bool(r1.tool_calls)
        row["in"] += r1.in_tokens; row["out"] += r1.out_tokens
        if r1.tool_calls:
            conv.add_tool_results([(tc.id, "pong") for tc in r1.tool_calls])
            r2 = await llm.chat_conv(spec, "You are a test harness.", conv, tools=[PING], tag="smoke", max_attempts=2)
            conv.add_assistant(r2)
            row["turn2"] = r2.stop_reason
            row["in"] += r2.in_tokens; row["out"] += r2.out_tokens
        if spec.provider == "google":    # the real T1 tool schemas must be accepted after stripping
            r3 = await llm.chat(spec, None, [{"role": "user", "content": "Reply with the single word OK."}], tools=t1_tools(30),
                                tag="smoke", max_attempts=2)
            row["t1_schema"] = "ok"
            row["in"] += r3.in_tokens; row["out"] += r3.out_tokens
    except Exception as e:
        row["status"] = f"error:{type(e).__name__}"
        row["error"] = _safe(e)
    row["latency"] = round(time.time() - t0, 1)
    row["reasoning"] = _reasoning_param(spec)
    return row


async def main():
    load_keys_from_env_file()
    missing = [k for k in KEYS if not os.environ.get(k)]
    print("keys present:", {k: k not in missing for k in KEYS})
    llm = LLM()
    specs = [ModelSpec(key=f"{p}:{m}", provider=p, model_id=m, effort="low", max_tokens=4096)
             for p, ms in CANDIDATES.items() for m in ms]
    rows = await asyncio.gather(*(one(llm, s) for s in specs))
    cols = ["provider", "model", "status", "tool_call", "turn2", "in", "out", "latency", "reasoning", "t1_schema"]
    print(" | ".join(cols))
    for r in rows:
        print(" | ".join(str(r.get(c)) for c in cols) + (f"  err={r['error']}" if "error" in r else ""))
    print("totals:", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in llm.totals.items()})
    ok = {p for p, ms in CANDIDATES.items() if any(r["status"] == "ok" and r["tool_call"] for r in rows if r["provider"] == p)}
    print("providers with a fully ok model:", sorted(ok))
    return 0 if ok == set(CANDIDATES) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
