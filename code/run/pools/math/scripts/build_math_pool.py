"""Deterministic builder for the MetaBench math pool (pools/math/pool.jsonl).

Inputs: pools/_work/math/raw/*.jsonl written by download_sources.py (untrusted data, read as JSON only).
No model is run; no model output is read. Selection within sources is seeded random (SEED).
Every verification is code that can fail; its evidence is stored per item.

Usage: python -I build_math_pool.py   (writes pool.jsonl and build_report.json next to pools/math/)
"""
from __future__ import annotations
import difflib, json, random, re, sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
POOL_DIR = HERE.parent
ROOT = POOL_DIR.parents[1]
RAW = ROOT / "pools/_work/math/raw"
sys.path.append(str(ROOT / "pools"))  # append: pools/math must not shadow stdlib math
from schema_check import CUTOFF_REFERENCE, DEVELOPER_CUTOFFS, parse_date  # noqa: E402
sys.path.insert(0, str(HERE))
import add_math_level5  # noqa: E402

SEED = 20261025
TARGET = 2000
# The 2026-10-25 04:52 base pool (1,209 items, full-line sha256 52f3ece3...) is frozen in base_manifest.json:
# base items keep their ids and content (source, source_id, question, answer); verification metadata may be upgraded.
# A base item excluded by a later check (BRUMO/CMIMC official-PDF disagreement) leaves a gap in the id range.
FROZEN_BASE_N = 1209
MANIFEST = json.loads((POOL_DIR / "base_manifest.json").read_text())["items"]
HF = "https://huggingface.co/datasets/"
MA_LIC = "CC-BY-NC-SA-4.0 (MathArena dataset card)"

# Contest dates (provenance per contest in PROVENANCE.md). HMMT dates are overwritten at build time by the date
# printed in the organiser's solutions PDF. APEX 2025 and AIME 1983-2021 use first-of-month fallbacks.
DATES = {
    "AIME 2026 I": "2026-02-05", "AIME 2026 II": "2026-02-11",
    "AIME 2025 I": "2025-02-06", "AIME 2025 II": "2025-02-12",
    "AIME 2024 I": "2024-02-01", "AIME 2024 II": "2024-02-07",
    "AIME 2023 I": "2023-02-07", "AIME 2023 II": "2023-02-15",
    "AIME 2022 I": "2022-02-08", "AIME 2022 II": "2022-02-16",
    "HMMT Feb 2026": "2026-02-14", "HMMT Feb 2025": "2025-02-15", "HMMT Feb 2024": "2024-02-17",
    "HMMT Feb 2023": "2023-02-18", "HMMT Nov 2025": "2025-11-08",
    "BRUMO 2025": "2025-04-05", "CMIMC 2025": "2025-03-15", "SMT 2025": "2025-04-12",
    "APEX 2025": "2025-01-01",
}
# MathArena contest datasets: hf name -> (category, contest label(s), official url)
MATHARENA = {
    "MathArena/aime_2026": ("AIME", "AIME 2026", "https://maa.org/student-programs/amc/"),
    "MathArena/aime_2025": ("AIME", "AIME 2025", "https://maa.org/student-programs/amc/"),
    "MathArena/aime_2024_I": ("AIME", "AIME 2024 I", "https://maa.org/student-programs/amc/"),
    "MathArena/aime_2024_II": ("AIME", "AIME 2024 II", "https://maa.org/student-programs/amc/"),
    "MathArena/aime_2023_I": ("AIME", "AIME 2023 I", "https://maa.org/student-programs/amc/"),
    "MathArena/aime_2023_II": ("AIME", "AIME 2023 II", "https://maa.org/student-programs/amc/"),
    "MathArena/hmmt_feb_2026": ("HMMT", "HMMT Feb 2026", "https://www.hmmt.org/www/archive/292"),
    "MathArena/hmmt_feb_2025": ("HMMT", "HMMT Feb 2025", "https://www.hmmt.org/www/archive/282"),
    "MathArena/hmmt_feb_2024": ("HMMT", "HMMT Feb 2024", "https://www.hmmt.org/www/archive/272"),
    "MathArena/hmmt_feb_2023": ("HMMT", "HMMT Feb 2023", "https://www.hmmt.org/www/archive/262"),
    "MathArena/hmmt_nov_2025": ("HMMT", "HMMT Nov 2025", "https://www.hmmt.org/www/archive/291"),
    "MathArena/brumo_2025": ("BRUMO", "BRUMO 2025", "https://www.brumo.org/archive"),
    "MathArena/cmimc_2025": ("CMIMC", "CMIMC 2025", "https://cmimc.math.cmu.edu/archive"),
    "MathArena/smt_2025": ("SMT", "SMT 2025", "https://sumo.stanford.edu/smt"),
    "MathArena/apex_2025": ("APEX", "APEX 2025", "https://matharena.ai/"),
}

