"""Memory probe for the panel precompute (Builder 5).  Offline: no key file is read and no network is used.

Two reproduction levels, both through the real `metabench.panel.precompute`:
  level "fake":  a `metabench.llm.LLM` whose four provider methods are replaced by fakes that return long
                 math-style responses (or raise a retryable error), so the real `chat` retry/accounting loop runs;
  level "mock":  the real `LLM` with every provider client over an httpx MockTransport that serves provider-shaped
                 JSON bodies (and HTTP 429s), so SDK parsing, httpx and the exception objects all run.
Responses carry 5,000-10,000 "tokens" of reasoning text (about 4 characters per token) and end with an
`Answer:` line that is correct, wrong, equivalent-but-different (sympy path) or missing (parse failure).
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import resource
import sys
import time
import tracemalloc
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ANTHROPIC_API_KEY", "fake-offline")   # the SDK constructors insist on a key; never a real one
os.environ.setdefault("OPENAI_API_KEY", "fake-offline")
os.environ.setdefault("XAI_API_KEY", "fake-offline")

import anthropic  # noqa: E402
import httpx2 as httpx  # noqa: E402
import openai  # noqa: E402

if os.environ.get("MB_GRADERS_FILE"):          # before/after comparison: load another graders.py as metabench.graders
    import importlib.util
    import metabench
    _spec = importlib.util.spec_from_file_location("metabench.graders", os.environ["MB_GRADERS_FILE"])
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["metabench.graders"] = _mod
    _spec.loader.exec_module(_mod)
    metabench.graders = _mod

from metabench import llm as llm_mod  # noqa: E402
from metabench import panel  # noqa: E402
from metabench.llm import LLM, LLMResponse, GoogleAPIError  # noqa: E402

EXPR_KEYS = ["\\frac{4 \\pi}{3}+\\sqrt{3}", "\\frac{5}{16}", "\\frac{9 \\sqrt{23}}{23}", "\\frac{1+\\sqrt{31}}{2}", "1+\\sqrt{3}",
             "8\\sqrt{10}", "\\frac{-1+\\sqrt{17}}{2}, \\frac{-1-\\sqrt{17}}{2}", "\\sqrt{38}-3", "\\dfrac{32}{7}", "\\frac{157}{40}",
             "248/517", "\\frac{23-5 \\sqrt{21}}{10}", "1-\\frac{2}{\\pi}", "\\frac{9\\sqrt{30}}{4}", "\\dfrac{1}{512}"]
# answer-line variants exercising every grader branch: exact, int, sympy fallback (equivalent and not), parse failure
EXPR_VARIANTS = ["{k}", "$\\boxed{{{k}}}$", "{k} + 0", "\\frac{{1}}{{3}}", "2\\sqrt{{2}}", "x^2 + 1", "1.4142135"]


def synthetic_math_pool(n: int, seed: int = 5) -> dict[str, dict]:
    rng = random.Random(seed)
    pool = {}
    for i in range(n):
        iid = f"X{i+1:05d}"
        if rng.random() < 0.76:
            kt, ans = "integer", str(rng.randint(0, 999))
        else:
            kt, ans = "expression", rng.choice(EXPR_KEYS)
        pool[iid] = {"id": iid, "domain": "math", "question": f"Problem {i}: compute the value of the quantity described here, "
                     f"a {rng.choice(['triangle', 'sequence', 'polynomial', 'lattice'])} with parameter {rng.randint(2, 99)}.",
                     "options": [], "answer": ans, "key_type": kt, "category": "synthetic"}
    return pool


_FILLER = ["Let the quantity be $x$. By the law of cosines we have $x^2 = a^2 + b^2 - 2ab\\cos\\theta$, so after substituting ",
           "Consider the generating function $\\sum_{n\\ge 0} a_n t^n$; the recurrence gives $(1 - t - t^2) A(t) = 1$, hence ",
           "We check small cases: for $n = 1, 2, 3$ the values are $1, 3, 8$ respectively, which suggests the closed form ",
           "Expanding the product and collecting terms of equal degree, the coefficient of $t^k$ equals $\\binom{n}{k} 2^{n-k}$, so ",
           "Wait, let me recompute that step. The denominator should be $\\sqrt{23}$, not $23$, because the vector has norm "]


BIG_RATE = {"rate": 0.0}     # fraction of answers that are a large power 2^{N}, N in [5e7, 6e7] (each about 6-7 MB as an integer)


def long_math_text(rng: random.Random, item: dict, n_tokens: int, uid: int) -> str:
    """About 4 chars per token of reasoning filler, unique per call, ending in an Answer line (or not)."""
    parts = [f"[trace {uid}] "]
    size = 0
    target = 4 * n_tokens
    while size < target:
        s = rng.choice(_FILLER) + str(rng.randint(1, 10**6)) + ". "
        parts.append(s); size += len(s)
    u = rng.random()
    k = item["answer"]
    if rng.random() < BIG_RATE["rate"]:
        tail = f"Answer: 2^{{{rng.randint(50_000_000, 60_000_000)}}}"                     # large power (sympy fallback)
    elif u < 0.08:
        tail = "I am not able to finish this computation in the space available."          # parse failure
    elif item["key_type"] == "integer":
        tail = "Answer: " + (k if u < 0.6 else str(int(k) + rng.randint(1, 50)))
    else:
        tail = "Answer: " + rng.choice(EXPR_VARIANTS).format(k=k)
    parts.append("\n\n" + tail)
    return "".join(parts)


def _fast_asyncio():
    """A module-shaped stand-in for asyncio inside metabench.llm whose sleep is instantaneous (retry backoff)."""
    ns = types.ModuleType("asyncio_fast")
    ns.__dict__.update(asyncio.__dict__)

    async def _sleep(_delay, *a, **k):
        await asyncio.sleep(0)
    ns.sleep = _sleep
    return ns


class FakeProviderLLM(LLM):
    """Real LLM.chat (retry loop, semaphores, accounting, per-call log) over fake provider methods."""

    def __init__(self, error_rate: float, tokens=(5000, 10000), seed: int = 11, **kw):
        super().__init__(**kw)
        self.rng = random.Random(seed)
        self.error_rate = error_rate
        self.tokens = tokens
        self.uid = 0

    def _fake(self, spec, messages, provider):
        self.uid += 1
        if self.rng.random() < self.error_rate:
            if provider == "google":
                raise GoogleAPIError(429, json.dumps({"error": {"code": 429, "message": "Resource exhausted " + "x" * 400}}))
            req = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
            resp = httpx.Response(429, request=req, json={"error": {"message": "rate limited", "type": "rate_limit_error"}})
            if provider == "anthropic":
                raise anthropic.InternalServerError("overloaded", response=httpx.Response(529, request=req, json={"error": {"type": "overloaded_error"}}), body=None)
            raise openai.RateLimitError("rate limited", response=resp, body=None)
        item_text = messages[0]["content"]
        n_tok = self.rng.randint(*self.tokens)
        text = long_math_text(self.rng, self._item_for(item_text), n_tok, self.uid)
        return LLMResponse(text=text, tool_calls=[], stop_reason="end_turn", in_tokens=len(item_text) // 4, out_tokens=n_tok,
                           latency=0.0, raw_assistant_message={"role": "assistant", "content": text}, provider=provider, model_id=spec.model_id)

    def _item_for(self, prompt: str) -> dict:
        return self._items[prompt.split("Problem ")[1].split(":")[0]]

    def bind_pool(self, pool: dict[str, dict]) -> None:
        self._items = {it["question"].split("Problem ")[1].split(":")[0]: it for it in pool.values()}

    async def _anthropic(self, spec, system, messages, tools, max_tokens, temperature):
        await asyncio.sleep(0)
        return self._fake(spec, messages, "anthropic")

    async def _openai(self, spec, system, messages, tools, max_tokens, temperature):
        await asyncio.sleep(0)
        return self._fake(spec, messages, "openai")

    async def _google(self, spec, system, messages, tools, max_tokens, temperature):
        await asyncio.sleep(0)
        return self._fake(spec, messages, "google")

    async def _xai(self, spec, system, messages, tools, max_tokens, temperature):
        await asyncio.sleep(0)
        return self._fake(spec, messages, "xai")


class MockTransportLLM(LLM):
    """Real LLM with every provider client over an httpx MockTransport serving provider-shaped bodies and 429s."""

    def __init__(self, error_rate: float, tokens=(5000, 10000), seed: int = 11, **kw):
        kw.setdefault("google_transport", "apikey")
        super().__init__(**kw)
        os.environ.setdefault("GEMINI_API_KEY", "fake-offline")
        self.rng = random.Random(seed)
        self.error_rate = error_rate
        self.tokens = tokens
        self.uid = 0
        tr = httpx.MockTransport(self._handle)
        self.ac = anthropic.AsyncAnthropic(max_retries=0, timeout=600.0, http_client=httpx.AsyncClient(transport=tr))
        self.oc = openai.AsyncOpenAI(max_retries=0, timeout=600.0, http_client=httpx.AsyncClient(transport=tr))
        self._xc = openai.AsyncOpenAI(api_key="fake-offline", base_url=llm_mod.XAI_BASE_URL, max_retries=0, timeout=240.0,
                                      http_client=httpx.AsyncClient(transport=tr))
        self.gc = httpx.AsyncClient(timeout=600.0, transport=tr)

    def bind_pool(self, pool: dict[str, dict]) -> None:
        self._items = {it["question"].split("Problem ")[1].split(":")[0]: it for it in pool.values()}

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.uid += 1
        body = json.loads(request.content)
        url = str(request.url)
        if "generateContent" in url:
            provider, prompt, model = "google", body["contents"][0]["parts"][0]["text"], url.rsplit("/", 1)[1].split(":")[0]
        elif "anthropic" in url:
            provider, prompt, model = "anthropic", body["messages"][0]["content"], body["model"]
        else:
            provider, prompt, model = "openai", body["messages"][0]["content"], body["model"]
        if self.rng.random() < self.error_rate:
            if provider == "google":
                return httpx.Response(429, json={"error": {"code": 429, "message": "Resource exhausted " + "x" * 400, "status": "RESOURCE_EXHAUSTED"}})
            if provider == "anthropic":
                return httpx.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
            return httpx.Response(429, json={"error": {"message": "Rate limit reached", "type": "rate_limit_error", "code": "rate_limit_exceeded"}})
        item = self._items[prompt.split("Problem ")[1].split(":")[0]]
        n_tok = self.rng.randint(*self.tokens)
        text = long_math_text(self.rng, item, n_tok, self.uid)
        if provider == "google":
            data = {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}],
                    "usageMetadata": {"promptTokenCount": 80, "candidatesTokenCount": n_tok // 3, "thoughtsTokenCount": n_tok - n_tok // 3}}
        elif provider == "anthropic":
            data = {"id": f"msg_{self.uid}", "type": "message", "role": "assistant", "model": model,
                    "content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "stop_sequence": None,
                    "usage": {"input_tokens": 80, "output_tokens": n_tok}}
        else:
            data = {"id": f"chatcmpl-{self.uid}", "object": "chat.completion", "created": int(time.time()), "model": model,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": text, "reasoning_content": text[: len(text) // 2]},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 80, "completion_tokens": n_tok, "total_tokens": 80 + n_tok}}
        return httpx.Response(200, json=data)


def rss_mb() -> float:
    with open("/proc/self/statm") as f:
        return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6


def maxrss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e3


def make_llm(level: str, error_rate: float, log_path: str | None, **kw):
    cls = FakeProviderLLM if level == "fake" else MockTransportLLM
    return cls(error_rate=error_rate, log_path=log_path, anthropic_concurrency=40, openai_concurrency=56, google_concurrency=32,
               xai_concurrency=64, **kw)


async def _sampler(samples: list, counter: dict, every_s: float):
    t0 = time.time()
    while True:
        samples.append((round(time.time() - t0, 1), counter.get("n", 0), round(rss_mb(), 1)))
        await asyncio.sleep(every_s)


def run_probe(n_items: int, k: int, concurrency: int, out_path: Path, level: str = "fake", error_rate: float = 0.05,
              snapshot: bool = False, every_s: float = 2.0, log_calls: bool = True, specs=None, big_rate: float = 0.0) -> dict:
    """One precompute over the synthetic pool; returns RSS samples, peak RSS and (optionally) tracemalloc top sites."""
    BIG_RATE["rate"] = big_rate
    prev_panel = panel.ACTIVE["name"]
    panel.set_active("confirmatory")
    specs = specs or list(panel.PANEL)
    pool = synthetic_math_pool(n_items)
    saved = llm_mod.asyncio
    llm_mod.asyncio = _fast_asyncio()
    try:
        llm = make_llm(level, error_rate, str(out_path.with_name("llm_calls.jsonl")) if log_calls else None)
        llm.bind_pool(pool)
        samples: list = []
        counter: dict = {}
        if snapshot:
            tracemalloc.start(12)

        async def main():
            # progress counter: wrap the output-file size, which precompute appends to row by row
            async def count():
                while True:
                    try:
                        with open(out_path) as f:
                            counter["n"] = sum(1 for _ in f)
                    except FileNotFoundError:
                        counter["n"] = 0
                    await asyncio.sleep(every_s)
            s = asyncio.create_task(_sampler(samples, counter, every_s))
            c = asyncio.create_task(count())
            snap0 = tracemalloc.take_snapshot() if snapshot else None
            t0 = time.time()
            counts = await panel.precompute(pool, specs, k, out_path, llm, concurrency=concurrency, max_tokens=4096)
            el = time.time() - t0
            s.cancel(); c.cancel()
            top = None
            if snapshot:
                snap1 = tracemalloc.take_snapshot()
                stats = snap1.compare_to(snap0, "traceback")
                top = []
                for st in stats[:12]:
                    top.append({"size_mb": round(st.size_diff / 1e6, 1), "count": st.count_diff,
                                "trace": [f"{fr.filename.replace(str(ROOT) + '/', '')}:{fr.lineno}" for fr in st.traceback[-6:]]})
                tracemalloc.stop()
            return counts, el, top

        rss_before = rss_mb()
        counts, el, top = asyncio.run(main())
        rows = sum(1 for _ in open(out_path))
        return {"level": level, "rows": rows, "elapsed_s": round(el, 1), "rss_before_mb": round(rss_before, 1), "rss_after_mb": round(rss_mb(), 1),
                "maxrss_mb": round(maxrss_mb(), 1), "counts": counts, "api_errors_total": llm.totals["errors"], "samples": samples, "top": top}
    finally:
        llm_mod.asyncio = saved
        panel.set_active(prev_panel or "pilot")       # leave the process-wide panel as the caller had it (other tests)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", type=int, default=300)
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--concurrency", type=int, default=96)
    ap.add_argument("--level", default="fake", choices=["fake", "mock"])
    ap.add_argument("--error-rate", type=float, default=0.05)
    ap.add_argument("--snapshot", action="store_true")
    ap.add_argument("--big-rate", type=float, default=0.0)
    ap.add_argument("--out", default="/tmp/b5_probe")
    a = ap.parse_args()
    d = Path(a.out); d.mkdir(parents=True, exist_ok=True)
    out = d / f"precompute_{a.level}.jsonl"
    for p in (out, out.with_name("llm_calls.jsonl")):
        if p.exists():
            p.unlink()
    r = run_probe(a.items, a.samples, a.concurrency, out, level=a.level, error_rate=a.error_rate, snapshot=a.snapshot, big_rate=a.big_rate)
    samples = r.pop("samples")
    print(json.dumps(r, indent=1))
    print("t_s,rows,rss_mb")
    for t, n, m in samples[:: max(1, len(samples) // 25)] + samples[-1:]:
        print(f"{t},{n},{m}")
