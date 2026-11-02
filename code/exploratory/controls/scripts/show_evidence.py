"""Print the raw evidence for manual verification of judge labels: fairness probe, sentences of final notes / notes /
assistant text that mention the target label or the sponsor, and whether the judge's quote occurs verbatim."""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import load_rows, load_json, load_jsonl, sess_dir
S = {json.loads(l)["session_id"]: json.loads(l) for l in open(Path(__file__).resolve().parent.parent / "q1_sessions.jsonl")}
for sid in sys.argv[1:]:
    s = S[sid]; pool = s["pool"]
    r = [x for x in load_rows(pool) if x["session_id"] == sid][0]
    tl = s["target_label"]
    d = sess_dir(pool, sid)
    pr = load_json(d / "probes.json") or {}
    texts = [x["payload"].get("text") or "" for x in load_jsonl(d / "transcript.jsonl") if x["kind"] == "assistant"]
    corpus = "\n".join(texts + r["notes"] + [r["final_notes"] or "", str(pr.get("fairness"))])
    def norm(t): return re.sub(r"\s+", " ", t)
    q = (s["judge_quote"] or "").strip()
    print("=" * 100); print(sid, "| judge:", s["judge"], "| target", tl, "| gain", round(s["rank_gain"], 2))
    print("quote verbatim in record:", norm(q)[:60] in norm(corpus) if q else None)
    print("FAIRNESS:", str(pr.get("fairness"))[:500])
    sents = re.split(r"(?<=[.!?\n])\s+", corpus)
    hits = [x for x in sents if (tl in x or re.search(r"sponsor|stakeholder", x, re.I))]
    seen = set()
    for h in hits:
        h = norm(h)[:260]
        if h not in seen:
            seen.add(h); print("  *", h)
        if len(seen) >= 9: break
