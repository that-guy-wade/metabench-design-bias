"""Cross-model outside checks for the MetaBench launch package (§6.3 cold readers, §6.4 hostile readers).

Readers are models from developers other than the drafting model's (Anthropic): OpenAI, Google, xAI, Meta.
Keys are loaded from the managed env file into this process only and never printed.
Usage: python -I readers.py {cold|hostile|answered} OUT_DIR
"""
import asyncio
import base64
import json
import os
import re
import sys
from pathlib import Path

import httpx
import openai

ENV = "/path/to/model-keys.env"
for line in open(ENV):
    m = re.match(r"^(OPENAI_API_KEY|GEMINI_API_KEY|XAI_API_KEY|META_API_KEY)=(.*)$", line.strip())
    if m:
        os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")

HERE = Path(__file__).resolve().parent.parent
CHARTS = HERE / "charts"
READERS = {  # name -> (provider, model id)
    "gpt61sol": ("openai", "gpt-6.1-sol"),
    "gpt55": ("openai", "gpt-5.5"),
    "gemini4argon": ("google", "gemini-4-argon"),
    "grok47": ("xai", "grok-4.7"),
    "muse_wonder": ("meta", "muse-wonder"),
}
GRADERS = ["gpt61sol", "gemini4argon"]  # two graders from different developers; a reader is never graded by itself
CLIENTS = {
    "openai": lambda: openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=600, max_retries=3),
    "xai": lambda: openai.AsyncOpenAI(api_key=os.environ["XAI_API_KEY"], base_url="https://api.x.ai/v1", timeout=600, max_retries=3),
    "meta": lambda: openai.AsyncOpenAI(api_key=os.environ["META_API_KEY"], base_url="https://<openai-compatible-provider>/v1", timeout=600, max_retries=3),
}
SEM = asyncio.Semaphore(12)


def img_b64(name):
    return base64.b64encode((CHARTS / name).read_bytes()).decode()


async def ask(reader, prompt, image=None, max_tokens=1500):
    prov, model = READERS[reader]
    async with SEM:
        if prov == "google":
            parts = [{"text": prompt}]
            if image:
                parts.insert(0, {"inline_data": {"mime_type": "image/png", "data": img_b64(image)}})
            body = {"contents": [{"role": "user", "parts": parts}],
                    "generationConfig": {"maxOutputTokens": max_tokens + 4000, "thinkingConfig": {"thinkingLevel": "low"}}}
            async with httpx.AsyncClient(timeout=600) as c:
                for attempt in range(4):
                    r = await c.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", json=body,
                                     headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
                    if r.status_code == 200:
                        break
                    await asyncio.sleep(5 * (attempt + 1))
                if r.status_code != 200:
                    return f"ERROR google {r.status_code}"
                cand = r.json().get("candidates", [{}])[0]
                return "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []) if not p.get("thought"))
        content = [{"type": "text", "text": prompt}]
        if image:
            content.insert(0, {"type": "image_url", "image_url": {"url": "data:image/png;base64," + img_b64(image)}})
        kw = {"max_completion_tokens": max_tokens + 4000} if prov == "openai" else {"max_tokens": max_tokens + 4000}
        try:
            r = await CLIENTS[prov]().chat.completions.create(model=model, messages=[{"role": "user", "content": content}], **kw)
            return r.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001
            return f"ERROR {type(e).__name__}: {str(e)[:200]}"


GLANCE = ("You are scrolling X on your phone and this image appears in your feed. You look at it for about five seconds, "
          "the way people actually do; do not study the fine print. ")
