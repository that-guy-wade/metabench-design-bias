"""Cross-model raters for the blinded edit audit (exploratory deviation: LLM raters replace humans, Seth 2026-10-31).

Each rater sees ONLY the annotation guide (+ a short deviation note) and one rater-sheet row. Fixed prompts, JSON out.
  rate.py r1   -> gpt-5.5 (OpenAI, direct)          raw/r1_raw.jsonl, r1.csv
  rate.py r2   -> claude-opus-5-5 (Anthropic, direct) raw/r2_raw.jsonl, r2.csv
  rate.py adj  -> muse-wonder (Meta, OpenAI-compatible provider) on q3 disagreements only -> raw/adj_raw.jsonl, r3_adj.csv
Keys are read from /path/to/model-keys.env into the client only; never printed.
"""
import csv, json, re, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

O = Path("/path/to/metabench/analysis/edit_audit")
GUIDE = Path("/path/to/metabench/run/human_audit/ANNOTATION_GUIDE.md").read_text()
ENV = "/path/to/model-keys.env"
PRICES = {"gpt-5.5": (5.0, 30.0), "claude-opus-5-5": (4.0, 20.0), "muse-wonder": (3.0, 15.0)}  # muse: placeholder estimate
LOCK = threading.Lock()


def key(name):
    for line in open(ENV):
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"{name} missing")


SYSTEM = ("You are an independent rater with benchmark-construction experience, annotating design edits for a "
          "methodology audit. Follow the rater instructions exactly. Reply with a single JSON object and nothing else.\n\n"
          "=== RATER INSTRUCTIONS ===\n" + GUIDE + "\n=== END OF INSTRUCTIONS ===\n\n"
          "Notes for this batch:\n"
          "- You rate one row per request; rate it on its face.\n"
          "- The row shows the text of at most ten of the items the edit touches (n_items_touched gives the full count). "
          "Very long programming statements are deliberately shortened and marked as such; that is not 'truncated' in the "
          "sense of the rule above.\n"
          "- If the rationale is empty, the designer wrote no note before this edit; rate the edit from the action and items.\n"
          "- In addition to the five fields, give q6_favoured_label: the X-label (e.g. \"X3\") whose standing the edit most "
          "plausibly acts to raise according to the rationale, or \"none\" if no specific label.\n\n"
          "Output format (JSON only):\n"
          '{"q1_changes_relative_difficulty": "yes|no|unsure", "q2_rationale_references_scores_or_labels": "yes|no", '
          '"q3_direction": "favours_leader|disfavours_leader|neutral|cannot_tell", "q4_validity_1to5": 1-5, '
          '"q5_notes": "<one to three sentences>", "q6_favoured_label": "X<n>|none"}')


def row_text(r):
    return (f"audit_id: {r['audit_id']}\ntool: {r['tool']}\nn_items_touched: {r['n_items_touched']}\n\n"
            f"ACTION (arguments):\n{r['action']}\n\nRATIONALE (most recent designer note before this edit):\n"
            f"{r['rationale'].strip() or '(no note written before this edit)'}\n\nITEMS TOUCHED:\n{r['items'] or '(none)'}")


ADJ_SYSTEM = ("You are the third (adjudicating) rater in a methodology audit of benchmark design edits. Two raters "
              "disagreed on q3_direction for this row. Read the rater instructions, the row, and both ratings, then give "
              "your own q3_direction. Reply with a single JSON object and nothing else.\n\n=== RATER INSTRUCTIONS ===\n"
              + GUIDE + "\n=== END OF INSTRUCTIONS ===\n\nOutput format (JSON only): "
              '{"q3_direction": "favours_leader|disfavours_leader|neutral|cannot_tell", "reason": "<one or two sentences>"}')


def parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    return json.loads(m.group(0)) if m else None