FIG_RE = re.compile(r"\[asy\]|\\begin\{asy\}|\bfigures?\b|\bdiagrams?\b|as shown|shown (below|above|here|in the)"
                    r"|\\includegraphics|\bpictures?\b|\bdrawing\b|!\[|\.(png|jpg|jpeg|gif)\b", re.I)
PROOF_RE = re.compile(r"\b(prove|show that|proof)\b", re.I)
INT_RE = re.compile(r"-?\d+")


def norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def alnum(s: str) -> str:
    """Letters and digits only: transcriptions of one problem differ in LaTeX spacing/punctuation."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def canon_pdf(s: str) -> str:
    """Canonical form for comparing a LaTeX key with a pypdf-extracted answer (documented in PROVENANCE)."""
    s = str(s).replace("√", "sqrt").replace("π", "pi").replace("−", "-")
    s = re.sub(r"\\(d|t)?frac", "", s).replace("\\sqrt", "sqrt").replace("\\pi", "pi")
    s = re.sub(r"\\[a-zA-Z]+", "", s)
    return alnum(s)


def pdf_agree(key: str, pdf_answer: str) -> bool:
    """The PDF often prints alternatives 'a = b'; agreement with any '='-separated form counts."""
    return any(canon_pdf(x) == canon_pdf(key) for x in pdf_answer.split("=") if x.strip())


def norm_answer(a) -> str:
    """Whitespace/notation-only normalisation for cross-source comparison; never rewrites a stored key."""
    s = str(a).strip().replace("$", "")
    s = re.sub(r"\^\{?\\circ\}?|\\circ|°", "", s)
    s = s.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac").replace("\\left", "").replace("\\right", "")
    s = re.sub(r"\\text\{(.*?)\}", r"\1", s)
    s = re.sub(r"\s+", "", s)
    if INT_RE.fullmatch(s):
        s = str(int(s))
    return s


def load(name: str) -> list[dict]:
    return [json.loads(l) for l in open(RAW / name) if l.strip()]


def date_flags(d: str) -> tuple[bool, dict]:
    dd = parse_date(d)
    return dd > CUTOFF_REFERENCE, {k: dd > v for k, v in DEVELOPER_CUTOFFS.items()}


def best_match(q: str, cands: list[tuple[str, str]]) -> tuple[float, str | None]:
    """Return (similarity, answer) of the candidate whose question text is closest to q."""
    nq = alnum(q)
    best, ans = 0.0, None
    for cq, ca in cands:
        r = difflib.SequenceMatcher(None, nq, alnum(cq)).ratio()
        if r > best:
            best, ans = r, ca
    return best, ans


def main() -> int:
    excl = Counter()
    excl_detail = defaultdict(list)
    disagreements = []
    candidates: list[dict] = []

    # ---- cross-source tables for AIME ----
    oc = {}
    for part in ("I", "II"):
        oc[part] = [(r["question"], r["answer"]) for r in load(f"opencompass__AIME2025__AIME2025-{part}__test.jsonl")]
    yl = {"I": [(r["problem"], r["answer"]) for r in load("yentinglin__aime_2025__part1__train.jsonl")],
          "II": [(r["problem"], r["answer"]) for r in load("yentinglin__aime_2025__part2__train.jsonl")]}
    aimo = defaultdict(list)  # (year, part) -> [(problem, answer)]
    for r in load("AI-MO__aimo-validation-aime__default__train.jsonl"):
        m = re.search(r"(\d{4})_AIME_(I{1,2})_Problems/Problem_(\d+)", r["url"])
        if m:
            aimo[(int(m.group(1)), m.group(2))].append((r["problem"], r["answer"]))

    def cross_check(q: str, ans: str, tables: dict[str, list]) -> dict | None:
        """Compare `ans` with the text-matched answer in each independent table. None = no table matched."""
        ev = {}
        for src, cands in tables.items():
            sim, a2 = best_match(q, cands)
            if sim >= 0.6:
                ev[src] = {"text_similarity": round(sim, 3), "answer": str(a2), "agree": norm_answer(a2) == norm_answer(ans)}
        return ev or None

    # ---- HMMT official solutions PDFs (hmmt_pdf_answers.py) ----
    hmmt_pdf = json.loads((POOL_DIR / "hmmt_pdf_answers.json").read_text())
    hmmt_pdf.update(json.loads((POOL_DIR / "other_pdf_answers.json").read_text()))  # BRUMO 2025, CMIMC 2025
    for contest, rec in hmmt_pdf.items():
        if rec.get("date"):
            DATES[contest] = rec["date"]  # official date printed in the organiser's PDF

    # ---- MathArena contests ----
    for hf, (cat, contest, official) in MATHARENA.items():
        rows = load(hf.replace("/", "__") + "__default__train.jsonl")
        for r in rows:
            idx = int(r["problem_idx"])
            q = str(r["problem"])
            ans = str(r["answer"]).strip()
            ans = re.sub(r"\s+", " ", ans)
            if cat == "AIME" and contest in ("AIME 2026", "AIME 2025"):
                part = "I" if idx <= 15 else "II"
                c = f"{contest} {part}"
                pnum = idx if idx <= 15 else idx - 15
            else:
                c, pnum = contest, idx
            year = int(re.search(r"(\d{4})", contest).group(1))
            rec = {"source": hf, "source_id": str(idx), "source_url": HF + hf, "licence": MA_LIC,
                   "source_date": DATES[c], "question": q, "options": [], "answer": ans,
                   "category": cat, "strata": {"contest": c, "year": year, "problem_number": pnum,
                                               "topic": (r.get("problem_type") or None),
                                               "difficulty_proxy": pnum}, "_official": official,
                   "_apex_source": r.get("source")}
            # mechanical exclusions
            if not ans:
                excl[f"{hf}:empty_answer"] += 1; excl_detail["empty_answer"].append((hf, idx)); continue
            if FIG_RE.search(q):
                excl[f"{hf}:figure_reference"] += 1; excl_detail["figure_reference"].append((hf, idx)); continue
            if PROOF_RE.search(q):
                excl[f"{hf}:proof_problem"] += 1; excl_detail["proof_problem"].append((hf, idx)); continue
            if cat == "AIME":
                if not INT_RE.fullmatch(ans) or not 0 <= int(ans) <= 999:
                    excl[f"{hf}:aime_key_not_0_999"] += 1; excl_detail["aime_key_not_0_999"].append((hf, idx, ans)); continue
                rec["answer"] = str(int(ans)); rec["key_type"] = "integer"
            else:
                rec["key_type"] = "integer" if INT_RE.fullmatch(ans) else "expression"
                if rec["key_type"] == "integer":
                    rec["answer"] = str(int(ans))
            # verification
            tables = {}
            if c.startswith("AIME 2025"):
                tables = {"opencompass/AIME2025": oc[part], "yentinglin/aime_2025": yl[part]}
            elif c.startswith("AIME 2024") or c.startswith("AIME 2023"):
                tables = {"AI-MO/aimo-validation-aime": aimo[(year, c.split()[-1])]}
            ev = cross_check(q, rec["answer"], tables) if tables else None
            pdf_ans, pdf_round = None, None
            if contest in hmmt_pdf:
                pr = hmmt_pdf[contest]
                pdf_ans = pr["answers"].get(str(idx)) or None
                # alignment guard: the PDF problem head must match this problem's text, else no comparison is made
                if pdf_ans and difflib.SequenceMatcher(None, alnum(q)[:150], alnum(pr["heads"].get(str(idx), ""))[:150]).ratio() < 0.5:
                    pdf_ans = None
                nr = len(pr["rounds"]) * pr["round_size"]
                pdf_round = pr["rounds"][(idx - 1) // pr["round_size"]] if idx <= nr else None
                if idx > nr:  # HMMT Feb 2026 extra problems come from the team round; match by text head
                    sim, hit = max(((difflib.SequenceMatcher(None, alnum(q)[:150], alnum(e["head"])[:150]).ratio(), e)
                                    for e in pr["team_extra"]), key=lambda t: t[0])
                    if sim >= 0.6 and hit["answer"]:
                        pdf_ans, pdf_round = hit["answer"], f"team#{hit['n']}"
            if ev:
                if not all(v["agree"] for v in ev.values()):
                    excl[f"{hf}:cross_source_disagreement"] += 1
                    disagreements.append({"source": hf, "problem_idx": idx, "answer": rec["answer"], "evidence": ev})
                    continue
                rec["verification"] = {"method": "two-source agreement", "verified": True,
                                       "evidence": {"primary_answer": rec["answer"], "key_format": rec["key_type"],
                                                    "cross_sources": ev}}
            elif pdf_ans is not None:
                pdf_url = pr["round_urls"][str(pdf_round).split("#")[0]]
                if not pdf_agree(rec["answer"], pdf_ans):
                    excl[f"{hf}:official_pdf_disagreement"] += 1
                    disagreements.append({"source": hf, "problem_idx": idx, "answer": rec["answer"],
                                          "evidence": {"official_pdf": pdf_url, "pdf_answer_raw": pdf_ans}})
                    continue
                rec["verification"] = {"method": "official-pdf agreement", "verified": True,
                                       "evidence": {"primary_answer": rec["answer"], "key_format": rec["key_type"],
                                                    "official_pdf": pdf_url, "pdf_round": pdf_round,
                                                    "pdf_answer_raw": pdf_ans, "canonical": canon_pdf(rec["answer"])}}
            else:
                rec["verification"] = {"method": "single-source (MathArena transcription of official key)",
                                       "verified": True,
                                       "evidence": {"primary_answer": rec["answer"], "key_format": rec["key_type"],
                                                    "format_check": "passed", "official_page": official,
                                                    "cross_source_attempted": bool(tables),
                                                    "official_pdf_attempted": contest in hmmt_pdf,
                                                    "official_pdf_result": "answer line not parsed" if contest in hmmt_pdf else None}}
            candidates.append(rec)

    # ---- gneubig AIME archive (1983-2024), minus years covered by MathArena ----
    gsrc = "gneubig/aime-1983-2024"
    for r in load("gneubig__aime-1983-2024__default__train.jsonl"):
        year, part, pnum = int(r["Year"]), r.get("Part"), int(r["Problem Number"])
        if year in (2023, 2024):
            excl[f"{gsrc}:year_covered_by_matharena"] += 1; continue
        q = str(r["Question"]); ans = str(r["Answer"]).strip()
        c = f"AIME {year}" + (f" {part}" if part else "")
        d = DATES.get(c, f"{year}-03-01")
        rec = {"source": gsrc, "source_id": str(r["ID"]), "source_url": HF + gsrc, "licence": "CC0-1.0",
               "source_date": d, "question": q, "options": [], "answer": ans, "key_type": "integer",
               "category": "AIME", "strata": {"contest": c, "year": year, "problem_number": pnum, "topic": None,
                                              "difficulty_proxy": pnum}, "_official": "https://maa.org/student-programs/amc/"}
        if not ans:
            excl[f"{gsrc}:empty_answer"] += 1; continue
        if FIG_RE.search(q):
            excl[f"{gsrc}:figure_reference"] += 1; excl_detail["figure_reference"].append((gsrc, r["ID"])); continue
        if PROOF_RE.search(q):
            excl[f"{gsrc}:proof_problem"] += 1; excl_detail["proof_problem"].append((gsrc, r["ID"])); continue
        if not INT_RE.fullmatch(ans) or not 0 <= int(ans) <= 999:
            excl[f"{gsrc}:aime_key_not_0_999"] += 1; excl_detail["aime_key_not_0_999"].append((gsrc, r["ID"], ans)); continue
        rec["answer"] = str(int(ans))
        tables = {"AI-MO/aimo-validation-aime": aimo[(year, part)]} if (year, part) in aimo else {}
        ev = cross_check(q, rec["answer"], tables) if tables else None
        if ev:
            if not all(v["agree"] for v in ev.values()):
                excl[f"{gsrc}:cross_source_disagreement"] += 1
                disagreements.append({"source": gsrc, "problem_idx": r["ID"], "answer": rec["answer"], "evidence": ev})
                continue
            rec["verification"] = {"method": "two-source agreement", "verified": True,
                                   "evidence": {"primary_answer": rec["answer"], "key_format": "integer", "cross_sources": ev}}
        else:
            rec["verification"] = {"method": "single-source (AoPS-wiki transcription of official key, gneubig/aime-1983-2024)",
                                   "verified": True,
                                   "evidence": {"primary_answer": rec["answer"], "key_format": "integer",
                                                "format_check": "passed", "official_page": rec["_official"],
                                                "cross_source_attempted": bool(tables)}}
        candidates.append(rec)

    # ---- overlap with MathArena/final_answer_comps (repackaging; never counted) ----
    fac = load("MathArena__final_answer_comps__default__train.jsonl")
    fac_texts = {norm_text(r["problem"]) for r in fac}
    fac_overlap = sum(1 for c in candidates if norm_text(c["question"]) in fac_texts)

    # ---- duplicates across all sources: keep earliest-dated copy ----
    by_text = defaultdict(list)
    for c in candidates:
        by_text[norm_text(c["question"])].append(c)
    kept, dup_log = [], []
    for k, group in by_text.items():
        group.sort(key=lambda c: (c["category"] == "APEX", c["source_date"], c["source"], c["source_id"]))
        kept.append(group[0])
        for g in group[1:]:
            excl[f"{g['source']}:duplicate_text"] += 1
            dup_log.append({"kept": (group[0]["source"], group[0]["source_id"]), "dropped": (g["source"], g["source_id"])})
    kept.sort(key=lambda c: (c["source"], c["source_id"]))

    # ---- sampling (stratified by contest family x year band) if above TARGET ----
    sampled_down = False
    if len(kept) > TARGET:
        sampled_down = True
        rng = random.Random(SEED)
        strata = defaultdict(list)
        for c in kept:
            strata[(c["category"], c["strata"]["year"] // 5 * 5)].append(c)
        frac = TARGET / len(kept)
        out = []
        for key in sorted(strata):
            grp = strata[key]
            rng.shuffle(grp)
            out += grp[: max(1, round(len(grp) * frac))]
        kept = out[:TARGET]

    # ---- id assignment from the frozen base manifest (ids were drawn by seeded shuffle on 2026-10-25) ----
    import hashlib
    items, removed = [], []
    for c in kept:
        m = MANIFEST.get(f"{c['source']}||{c['source_id']}")
        assert m, ("base item not in manifest", c["source"], c["source_id"])
        sha = hashlib.sha256(json.dumps([c["source"], c["source_id"], c["question"], c["answer"]]).encode()).hexdigest()
        assert sha == m["content_sha256"], ("base content changed", c["source"], c["source_id"])
        c["_id"] = m["id"]
    present = {c["_id"] for c in kept}
    removed = sorted(v["id"] for v in MANIFEST.values() if v["id"] not in present)
    kept.sort(key=lambda c: c["_id"])
    for c in kept:
        post, per_dev = date_flags(c["source_date"])
        it = {"id": c.pop("_id"), "domain": "math"}
        it.update({k: v for k, v in c.items() if not k.startswith("_")})
        it["post_cutoff"], it["post_cutoff_by_developer"] = post, per_dev
        if c.get("_apex_source"):
            it["strata"]["apex_source"] = c["_apex_source"]
        items.append(it)
    base_lines = [json.dumps(it, ensure_ascii=False) + "\n" for it in items]
    base_sha = hashlib.sha256("".join(base_lines).encode()).hexdigest()
    n_base = len(items)
    assert n_base + len(removed) == FROZEN_BASE_N, (n_base, removed)

    # ---- top-up: Hendrycks MATH test Level 5 (add_math_level5.py), ids continue after the frozen base ----
    existing = {norm_text(it["question"]) for it in items}
    new_items, math_report = add_math_level5.build(existing, TARGET - len(items), SEED)
    random.Random(SEED).shuffle(new_items)
    for j, c in enumerate(new_items, FROZEN_BASE_N + 1):
        post, per_dev = date_flags(c["source_date"])
        it = {"id": f"M{j:04d}", "domain": "math"}
        it.update(c)
        it["post_cutoff"], it["post_cutoff_by_developer"] = post, per_dev
        items.append(it)
    with open(POOL_DIR / "pool.jsonl", "w") as f:
        f.writelines(base_lines)
        for it in items[n_base:]:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")

    report = {
        "seed": SEED, "target": TARGET, "n_items": len(items), "sampled_down": sampled_down,
        "per_contest": dict(sorted(Counter(it["strata"]["contest"] for it in items).items())),
        "per_source": dict(sorted(Counter(it["source"] for it in items).items())),
        "per_category": dict(sorted(Counter(it["category"] for it in items).items())),
        "per_method": dict(Counter(it["verification"]["method"] for it in items)),
        "exclusions": dict(sorted(excl.items())),
        "exclusion_detail": {k: v[:200] for k, v in excl_detail.items()},
        "disagreements": disagreements, "duplicates": dup_log,
        "final_answer_comps_overlap": fac_overlap,
        "post_cutoff": Counter(it["post_cutoff"] for it in items)[True],
        "post_cutoff_by_developer": {d: sum(it["post_cutoff_by_developer"][d] for it in items) for d in DEVELOPER_CUTOFFS},
        "frozen_base": {"manifest_n": FROZEN_BASE_N, "retained": n_base, "removed_ids": removed, "line_sha256": base_sha},
        "math_level5": math_report,
    }
    (POOL_DIR / "build_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items() if k not in ("exclusion_detail", "duplicates")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