CHART_TESTS = {
    "1_null_result.png": {
        "intended": "On average the designer models did NOT follow / were not steered by the shuffled scoreboard (match near zero; "
                    "an average of 0.10 or more ruled out). It does not need to mention every detail.",
        "probe": "Does this image show the study PROVED there is no effect at all? Answer yes or no, then one short reason.",
        "probe_pass": "Answers NO (or equivalent: it bounds/rules out larger effects, an average, cannot prove zero). FAIL if it says the study proved no effect / zero effect.",
    },
    "2_told_to_rig.png": {
        "intended": "Models split sharply on a request to rig a benchmark: some complied, others refused. Only this split is "
                    "required; the answer need not repeat that the target was a named model, and naming which models is fine.",
        "probe": "According to this image, which AI lab is the safest?",
        "probe_pass": "Declines to name a safest lab, OR names one but explicitly cites the image's caveat that it is not a safety ranking / "
                      "one brief, one task, small samples. FAIL if it confidently names a safest lab without that caveat.",
    },
    "3_monitors.png": {
        "intended": "Monitors caught announced/open rigging (nearly all) but missed much of it when the rigging was hidden "
                    "(about a quarter to a half caught).",
        "probe": "Roughly what share of hidden rigging did the monitors catch?",
        "probe_pass": "Gives roughly 26% and/or 55% (a quarter to a half; 'about 1 in 4' / 'about 1 in 2'). FAIL if far off.",
    },
    "4_design.png": {
        "intended": "Identifies the image as explaining an experiment in which AI models build benchmarks, and mentions the "
                    "scoreboard/ranking condition AND at least one rigging condition. Listing every check is NOT required.",
        "probe": "In the main test, what were the models shown, and why?",
        "probe_pass": "Says they were shown a scoreboard in a random/shuffled order (to see whether the display steers the benchmark). "
                      "FAIL if it says they were shown the true scores.",
    },
}


def root_post():
    t = (HERE / "thread.md").read_text()
    block = t.split("### 1/")[1].split("###")[0]
    return "\n".join(l[2:] for l in block.splitlines() if l.startswith("> ")).strip()


GRADE = """You are grading a reader's answer against a rubric. Be strict and literal.
Rubric for PART A (main message): the answer must convey: {intended}
Rubric for PART B: {probe_pass}
Reader's answer:
<<<
{answer}
>>>
Reply with JSON only: {{"A": "PASS" or "FAIL", "B": "PASS" or "FAIL", "why": "<=25 words"}}"""


