"""Factual pool (SimpleQA subset) quality audit, EXPLORATORY.
A: grader false-negative / false-positive rate on random graded rows (two LLM judges: OpenAI + Anthropic).
B: item soundness for items every designer model misses, vs a random sample of discriminating items.
Keys are read from the managed env file and never printed."""
import asyncio
import collections
import json
import random
import sys
from pathlib import Path

import anthropic
import openai

OUT = Path(__file__).parent
POOL = Path("/path/to/metabench/run/pools/factual_qa/pool.jsonl")
PRE = Path("/path/to/metabench/unblinded/WORK_factual/precompute/factual.jsonl")
KEYS = ['fable51', 'opus5', 'sonnet55', 'gpt61sol', 'gpt6luna', 'gpt55', 'gemini4argon', 'gemini31pro',
        'gemini38flash', 'grok47', 'grok45', 'grok43']
OAI_MODEL, ANT_MODEL = "gpt-5.5", "claude-opus-5-5"


def key(name):
    for line in open("/path/to/model-keys.env"):
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"{name} missing")


oai = openai.AsyncOpenAI(api_key=key("OPENAI_API_KEY"), timeout=600, max_retries=4)
ant = anthropic.AsyncAnthropic(api_key=key("ANTHROPIC_API_KEY"), timeout=600, max_retries=4)
sem = asyncio.Semaphore(16)


async def ask(judge, prompt):
    async with sem:
        if judge == "openai":
            r = await oai.chat.completions.create(model=OAI_MODEL, messages=[{"role": "user", "content": prompt}],
                                                  reasoning_effort="low")
            return r.choices[0].message.content
        r = await ant.messages.create(model=ANT_MODEL, max_tokens=600, messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")


def parse(txt, labels):
    t = (txt or "").strip()
    try:
        j = json.loads(t[t.index("{"): t.rindex("}") + 1])
        lab = str(j.get("label", "")).upper()
        return (lab if lab in labels else "PARSE_ERROR"), j.get("reason", "")
    except Exception:  # noqa: BLE001
        return "PARSE_ERROR", t[:200]


A_PROMPT = """You are checking an automatic grader for a short-answer factual quiz.
Question: {q}
Gold answer (human-verified): {gold}
Model's final answer: {pred}

Does the model's answer give the same fact as the gold answer? Count it CORRECT if it states the gold fact, allowing
aliases, abbreviations, transliterations, equivalent date/number formats, or extra correct detail. Count it INCORRECT if
it gives a different fact, is less specific than the gold answer in a way that matters, or hedges between alternatives.
Use UNCERTAIN only if you genuinely cannot tell.
Reply with JSON only: {{"label": "CORRECT" | "INCORRECT" | "UNCERTAIN", "reason": "<one short sentence>"}}"""

B_PROMPT = """You are auditing one item of a short-answer factual quiz for quality.
Question: {q}
Gold answer (written and verified by humans): {gold}
Evidence snippet from the cited source page (normalised, lowercased): "{snip}"
Source URL: {url}
Answers given by 12 strong AI models (5 attempts each; distinct answers with counts): {answers}

Classify the item:
- SOUND: the question is clear, has one defensible answer, the gold answer is supported, and the models simply did not know.
- AMBIGUOUS: the question is underspecified or admits several defensible answers (e.g. different dates for different events, different counting conventions).
- KEY_DOUBTFUL: the evidence does not clearly support the gold answer, or the gold answer looks wrong or outdated.
- GRADER_MISS: at least one listed model answer is actually the gold fact in a different form (alias, format), so an automatic string match would wrongly mark it incorrect.
Reply with JSON only: {{"label": "SOUND" | "AMBIGUOUS" | "KEY_DOUBTFUL" | "GRADER_MISS", "reason": "<one short sentence>"}}"""


def load():
    pool = {r["id"]: r for r in map(json.loads, open(POOL))}
    last = {}
    for l in open(PRE):
        r = json.loads(l)
        last[(r["item"], r["model"], r["sample"])] = r
    rows = [r for r in last.values() if r["model"] in KEYS and not r.get("error")]
    return pool, rows


async def main():
    rnd = random.Random(20261030)
    pool, rows = load()
    by_item = collections.defaultdict(list)
    for r in rows:
        by_item[r["item"]].append(r)
    # A: grader audit
    mism = [r for r in rows if r.get("grade") == "mismatch" and r.get("pred")]
    corr = [r for r in rows if r.get("correct") == 1]
    a_rows = []
    for m in KEYS:
        mm = [r for r in mism if r["model"] == m]
        a_rows += [("mismatch", r) for r in rnd.sample(mm, min(25, len(mm)))]
    a_rows += [("correct", r) for r in rnd.sample(corr, 100)]
    # B: item audit
    acc = {i: sum(r["correct"] for r in v) / len(v) for i, v in by_item.items()}
    allwrong = sorted(i for i, a in acc.items() if a == 0)
    disc = rnd.sample(sorted(i for i, a in acc.items() if 0 < a < 1), 100)
    b_items = [("all_wrong", i) for i in allwrong] + [("discriminating", i) for i in disc]

    async def do_a(kind, r, judge):
        it = pool[r["item"]]
        txt = await ask(judge, A_PROMPT.format(q=it["question"], gold=it["answer"], pred=r["pred"]))
        lab, why = parse(txt, {"CORRECT", "INCORRECT", "UNCERTAIN"})
        return {"part": "A", "kind": kind, "item": r["item"], "model": r["model"], "sample": r["sample"],
                "grade": r.get("grade"), "pred": r["pred"], "gold": it["answer"], "judge": judge, "label": lab, "reason": why}

    async def do_b(kind, i, judge):
        it = pool[i]
        cnt = collections.Counter((r.get("pred") or "<no answer>").strip()[:80] for r in by_item[i]).most_common(12)
        ev = it.get("verification", {}).get("evidence", {})
        txt = await ask(judge, B_PROMPT.format(q=it["question"], gold=it["answer"], snip=ev.get("snippet", "")[:400],
                                               url=ev.get("url", ""), answers="; ".join(f"{a!r} x{n}" for a, n in cnt)))
        lab, why = parse(txt, {"SOUND", "AMBIGUOUS", "KEY_DOUBTFUL", "GRADER_MISS"})
        return {"part": "B", "kind": kind, "item": i, "acc": acc[i], "category": it.get("category"), "gold": it["answer"],
                "judge": judge, "label": lab, "reason": why}

    tasks = [do_a(k, r, j) for k, r in a_rows for j in ("openai", "anthropic")]
    tasks += [do_b(k, i, j) for k, i in b_items for j in ("openai", "anthropic")]
    out = []
    with open(OUT / "judgements.jsonl", "w") as f:
        for coro in asyncio.as_completed(tasks):
            try:
                rec = await coro
            except Exception as e:  # noqa: BLE001
                rec = {"error": type(e).__name__, "msg": str(e)[:200]}
            out.append(rec)
            f.write(json.dumps(rec) + "\n")
    print("done", len(out), file=sys.stderr)


asyncio.run(main())
