"""Extract official BRUMO 2025 and CMIMC 2025 answers from the organisers' solutions PDFs (same parser as HMMT).

Input: pools/_work/math/pdf_other/brumo_*.pdf (https://www.brumo.org/s/<file>) and cmimc2025_*_sol.pdf
(https://cmimc.math.cmu.edu/archive/cmimc2025/<round>_sol.pdf). Output: pools/math/other_pdf_answers.json in the same
shape as hmmt_pdf_answers.json plus "round_urls". MathArena problem_idx mapping: BRUMO 1-15 individual, 16-30 team;
CMIMC 1-10 algnt, 11-20 combo, 21-30 geo, 31-40 team (checked against the first problem of each round).
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from hmmt_pdf_answers import parse_round, pdf_text  # noqa: E402
PDF = HERE.parents[2] / "pools/_work/math/pdf_other"
OUT = HERE.parent / "other_pdf_answers.json"
CONTESTS = {
    "BRUMO 2025": [("individual", "brumo_individual-solutions.pdf", 15, "https://www.brumo.org/s/individual-solutions.pdf"),
                   ("team", "brumo_team-solutions.pdf", 15, "https://www.brumo.org/s/team-solutions.pdf")],
    "CMIMC 2025": [(r, f"cmimc2025_{r}_sol.pdf", 10, f"https://cmimc.math.cmu.edu/archive/cmimc2025/{r}_sol.pdf")
                   for r in ("algnt", "combo", "geo", "team")],
}


def main() -> int:
    out = {}
    for contest, rounds in CONTESTS.items():
        answers, heads, dates, urls, offset = {}, {}, set(), {}, 0
        for rnd, fname, size, url in rounds:
            urls[rnd] = url
            d, probs = parse_round(pdf_text(PDF / fname), nmax=size)
            if d: dates.add(d)
            for n, head, ans in probs:
                answers[str(offset + n)] = ans
                heads[str(offset + n)] = re.sub(r"\s+", " ", head)[:200]
            offset += size
        out[contest] = {"date": sorted(dates)[0] if dates else None, "dates_seen": sorted(dates), "answers": answers,
                        "heads": heads, "rounds": [r[0] for r in rounds], "round_size": rounds[0][2], "round_urls": urls, "team_extra": []}
        print(contest, sorted(dates), "n answers", len(answers))
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
