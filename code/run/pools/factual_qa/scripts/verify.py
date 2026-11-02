"""Verify every SimpleQA key against the cached text of its cited pages. Pure, deterministic; reads only the CSV, the
fetch log and pools/_work/factual_qa/pages/. Writes pools/_work/factual_qa/verified.jsonl (one record per CSV row).

Match rule (fixed 2026-10-25 before any page was inspected):
  normalise(s) = NFKC -> casefold -> every char that is not a letter, digit or whitespace becomes a space -> collapse
  whitespace -> strip.  An item is verified when, for at least one cited page, one of these forms is found:
   * exact : normalise(answer) (>= 2 chars) is a substring of normalise(page)
   * digits: numeric answers only (answer_type == Number, or the answer is only digits/space/.,): thousands commas are
             removed from answer and page, the digits-only answer (>= 2 digits) must occur in normalise(page) bounded by
             non-digits
   * date  : if the answer parses as D Month YYYY / Month D, YYYY / YYYY-MM-DD / Month YYYY (English month names or
             3-letter abbreviations, optional ordinal suffix), any standard English long/short rendering of that same
             date is accepted as a substring of normalise(page)
Forms are tried in the order exact, digits, date; the first hit is the evidence. No fuzzy matching.
"""
from __future__ import annotations
import ast, csv, hashlib, json, re, sys, unicodedata
from collections import Counter
from pathlib import Path

WORK = Path(__file__).resolve().parents[2] / "_work" / "factual_qa"
CSV, LOG, PAGES, OUT = WORK / "simple_qa_test_set.csv", WORK / "fetch_log.jsonl", WORK / "pages", WORK / "verified.jsonl"
METHOD = "cited_page_substring_match_v1"
SNIPPET_PAD = 100

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
MON3 = {m[:3]: i for i, m in enumerate(MONTHS, 1)}
MON3["sept"] = 9
MONTH_RE = "(" + "|".join(MONTHS + list(MON3)) + ")"
ORD = r"(?:st|nd|rd|th)?"
DATE_PATTERNS = [
    re.compile(rf"^(?:the )?(?P<d>\d{{1,2}}){ORD}(?: of)? {MONTH_RE.replace('(', '(?P<m>', 1)} (?P<y>\d{{4}})$"),
    re.compile(rf"^{MONTH_RE.replace('(', '(?P<m>', 1)} (?P<d>\d{{1,2}}){ORD} (?P<y>\d{{4}})$"),
    re.compile(r"^(?P<y>\d{4}) (?P<m>\d{1,2}) (?P<d>\d{1,2})$"),
    re.compile(rf"^{MONTH_RE.replace('(', '(?P<m>', 1)} (?P<y>\d{{4}})$"),
]
_NONWORD = re.compile(r"[^\w\s]|_")
_WS = re.compile(r"\s+")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d)")


def normalise(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).casefold()
    return _WS.sub(" ", _NONWORD.sub(" ", s)).strip()


def _month_num(tok: str) -> int:
    return MONTHS.index(tok) + 1 if tok in MONTHS else MON3[tok]


def ordinal(d: int) -> str:
    return f"{d}{'th' if 11 <= d % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(d % 10, 'th')}"


def date_forms(answer: str) -> list[str]:
    """Deterministic alternative renderings of a date-shaped answer, already normalised. [] if not date-shaped."""
    a = normalise(answer)
    for pat in DATE_PATTERNS:
        m = pat.match(a)
        if not m:
            continue
        g = m.groupdict()
        mt = g["m"]
        try:
            mnum = int(mt) if mt.isdigit() else _month_num(mt)
        except (ValueError, KeyError):
            return []
        if not 1 <= mnum <= 12:
            return []
        y, M, m3 = g["y"], MONTHS[mnum - 1], MONTHS[mnum - 1][:3]
        if g.get("d") is None:
            return [f"{M} {y}", f"{m3} {y}", f"{y} {mnum:02d}"]
        d = int(g["d"])
        if not 1 <= d <= 31:
            return []
        o = ordinal(d)
        return [f"{d} {M} {y}", f"{M} {d} {y}", f"{o} {M} {y}", f"{M} {o} {y}", f"{o} of {M} {y}",
                f"{d} {m3} {y}", f"{m3} {d} {y}", f"{y} {mnum:02d} {d:02d}", f"{d:02d} {M} {y}"]
    return []


