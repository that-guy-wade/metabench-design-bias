"""Hendrycks MATH test split, Level 5 only: verified universe + seeded stratified sample for the math pool.

Copies (both read as JSON only, never executed):
  original: qwedsacf/competition_math (the copy the authors' GitHub README now links to; the HF repo
            hendrycks/competition_math is `disabled` after the 2024 AoPS DMCA claim and the Berkeley tarball is down).
            12,500 rows = train+test without a split column, so test membership comes from the mirror.
  mirror:   EleutherAI/hendrycks_math, per-subject `test` splits (5,000 rows).
Verification = two-mirror transcription check of the human-written \\boxed{} answer (NOT two independent keyings).
"""
from __future__ import annotations
import hashlib, json, random, re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RAW = ROOT / "pools/_work/math/raw"
SUBJECTS = ["algebra", "counting_and_probability", "geometry", "intermediate_algebra", "number_theory",
            "prealgebra", "precalculus"]
ORIGINAL = "qwedsacf/competition_math"
MIRROR = "EleutherAI/hendrycks_math"
SOURCE_DATE = "2021-03-05"
FIG_RE = re.compile(r"\[asy\]|\\begin\{asy\}|\bfigures?\b|\bdiagrams?\b|\bshown\b|\\includegraphics|\bpictures?\b"
                    r"|\bdrawing\b|!\[|\.(png|jpg|jpeg|gif)\b", re.I)
INT_RE = re.compile(r"-?\d+")


def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def norm_text(s: str) -> str:
    return norm_ws(s).lower()


def extract_boxed(solution: str) -> list[str] | None:
    """All \\boxed{...} contents, brace-balanced. None if a \\boxed is not followed by a balanced group."""
    out, i = [], 0
    while True:
        i = solution.find("\\boxed", i)
        if i < 0:
            return out
        j = i + len("\\boxed")
        while j < len(solution) and solution[j] == " ":
            j += 1
        if j >= len(solution) or solution[j] != "{":
            return None
        depth, k = 0, j
        while k < len(solution):
            c = solution[k]
            if c == "\\" and k + 1 < len(solution):
                k += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        if depth != 0:
            return None
        out.append(solution[j + 1:k])
        i = k + 1


def verify_pair(sol_original: str, sol_mirror: str) -> tuple[bool, str, dict]:
    """(verified, failure_rule, evidence). Fails on: boxed count != 1 in either copy, answer mismatch, solution mismatch."""
    bo, bm = extract_boxed(sol_original), extract_boxed(sol_mirror)
    ev = {"boxed_answer_original": bo[0] if bo and len(bo) == 1 else None,
          "boxed_answer_mirror": bm[0] if bm and len(bm) == 1 else None,
          "solution_sha256": hashlib.sha256(norm_ws(sol_original).encode()).hexdigest()}
    if bo is None or bm is None or len(bo) != 1 or len(bm) != 1:
        return False, "boxed_count_not_one", ev
    if norm_ws(bo[0]) != norm_ws(bm[0]):
        return False, "boxed_answer_mismatch", ev
    if norm_ws(sol_original) != norm_ws(sol_mirror):
        return False, "solution_text_mismatch", ev
    return True, "", ev


def load(name: str) -> list[dict]:
    return [json.loads(l) for l in open(RAW / name) if l.strip()]


def build(existing_questions: set[str], n_needed: int, seed: int) -> tuple[list[dict], dict]:
    excl, excl_detail = Counter(), defaultdict(list)
    orig_by_text = defaultdict(list)
    for i, r in enumerate(load(f"{ORIGINAL.replace('/', '__')}__default__train.jsonl")):
        orig_by_text[norm_text(r["problem"])].append((i, r))
    verified, universe, seen_math = [], 0, set()
    for subj in SUBJECTS:
        for idx, r in enumerate(load(f"{MIRROR.replace('/', '__')}__{subj}__test.jsonl")):
            if r["level"] != "Level 5":
                continue
            universe += 1
            q = r["problem"]
            key = norm_text(q)
            sid = f"{subj}/{idx}"
            if FIG_RE.search(q):
                excl["figure_reference"] += 1; continue
            if key in existing_questions:
                excl["duplicate_of_existing_pool"] += 1; excl_detail["duplicate_of_existing_pool"].append(sid); continue
            if key in seen_math:
                excl["duplicate_within_math"] += 1; excl_detail["duplicate_within_math"].append(sid); continue
            seen_math.add(key)
            hits = orig_by_text.get(key, [])
            sols = {norm_ws(h[1]["solution"]) for h in hits}
            if not hits:
                excl["no_match_in_original"] += 1; excl_detail["no_match_in_original"].append(sid); continue
            if len(sols) > 1:
                excl["ambiguous_match_in_original"] += 1; excl_detail["ambiguous_match_in_original"].append(sid); continue
            oi, orow = hits[0]
            ok, rule, ev = verify_pair(orow["solution"], r["solution"])
            if not ok:
                excl[rule] += 1; excl_detail[rule].append(sid); continue
            ans = norm_ws(ev["boxed_answer_original"])
            if not ans:
                excl["empty_boxed"] += 1; continue
            ev.update({"subject": subj, "level": 5, "original_row": oi, "mirror_row": idx,
                       "original_type_field": orow["type"], "mirror_level_field": r["level"]})
            verified.append({"source": f"{ORIGINAL}:test", "source_id": sid, "source_url": "https://huggingface.co/datasets/" + ORIGINAL,
                             "licence": "MIT (github.com/hendrycks/math LICENSE)", "source_date": SOURCE_DATE,
                             "question": q, "options": [], "answer": ans,
                             "key_type": "integer" if INT_RE.fullmatch(ans) else "expression", "category": "MATH",
                             "strata": {"contest": "MATH", "year": None, "subject": subj, "level": 5, "difficulty_proxy": 5},
                             "verification": {"method": "two-mirror transcription check of a human-written boxed answer "
                                                        "(qwedsacf/competition_math vs EleutherAI/hendrycks_math; not two independent keyings)",
                                              "verified": True, "evidence": ev}})
    # proportional allocation by subject, largest remainders, seeded sample within subject
    by_subj = defaultdict(list)
    for v in verified:
        by_subj[v["strata"]["subject"]].append(v)
    n_total = len(verified)
    quota = {s: n_needed * len(by_subj[s]) / n_total for s in SUBJECTS}
    alloc = {s: int(quota[s]) for s in SUBJECTS}
    for s in sorted(SUBJECTS, key=lambda s: -(quota[s] - alloc[s]))[: n_needed - sum(alloc.values())]:
        alloc[s] += 1
    rng = random.Random(seed)
    sampled = []
    for s in SUBJECTS:
        grp = sorted(by_subj[s], key=lambda v: v["source_id"])
        sampled += rng.sample(grp, min(alloc[s], len(grp)))
    report = {"original": ORIGINAL, "mirror": MIRROR, "universe_level5_test": universe, "verified": n_total,
              "verified_per_subject": {s: len(by_subj[s]) for s in SUBJECTS}, "allocation": alloc,
              "sampled": len(sampled), "sampled_per_subject": dict(Counter(v["strata"]["subject"] for v in sampled)),
              "exclusions": dict(excl), "exclusion_detail": {k: v[:50] for k, v in excl_detail.items()},
              "key_types": dict(Counter(v["key_type"] for v in sampled))}
    return sampled, report
