"""Shared schema checker for MetaBench main-study pools. Pure functions; no I/O except reading the pool."""
from __future__ import annotations
import json, re
from collections import Counter
from datetime import date
from pathlib import Path

CUTOFF_REFERENCE = date(2026, 6, 30)
DEVELOPER_CUTOFFS = {"anthropic": date(2026, 6, 30), "openai": date(2025, 12, 1),
                     "google": date(2025, 1, 1), "xai": date(2026, 5, 31)}
KEY_TYPES = {"integer", "expression", "letter", "string", "tests"}
REQUIRED = ["id", "domain", "source", "source_id", "source_url", "licence", "source_date", "question",
            "options", "answer", "key_type", "category", "strata", "verification", "post_cutoff",
            "post_cutoff_by_developer"]
CODE_REQUIRED = ["tests", "reference_solution", "language", "time_limit_s", "memory_limit_mb"]
LETTERS = "ABCDEFGHIJ"


def load(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def parse_date(s: str) -> date:
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def check_item(it: dict, prefix: str) -> list[str]:
    errs = []
    for k in REQUIRED:
        if k not in it:
            errs.append(f"missing {k}")
    if errs:
        return errs
    if not re.fullmatch(prefix + r"\d{4,5}", it["id"]):
        errs.append(f"bad id {it['id']}")
    for k in ("domain", "source", "source_id", "source_url", "licence", "question", "answer", "category"):
        if not isinstance(it[k], str) or not it[k].strip():
            errs.append(f"{k} empty or not str")
    if not it["source_url"].startswith("http"):
        errs.append("source_url not http")
    try:
        d = parse_date(it["source_date"])
    except Exception:
        errs.append(f"bad source_date {it['source_date']}")
        d = None
    if d is not None:
        if d > date(2026, 10, 25):
            errs.append("source_date in the future")
        if it["post_cutoff"] != (d > CUTOFF_REFERENCE):
            errs.append("post_cutoff inconsistent with source_date")
        for dev, cut in DEVELOPER_CUTOFFS.items():
            if it["post_cutoff_by_developer"].get(dev) != (d > cut):
                errs.append(f"post_cutoff_by_developer[{dev}] inconsistent")
    if it["key_type"] not in KEY_TYPES:
        errs.append(f"bad key_type {it['key_type']}")
    if not isinstance(it["options"], list):
        errs.append("options not list")
    if it["key_type"] == "letter":
        n = len(it["options"])
        if n < 2 or it["answer"] not in LETTERS[:n]:
            errs.append("letter key outside options")
    else:
        if it["options"]:
            errs.append("non-letter item has options")
    if it["key_type"] == "integer" and not re.fullmatch(r"-?\d+", it["answer"]):
        errs.append(f"integer key not an integer: {it['answer']!r}")
    v = it["verification"]
    if not (isinstance(v, dict) and v.get("verified") is True and isinstance(v.get("method"), str)
            and isinstance(v.get("evidence"), dict) and v["evidence"]):
        errs.append("verification missing method/verified/evidence")
    if not isinstance(it["strata"], dict) or not it["strata"]:
        errs.append("strata empty")
    if it["key_type"] == "tests":
        for k in CODE_REQUIRED:
            if k not in it:
                errs.append(f"code item missing {k}")
        if it.get("answer") != "tests":
            errs.append("code answer must be 'tests'")
        if isinstance(it.get("tests"), list) and len(it["tests"]) < 1:
            errs.append("code item has no tests")
    return errs


def check_pool(path: Path, prefix: str, domain: str, min_items: int) -> dict:
    items = load(path)
    report = {"n": len(items), "errors": [], "duplicates": []}
    ids = Counter(it["id"] for it in items)
    report["duplicates"] += [f"dup id {k}" for k, c in ids.items() if c > 1]
    texts = Counter(re.sub(r"\s+", " ", it["question"].strip().lower()) for it in items)
    report["duplicates"] += [f"dup question text ({c}x): {k[:80]}" for k, c in texts.items() if c > 1]
    srcs = Counter((it["source"], it["source_id"]) for it in items)
    report["duplicates"] += [f"dup source id {k}" for k, c in srcs.items() if c > 1]
    for it in items:
        e = check_item(it, prefix)
        if it.get("domain") != domain:
            e.append(f"domain {it.get('domain')} != {domain}")
        if e:
            report["errors"].append((it.get("id"), e))
    if len(items) < min_items:
        report["errors"].append(("POOL", [f"only {len(items)} items < {min_items}"]))
    report["ok"] = not report["errors"] and not report["duplicates"]
    return report
