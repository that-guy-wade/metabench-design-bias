"""Extract official HMMT answers (and the contest date) from organiser solutions PDFs.

Input: pools/_work/math/pdf/<year>_<feb|nov>_<round>.pdf downloaded from
https://hmmt-archive.s3.amazonaws.com/tournaments/<year>/<feb|nov>/<round>/solutions.pdf
Output: pools/math/hmmt_pdf_answers.json  {contest: {"date": "YYYY-MM-DD", "answers": {idx: raw_answer}, "rounds": [...]}}
MathArena problem_idx mapping (checked against the PDFs' first problems): Feb 1-10 algnt, 11-20 comb, 21-30 geo;
Nov 1-10 gen, 11-20 thm, 21-30 team. Feb 2026 idx 31-33 are matched by problem text against the team round.
"""
from __future__ import annotations
import json, re, sys
from datetime import datetime
from pathlib import Path
from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PDF = ROOT / "pools/_work/math/pdf"
OUT = HERE.parent / "hmmt_pdf_answers.json"
CONTESTS = {"HMMT Feb 2023": ("2023_feb", ["algnt", "comb", "geo"]), "HMMT Feb 2024": ("2024_feb", ["algnt", "comb", "geo"]),
            "HMMT Feb 2025": ("2025_feb", ["algnt", "comb", "geo"]), "HMMT Feb 2026": ("2026_feb", ["algnt", "comb", "geo"]),
            "HMMT Nov 2025": ("2025_nov", ["gen", "thm", "team"])}
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


def pdf_text(p: Path) -> str:
    return "\n".join(pg.extract_text() or "" for pg in PdfReader(p).pages)


ANSWER_PATTERNS = [re.compile(r"Answer[:.]\s*(.{0,120}?)\n\s*Solution", re.S), re.compile(r"Answer[:.]\s*(.*?)\n")]
STRIP_PATTERNS = [r"©\d{4} HMMT", r"BrUMO \d{4} .*?Solutions April \d+, \d{4}"]  # per-page headers/footers


def parse_round(text: str, nmax: int = 10, answer_patterns=ANSWER_PATTERNS, strip_patterns=STRIP_PATTERNS
                ) -> tuple[str | None, list[tuple[int, str, str]]]:
    """Return (date, [(problem_number, problem_text_head, answer_raw)]), parsed sequentially: problem N is searched
    only after problem N-1's answer, so numbers appearing inside solutions cannot be mistaken for headers.
    Answer patterns are tried in order (up to the next 'Solution' line first, then the rest of the line)."""
    text = text.replace("F ebruary", "February").replace("T eam", "Team")
    m = re.search(rf"(?:{MONTHS})\s+\d{{1,2}},\s+\d{{4}}", text)
    d = datetime.strptime(m.group(0), "%B %d, %Y").strftime("%Y-%m-%d") if m else None
    for sp in strip_patterns:
        text = re.sub(sp, "", text)
    probs, pos = [], 0
    for n in range(1, nmax + 1):
        h = re.compile(rf"(?:^|\n){n}\.\s*(?:\[\d+\]\s*)?").search(text, pos)
        if not h:
            break
        nxt = re.compile(rf"(?:^|\n){n + 1}\.\s*(?:\[\d+\]\s*)?").search(text, h.end())
        a = None
        for pat in answer_patterns:
            a = pat.search(text, h.end())
            if a and not (nxt and a.start() > nxt.start()):
                break
            a = None
        if not a:
            probs.append((n, text[h.end(): h.end() + 300], ""))
            pos = nxt.start() if nxt else len(text)
            continue
        head = re.sub(r"Proposed by:?.*", "", text[h.end(): a.start()], flags=re.S)
        probs.append((n, head, a.group(1).strip()))
        pos = a.end()
    return d, probs


def main() -> int:
    out = {}
    for contest, (stem, rounds) in CONTESTS.items():
        answers, heads, dates = {}, {}, set()
        for ri, rnd in enumerate(rounds):
            p = PDF / f"{stem}_{rnd}.pdf"
            if not p.exists():
                print("missing", p); continue
            d, probs = parse_round(pdf_text(p))
            if d: dates.add(d)
            seen = set()
            for n, head, ans in probs:
                if n in seen or not 1 <= n <= 10: continue
                seen.add(n)
                answers[str(ri * 10 + n)] = ans
                heads[str(ri * 10 + n)] = re.sub(r"\s+", " ", head)[:200]
        team = PDF / f"{stem}_team.pdf"
        extra = []
        if team.exists() and "team" not in rounds:
            _, probs = parse_round(pdf_text(team))
            extra = [{"n": n, "head": re.sub(r"\s+", " ", h)[:200], "answer": a} for n, h, a in probs]
        yr, mo = stem.split("_")
        urls = {r: f"https://hmmt-archive.s3.amazonaws.com/tournaments/{yr}/{mo}/{r}/solutions.pdf" for r in rounds + ["team"]}
        out[contest] = {"date": sorted(dates)[0] if dates else None, "dates_seen": sorted(dates), "answers": answers,
                        "heads": heads, "team_extra": extra, "rounds": rounds, "round_size": 10, "round_urls": urls}
        print(contest, "date", sorted(dates), "n answers", len(answers), "team extra", len(extra))
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