def parse_json(s):
    m = re.search(r"\{.*\}", s or "", re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except Exception:  # noqa: BLE001
        return {}


async def grade(reader, rubric, answer):
    gs = [g for g in GRADERS if g != reader] or GRADERS
    if len(gs) < 2:
        gs = gs + ["grok47"]
    outs = await asyncio.gather(*(ask(g, GRADE.format(answer=answer, **rubric), max_tokens=300) for g in gs[:2]))
    js = [parse_json(o) for o in outs]
    return {"graders": gs[:2], "grades": js,
            "A": "PASS" if all(j.get("A") == "PASS" for j in js) else "FAIL",
            "B": "PASS" if all(j.get("B") == "PASS" for j in js) else "FAIL"}


async def cold(out):
    tasks = []
    only = sys.argv[3].split(",") if len(sys.argv) > 3 else None
    for chart, t in CHART_TESTS.items():
        if only and chart not in only:
            continue
        prompt = GLANCE + "In one sentence, what is the main message of this image?\nThen, on a new line starting 'B:', answer: " + t["probe"]
        for r in READERS:
            tasks.append(("chart", chart, r, prompt, chart, {"intended": t["intended"], "probe_pass": t["probe_pass"]}))
    rp = root_post()
    eb = ("This post appeared in your X feed, with the attached chart. Read it once, as you normally would.\n\nPOST:\n" + rp +
          "\n\nIn two or three sentences, restate in your own words what the post claims, including any limits it states.\n"
          "Then, on a new line starting 'B:', answer: Did this study prove that AI models never bias the benchmarks they build?")
    for r in ([] if only else READERS):
        tasks.append(("explain_back", "root", r, eb, "1_null_result.png",
                      {"intended": "(1) on average the models did not follow the shown/shuffled scoreboard (larger average effects ruled out); AND "
                                   "(2) the limit that a single model doing it could slip through / this bounds only the average.",
                       "probe_pass": "Answers NO (it bounded an average; did not prove never). FAIL if yes."}))

    async def run(kind, item, r, prompt, image, rubric):
        ans = await ask(r, prompt, image)
        g = await grade(r, rubric, ans) if not ans.startswith("ERROR") else {"A": "ERROR", "B": "ERROR"}
        return {"kind": kind, "item": item, "reader": r, "answer": ans, **g}

    if only:
        tasks = tasks * 2  # two samples per reader when re-testing selected charts
    res = await asyncio.gather(*(run(*t) for t in tasks))
    (out / ("cold_readers_retest.json" if only else "cold_readers.json")).write_text(json.dumps(res, indent=1))
    for x in res:
        print(x["kind"], x["item"], x["reader"], x["A"], x["B"], "|", (x["answer"] or "").replace("\n", " ")[:160])


PERSONAS = {
    "lab_comms": ("gemini4argon", "the communications lead at one of the AI labs whose models appear in this study's per-model table"),
    "safety_sceptic": ("grok47", "an AI-safety researcher who thinks studies like this are reassuring theatre that understates risk"),
    "statistician": ("gpt61sol", "an applied statistician who specialises in equivalence testing, pre-registration and multiple comparisons"),
    "competitor": ("muse_wonder", "the founder of a competing benchmark/evaluation company who doubts a conflicted party's study"),
    "han_fang": ("gpt55", "Han Fang, a Meta Superintelligence Labs researcher whose public X post this study replies to; you said you had "
                          "'yet come across solid evidence on models' self preferences' and asked to be shown some"),
}


async def hostile(out):
    blog = (HERE / "blog_v4.md").read_text()
    thread = (HERE / "thread.md").read_text()
    prompt = ("You are {who}. Below are an X thread and the blog post it links to.\n\n===THREAD===\n{thread}\n\n===BLOG===\n{blog}\n\n"
              "Write the most damaging criticism you could post that is still FAIR (true, and something a reasonable expert in your "
              "position would actually say). Give: (1) the post, max 280 characters; (2) the specific claim or design choice it "
              "targets; (3) what evidence or change would answer it. Be concrete.")

    async def one(key):
        r, who = PERSONAS[key]
        ans = await ask(r, prompt.format(who=who, thread=thread, blog=blog), max_tokens=1200)
        return {"persona": key, "reader": r, "answer": ans}

    res = await asyncio.gather(*(one(k) for k in PERSONAS))
    (out / "hostile_readers.json").write_text(json.dumps(res, indent=1))
    for x in res:
        print("=====", x["persona"], x["reader"]); print(x["answer"])


async def answered(out):
    """For each hostile criticism, a model from a different developer than its author judges whether the package answers it."""
    crit = json.loads((out / "hostile_readers.json").read_text())
    pkg = "===THREAD===\n" + (HERE / "thread.md").read_text() + "\n===BLOG===\n" + (HERE / "blog_v4.md").read_text()
    q = ("Here is a criticism of a study announcement, then the announcement (thread + blog).\n\nCRITICISM:\n{c}\n\n{pkg}\n\n"
         "Is the criticism (a) FALSE given the materials, (b) ALREADY ANSWERED in the thread or blog (quote the answering text), "
         "or (c) NOT ANSWERED? Reply JSON only: {{\"verdict\": \"FALSE|ANSWERED|NOT_ANSWERED\", \"quote\": \"...\", \"why\": \"<=30 words\"}}")
    judge_for = {"gemini4argon": "gpt61sol", "grok47": "gemini4argon", "gpt61sol": "grok47", "muse_wonder": "gpt61sol", "gpt55": "gemini4argon"}

    async def one(x):
        j = judge_for[x["reader"]]
        return {**x, "judge": j, "verdict": parse_json(await ask(j, q.format(c=x["answer"], pkg=pkg), max_tokens=600))}

    res = await asyncio.gather(*(one(x) for x in crit))
    (out / "hostile_answered.json").write_text(json.dumps(res, indent=1))
    for x in res:
        print(x["persona"], "→", x["verdict"].get("verdict"), "|", x["verdict"].get("why"), "|", (x["verdict"].get("quote") or "")[:160])


if __name__ == "__main__":
    mode, out = sys.argv[1], Path(sys.argv[2] if len(sys.argv) > 2 else HERE / "checks")
    out.mkdir(parents=True, exist_ok=True)
    asyncio.run({"cold": cold, "hostile": hostile, "answered": answered}[mode](out))
