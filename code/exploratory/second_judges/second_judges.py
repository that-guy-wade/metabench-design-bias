"""Exploratory robustness check for the instructed-arm labels (answers the single-judge criticism).

Re-labels the 102 main-experiment instructed sessions with two more judges from other developers (Gemini 4 Argon,
Grok 4.7), using the released judge rubric and the exact inputs GPT-5.5 judged (data/exploratory/controls/judge.tar.gz).
Usage: python -I second_judges.py JUDGE_DIR OUT_DIR   (JUDGE_DIR = extracted judge.tar.gz/judge)
"""
import asyncio
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("readers", Path(__file__).resolve().parent / "readers.py")
R = importlib.util.module_from_spec(_spec)  # loads keys into this process; never printed
_spec.loader.exec_module(R)

REL = Path("/path/to/metabench/release/metabench-release")
JD, OUT = Path(sys.argv[1]), Path(sys.argv[2])
src = (REL / "code/exploratory/controls/scripts/judge_c1.py").read_text()
RUBRIC = re.search(r'RUBRIC = """(.*?)"""', src, re.S).group(1)
inputs = [json.loads(line) for line in open(JD / "c1_inputs.jsonl")]
gpt = {}
for line in open(JD / "c1_judge_raw.jsonl"):
    o = json.loads(line)
    gpt[o["session_id"]] = R.parse_json(o.get("raw")).get("label")
JUDGES = ["gemini4argon", "grok47"]


async def main():
    async def one(j, x):
        txt = await R.ask(j, RUBRIC + "\n\n" + x["input"] + "\n\nReply with the JSON object only.", max_tokens=800)
        return j, x["session_id"], R.parse_json(txt).get("label"), txt[:2000]

    res = await asyncio.gather(*(one(j, x) for j in JUDGES for x in inputs))
    lab = defaultdict(dict)
    for j, sid, label, raw in res:
        lab[sid][j] = label
    for sid in lab:
        lab[sid]["gpt55"] = gpt.get(sid)
    des = {x["session_id"]: re.match(r"T1_\w+?_(\w+?)_instructed", x["session_id"]).group(1) for x in inputs}
    judges = ["gpt55"] + JUDGES

    def agree(a, b):
        pairs = [(lab[s][a], lab[s][b]) for s in lab if lab[s].get(a) and lab[s].get(b)]
        return sum(p == q for p, q in pairs), len(pairs)

    majority, per_model = {}, defaultdict(Counter)
    for s, d in lab.items():
        c = Counter(d[j] for j in judges if d.get(j))
        top, n = c.most_common(1)[0]
        majority[s] = top if n >= 2 else "NO_MAJORITY"
        per_model[des[s]][majority[s]] += 1
    out = {"n_sessions": len(lab), "labels": lab, "majority": majority,
           "pairwise_agreement": {f"{a}~{b}": agree(a, b) for i, a in enumerate(judges) for b in judges[i + 1:]},
           "all_three_agree": sum(len({lab[s].get(j) for j in judges}) == 1 for s in lab),
           "per_model_majority": {k: dict(v) for k, v in per_model.items()},
           "per_model_gpt55": {k: dict(Counter(lab[s]["gpt55"] for s in lab if des[s] == k)) for k in per_model},
           "raw": [dict(judge=j, session_id=s, raw=r) for j, s, _, r in res]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "second_judges.json").write_text(json.dumps(out, indent=1))
    print("pairwise", out["pairwise_agreement"], "all three agree", out["all_three_agree"], "/", len(lab))
    for k in sorted(per_model):
        print(k, "gpt55", out["per_model_gpt55"][k], "| majority", out["per_model_majority"][k])


asyncio.run(main())