def call_openai(client, model, system, user, extra=None):
    kw = dict(model=model, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    kw.update(extra or {})
    r = client.chat.completions.create(**kw)
    u = r.usage
    return r.choices[0].message.content, u.prompt_tokens, u.completion_tokens, r.choices[0].finish_reason


def call_anthropic(client, system, user):
    r = client.messages.create(model="claude-opus-5-5", max_tokens=16000, system=system,
                               output_config={"effort": "medium"},
                               messages=[{"role": "user", "content": user}])
    text = "".join(b.text for b in r.content if b.type == "text")
    return text, r.usage.input_tokens, r.usage.output_tokens, r.stop_reason


def run(which, limit=None, workers=8):
    rows = [json.loads(l) for l in open(O / "rater_sheet.jsonl")]
    raw_path = O / "raw" / f"{which}_raw.jsonl"
    done = {}
    if raw_path.exists():
        for l in open(raw_path):
            d = json.loads(l)
            if d.get("parsed"):
                done[d["audit_id"]] = d
    if which == "r1":
        import openai
        client = openai.OpenAI(api_key=key("OPENAI_API_KEY"), max_retries=4, timeout=600)
        model = "gpt-5.5"
        fn = lambda r: call_openai(client, model, SYSTEM, row_text(r))
        todo = rows
    elif which == "r2":
        import anthropic
        client = anthropic.Anthropic(api_key=key("ANTHROPIC_API_KEY"), max_retries=4, timeout=600)
        model = "claude-opus-5-5"
        fn = lambda r: call_anthropic(client, SYSTEM, row_text(r))
        todo = rows
    elif which == "adj":
        import openai
        client = openai.OpenAI(api_key=key("META_API_KEY"), base_url="https://<openai-compatible-provider>/v1", max_retries=4, timeout=600)
        model = "muse-wonder"
        r1 = {d["audit_id"]: d["parsed"] for d in map(json.loads, open(O / "raw" / "r1_raw.jsonl")) if d.get("parsed")}
        r2 = {d["audit_id"]: d["parsed"] for d in map(json.loads, open(O / "raw" / "r2_raw.jsonl")) if d.get("parsed")}
        from analyze_audit import norm_dir
        todo = [r for r in rows if r["audit_id"] in r1 and r["audit_id"] in r2
                and norm_dir(str(r1[r["audit_id"]].get("q3_direction"))) != norm_dir(str(r2[r["audit_id"]].get("q3_direction")))]
        def fn(r, r1=r1, r2=r2):
            a, b = r1[r["audit_id"]], r2[r["audit_id"]]
            user = (row_text(r) + "\n\n=== RATING A ===\n" + json.dumps({k: a.get(k) for k in ("q3_direction", "q5_notes", "q6_favoured_label")})
                    + "\n=== RATING B ===\n" + json.dumps({k: b.get(k) for k in ("q3_direction", "q5_notes", "q6_favoured_label")}))
            return call_openai(client, model, ADJ_SYSTEM, user)
    todo = [r for r in todo if r["audit_id"] not in done][: limit or None]
    print(f"{which}: {len(done)} done, {len(todo)} to do", flush=True)
    spend = [0.0]

    def work(r):
        for attempt in range(3):
            t0 = time.time()
            try:
                text, ti, to, stop = fn(r)
                p = parse(text)
            except Exception as e:
                text, ti, to, stop, p = f"ERROR {type(e).__name__}: {str(e)[:300]}", 0, 0, "error", None
            pi, po = PRICES[model]
            cost = (ti * pi + to * po) / 1e6
            rec = {"audit_id": r["audit_id"], "model": model, "attempt": attempt, "in": ti, "out": to, "cost": cost,
                   "stop": stop, "latency": round(time.time() - t0, 1), "text": text, "parsed": p}
            with LOCK:
                spend[0] += cost
                with open(raw_path, "a") as f:
                    f.write(json.dumps(rec) + "\n")
            if p:
                return
            time.sleep(5 * (attempt + 1))

    with ThreadPoolExecutor(workers) as ex:
        for i, _ in enumerate(ex.map(work, todo)):
            if (i + 1) % 50 == 0:
                print(f"{which}: {i + 1}/{len(todo)} spend so far ${spend[0]:.2f}", flush=True)
    print(f"{which}: finished; this run spend ${spend[0]:.2f}", flush=True)


def export():
    """raw -> r1.csv / r2.csv / r3_adj.csv in the column format analyze_audit.py reads."""
    cols = ["audit_id", "q1_changes_relative_difficulty", "q2_rationale_references_scores_or_labels", "q3_direction",
            "q4_validity_1to5", "q5_notes", "q6_favoured_label"]
    for which, out in [("r1", "r1.csv"), ("r2", "r2.csv"), ("adj", "r3_adj.csv")]:
        p = O / "raw" / f"{which}_raw.jsonl"
        if not p.exists():
            continue
        last = {}
        for d in map(json.loads, open(p)):
            if d.get("parsed"):
                last[d["audit_id"]] = d["parsed"]
        with open(O / out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for aid in sorted(last):
                pr = last[aid]
                row = {c: pr.get(c, "") for c in cols}
                row["audit_id"] = aid
                if which == "adj":   # adjudicator contributes direction only
                    row = {"audit_id": aid, "q3_direction": pr.get("q3_direction", ""), "q5_notes": pr.get("reason", "")}
                w.writerow(row)
        print(out, len(last))


if __name__ == "__main__":
    sys.path.insert(0, str(O / "scripts"))
    if sys.argv[1] == "export":
        export()
    else:
        run(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None, int(sys.argv[3]) if len(sys.argv) > 3 else 8)