def is_numeric(answer: str, answer_type: str) -> bool:
    return answer_type == "Number" or bool(re.fullmatch(r"[\d\s.,]+", answer.strip()))


def digits_form(answer: str) -> str:
    return re.sub(r"\D", "", _THOUSANDS.sub("", answer))


def match_in(norm_text: str, answer: str, answer_type: str, *, numeric_text: str | None = None):
    """Return (form, matched_string, start, end, text_used) or None. text_used is the string the offsets refer to."""
    a = normalise(answer)
    if len(a) >= 2:
        i = norm_text.find(a)
        if i >= 0:
            return "exact", a, i, i + len(a), norm_text
    if is_numeric(answer, answer_type):
        dg = digits_form(answer)
        if len(dg) >= 2:
            nt = numeric_text if numeric_text is not None else norm_text
            m = re.search(rf"(?<!\d){re.escape(dg)}(?!\d)", nt)
            if m:
                return "digits", dg, m.start(), m.end(), nt
    for f in date_forms(answer):
        i = norm_text.find(f)
        if i >= 0:
            return "date", f, i, i + len(f), norm_text
    return None


def snippet_matches(snippet: str, form: str, matched: str) -> bool:
    """The rule a stored snippet must satisfy (used by test_factual_qa_schema.py)."""
    if form == "digits":
        return re.search(rf"(?<!\d){re.escape(matched)}(?!\d)", snippet) is not None
    return matched in snippet


def main() -> int:
    log: dict[str, dict] = {}
    with open(LOG, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                log[r["url"]] = r
    norm_cache: dict[str, tuple[str, str | None]] = {}

    def page_text(url: str):
        rec = log.get(url)
        if not rec or not rec.get("page_sha256"):
            return None
        if url not in norm_cache:
            raw = (PAGES / f"{rec['url_sha256']}.txt").read_text(encoding="utf-8")
            norm_cache[url] = (normalise(raw), None)
        return norm_cache[url]

    def numeric_text(url: str) -> str:
        nt, num = norm_cache[url]
        if num is None:
            raw = (PAGES / f"{log[url]['url_sha256']}.txt").read_text(encoding="utf-8")
            num = normalise(_THOUSANDS.sub("", raw))
            norm_cache[url] = (nt, num)
        return num

    counts = Counter()
    with open(CSV, newline="", encoding="utf-8") as f, open(OUT, "w", encoding="utf-8") as out:
        for row_idx, row in enumerate(csv.DictReader(f)):
            meta = ast.literal_eval(row["metadata"])
            urls = [u.strip() for u in meta["urls"] if u.strip()]
            answer, atype = row["answer"], meta["answer_type"]
            rec = {"row": row_idx, "topic": meta["topic"], "answer_type": atype, "urls": urls, "question": row["problem"],
                   "answer": answer, "status": None, "evidence": None}
            n_fetched = n_logged = 0
            for u in urls:
                if u in log:
                    n_logged += 1
                pt = page_text(u)
                if pt is None:
                    continue
                n_fetched += 1
                numeric = numeric_text(u) if is_numeric(answer, atype) else None
                hit = match_in(pt[0], answer, atype, numeric_text=numeric)
                if hit:
                    form, matched, s, e, used = hit
                    rec["status"] = "verified"
                    rec["evidence"] = {"url": u, "fetched_at": log[u]["fetched_at"], "page_sha256": log[u]["page_sha256"],
                                       "match_form": form, "matched": matched,
                                       "snippet": used[max(0, s - SNIPPET_PAD): e + SNIPPET_PAD]}
                    break
            if rec["status"] is None:
                if n_logged < len(urls):
                    rec["status"] = "not_fetched"      # interim: fetch still running / incomplete
                elif n_fetched == 0:
                    rec["status"] = "fetch_failed"
                else:
                    rec["status"] = "no_match"
            counts[rec["status"]] += 1
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(counts), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
