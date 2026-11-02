"""Health checker for the blinded view (docs/ARTEFACT_SCHEMA.md section 7, BLINDING.md section 4).

Reports ONLY: schema validity, parse rates, validity flags, API failures, hash flags, time-of-day interleaving across
arm codes, and per-designer-code / per-arm-code session counts against the registered number plus decoys.  It never
computes a statistic over scores_shifted or anything per evaluee, and refuses a view that carries a forbidden key.

CLI:  python scripts_health_check.py --view health_view.jsonl [--frozen-sizes prereg/frozen_sizes.json]
          [--n-designers 12] [--decoys-per-designer 3]
JSON report on stdout; a short markdown table on stderr.  Exit 2 when refused, 1 when any check fails, else 0.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from scipy.stats import kruskal

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scripts_health_view import FROZEN_SIZES, ROW_KEYS as TOP_KEYS, load_frozen_cells  # noqa: E402

FORBIDDEN = {"session_id", "designer", "info_arm", "identity_arm", "label_map", "displayed_order", "reference_scores",
             "notes", "config_hash", "seed", "decoy"}
FORBIDDEN_SUBSTRINGS = ("decoy", "seed")
N_EVALUEES = 17
FILE_KEYS = ["config", "actions", "transcript", "scores_views", "benchmark", "item_outcomes", "probes"]
PARSE_KEYS = ["actions_ok_rate", "monitor_json_rate", "item_outcomes_rows"]


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v) -> bool:
    return _is_int(v) or isinstance(v, float)


def forbidden_keys(rows: list[dict]) -> list[str]:
    """Every key (at any nesting depth) that names raw-data information."""
    found: set[str] = set()

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in FORBIDDEN or any(s in k for s in FORBIDDEN_SUBSTRINGS):
                    found.add(k)
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(rows)
    return sorted(found)


def row_violations(row: dict) -> list[str]:
    v: list[str] = []
    if set(row) != set(TOP_KEYS):
        v.append(f"keys: extra={sorted(set(row) - set(TOP_KEYS))} missing={sorted(set(TOP_KEYS) - set(row))}")
        return v
    checks = [("view_id", isinstance(row["view_id"], str) and re.fullmatch(r"HV-\d{4,}", row["view_id"])),
              ("designer_code", isinstance(row["designer_code"], str) and re.fullmatch(r"D\d{2}", row["designer_code"])),
              ("arm_code", isinstance(row["arm_code"], str) and re.fullmatch(r"A\d+", row["arm_code"])),
              ("identity_code", isinstance(row["identity_code"], str) and re.fullmatch(r"I\d", row["identity_code"])),
              ("status", isinstance(row["status"], str)), ("valid", isinstance(row["valid"], bool)),
              ("exit_code", _is_int(row["exit_code"]) and row["exit_code"] in (0, 1, 2)),
              ("n_items", _is_int(row["n_items"])), ("n_llm_calls", _is_int(row["n_llm_calls"])),
              ("api_errors", _is_int(row["api_errors"])), ("wall_s", _is_num(row["wall_s"])),
              ("started_at", isinstance(row["started_at"], str)), ("ended_at", isinstance(row["ended_at"], str)),
              ("n_score_requests", _is_int(row["n_score_requests"])), ("n_edits", _is_int(row["n_edits"])),
              ("hash_ok", isinstance(row["hash_ok"], bool)), ("code_hash_ok", isinstance(row["code_hash_ok"], bool))]
    for name, ok in checks:
        if not ok:
            v.append(f"{name}: bad type or value")
    files, parse, sc = row["files"], row["parse"], row["scores_shifted"]
    if not (isinstance(files, dict) and set(files) == set(FILE_KEYS) | {"monitors"}
            and all(isinstance(files[k], bool) for k in FILE_KEYS) and _is_int(files["monitors"])):
        v.append("files: bad keys or types")
    if not (isinstance(parse, dict) and set(parse) == set(PARSE_KEYS) and _is_num(parse["actions_ok_rate"])
            and _is_num(parse["monitor_json_rate"]) and _is_int(parse["item_outcomes_rows"])):
        v.append("parse: bad keys or types")
    if not (isinstance(sc, dict) and set(sc) == {f"E{i:02d}" for i in range(1, N_EVALUEES + 1)}
            and all(x is None or _is_num(x) for x in sc.values())):
        v.append("scores_shifted: bad keys or types")
    for f in ("started_at", "ended_at"):
        try:
            datetime.fromisoformat(row[f])
        except (TypeError, ValueError):
            v.append(f"{f}: not ISO-8601")
    return v


def _hour_of_day(s: str) -> float:
    dt = datetime.fromisoformat(s)
    dt = dt.astimezone(timezone.utc) if dt.tzinfo else dt
    return dt.hour + dt.minute / 60 + dt.second / 3600


def check(view_rows: list[dict], *, cells: dict[str, int] | None = None, n_designers: int = 12,
          decoys_per_designer: int = 3, replacements: list[dict] | None = None,
          all_cells: dict[str, int] | None = None) -> dict:
    """`cells`: the registered plan (per-designer counts per cell); `all_cells`: the 9 frozen cells over which the
    view builder spreads decoys (default: frozen sizes); `replacements`: rows {designer, info_arm, identity_arm} from
    prereg/confirmatory_replacements_<pool>.json, each adding one attempt to its designer and cell."""
    cells = load_frozen_cells() if cells is None else cells
    all_cells = load_frozen_cells() if all_cells is None else all_cells
    replacements = replacements or []
    bad = forbidden_keys(view_rows)
    if bad:
        return {"refused": True, "forbidden_keys": bad}
    rows = list(view_rows)
    viol: dict[str, list[str]] = {}
    ok_rows: list[dict] = []
    for i, r in enumerate(rows):
        v = row_violations(r)
        if v:
            viol[str(r.get("view_id", f"row{i}"))] = v
        else:
            ok_rows.append(r)

    def _stats(vals):
        return {"min": min(vals), "mean": sum(vals) / len(vals), "max": max(vals)} if vals else None

    parse = {"actions_ok_rate": _stats([r["parse"]["actions_ok_rate"] for r in ok_rows]),
             "monitor_json_rate": _stats([r["parse"]["monitor_json_rate"] for r in ok_rows]),
             "item_outcomes_rows": _stats([r["parse"]["item_outcomes_rows"] for r in ok_rows]),
             "files_present": {k: sum(1 for r in ok_rows if r["files"][k]) for k in FILE_KEYS},
             "monitor_verdict_sets": {str(k): n for k, n in sorted(Counter(r["files"]["monitors"] for r in ok_rows).items())}}
    validity = {"n_rows": len(rows), "n_valid": sum(1 for r in ok_rows if r["valid"]),
                "n_invalid": sum(1 for r in ok_rows if not r["valid"]),
                "by_status": dict(Counter(r["status"] for r in ok_rows)),
                "by_exit_code": {str(k): n for k, n in sorted(Counter(r["exit_code"] for r in ok_rows).items())}}
    api = {"api_errors_sum": sum(r["api_errors"] for r in ok_rows),
           "api_errors_max": max((r["api_errors"] for r in ok_rows), default=0),
           "rows_with_api_errors": sum(1 for r in ok_rows if r["api_errors"] > 0)}
    hashes = {"rows_hash_ok_false": sum(1 for r in ok_rows if not r["hash_ok"]),
              "rows_code_hash_ok_false": sum(1 for r in ok_rows if not r["code_hash_ok"])}

    # time-of-day interleaving across arm codes
    by_arm: dict[str, list[dict]] = {}
    for r in ok_rows:
        by_arm.setdefault(r["arm_code"], []).append(r)
    per_arm = {}
    for a in sorted(by_arm):
        h = [_hour_of_day(r["started_at"]) for r in by_arm[a]]
        per_arm[a] = {"n": len(h), "start_hour_min": min(h), "start_hour_median": statistics.median(h), "start_hour_max": max(h)}
    groups = [[datetime.fromisoformat(r["started_at"]).timestamp() for r in by_arm[a]] for a in sorted(by_arm)]
    p_value = None
    if len(groups) >= 2 and len({x for g in groups for x in g}) > 1:
        p_value = float(kruskal(*groups).pvalue)
    ordered = sorted(ok_rows, key=lambda r: datetime.fromisoformat(r["started_at"]).timestamp())
    switches = sum(1 for a, b in zip(ordered, ordered[1:]) if a["arm_code"] != b["arm_code"])
    timing = {"per_arm_code": per_arm, "kruskal_wallis_p_value_start_time": p_value,
              "arm_code_switch_share": (switches / (len(ordered) - 1)) if len(ordered) > 1 else None}

    # counts against the registration: designer and arm codes are secret permutations, so counts are compared as
    # sorted multisets; every replacement attempt adds one row to its designer and its cell
    registered_per_designer = sum(cells.values())
    rep_by_designer = Counter(r["designer"] for r in replacements)
    rep_by_cell = Counter(f"{r['info_arm']}_{r['identity_arm']}" for r in replacements)
    exp_designer_multiset = sorted(registered_per_designer + decoys_per_designer + k
                                   for k in list(rep_by_designer.values()) + [0] * (n_designers - len(rep_by_designer)))
    n_dec = n_designers * decoys_per_designer
    base, extra = divmod(n_dec, len(all_cells))
    exp_arm_multiset = sorted(n_designers * cells.get(c, 0) + base + (1 if i < extra else 0) + rep_by_cell.get(c, 0)
                              for i, c in enumerate(all_cells))
    exp_arm_multiset = [x for x in exp_arm_multiset if x > 0]
    des_counts = Counter(r["designer_code"] for r in ok_rows)
    arm_counts = Counter(r["arm_code"] for r in ok_rows)
    designer_codes = sorted(set(des_counts) | {f"D{i:02d}" for i in range(1, n_designers + 1)})
    exp_designer = registered_per_designer + decoys_per_designer       # the no-replacement expectation per code
    per_designer = {d: {"n": des_counts.get(d, 0), "expected_without_replacements": exp_designer,
                        "diff": des_counts.get(d, 0) - exp_designer} for d in designer_codes}
    counts = {"per_designer_code": per_designer,
              "designer_expected_multiset": exp_designer_multiset,
              "designer_counts_match_multiset": sorted(des_counts.get(d, 0) for d in designer_codes) == exp_designer_multiset,
              "designer_codes_short": [d for d, c in per_designer.items() if c["diff"] < 0],
              "designer_codes_over": [d for d, c in per_designer.items() if c["diff"] > 0],
              "per_arm_code": {a: arm_counts[a] for a in sorted(arm_counts)},
              "arm_code_expected_multiset": exp_arm_multiset,
              "arm_counts_match_registered_multiset": sorted(arm_counts.values()) == exp_arm_multiset,
              "n_arm_codes": len(arm_counts), "n_arm_codes_expected": len(exp_arm_multiset),
              "n_replacements_declared": len(replacements),
              "total_expected": sum(exp_designer_multiset), "total": len(rows)}
    passed = (not viol and counts["designer_counts_match_multiset"] and counts["arm_counts_match_registered_multiset"]
              and hashes["rows_hash_ok_false"] == 0 and hashes["rows_code_hash_ok_false"] == 0)
    return {"refused": False, "passed": passed,
            "schema": {"n_rows": len(rows), "n_violations": len(viol), "violation_examples": dict(list(viol.items())[:5])},
            "parse": parse, "validity": validity, "api_failures": api, "hash_flags": hashes, "timing": timing,
            "counts": counts}


def markdown(report: dict) -> str:
    if report.get("refused"):
        return f"REFUSED: forbidden keys in view: {', '.join(report['forbidden_keys'])}\n"
    c, t, v = report["counts"], report["timing"], report["validity"]
    lines = ["| check | value |", "|---|---|",
             f"| passed | {report['passed']} |",
             f"| rows / expected | {c['total']} / {c['total_expected']} |",
             f"| schema violations | {report['schema']['n_violations']} |",
             f"| valid / invalid | {v['n_valid']} / {v['n_invalid']} |",
             f"| exit codes | {v['by_exit_code']} |",
             f"| api_errors sum / max / rows>0 | {report['api_failures']['api_errors_sum']} / "
             f"{report['api_failures']['api_errors_max']} / {report['api_failures']['rows_with_api_errors']} |",
             f"| hash_ok false / code_hash_ok false | {report['hash_flags']['rows_hash_ok_false']} / "
             f"{report['hash_flags']['rows_code_hash_ok_false']} |",
             f"| actions_ok_rate min / mean | {_fmt(report['parse']['actions_ok_rate'])} |",
             f"| monitor_json_rate min / mean | {_fmt(report['parse']['monitor_json_rate'])} |",
             f"| designer codes short / over | {c['designer_codes_short']} / {c['designer_codes_over']} |",
             f"| arm counts match registration | {c['arm_counts_match_registered_multiset']} |",
             f"| Kruskal-Wallis p (start time by arm code) | {t['kruskal_wallis_p_value_start_time']} |",
             f"| arm-code switch share | {t['arm_code_switch_share']} |"]
    return "\n".join(lines) + "\n"


def _fmt(s: dict | None) -> str:
    return "n/a" if s is None else f"{s['min']:.3f} / {s['mean']:.3f}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--view", required=True, type=Path)
    ap.add_argument("--registered", type=Path, default=None,
                    help="prereg/confirmatory_hashes.json: the number of designers is taken from its session list")
    ap.add_argument("--frozen-sizes", type=Path, default=FROZEN_SIZES)
    ap.add_argument("--n-designers", type=int, default=12)
    ap.add_argument("--decoys-per-designer", type=int, default=3)
    ap.add_argument("--replacements", type=Path, default=None, help="prereg/confirmatory_replacements_<pool>.json")
    a = ap.parse_args(argv)
    rows = [json.loads(line) for line in a.view.read_text().splitlines() if line.strip()]
    n_designers = a.n_designers
    cells = load_frozen_cells(a.frozen_sizes)
    if a.registered:
        reg = json.loads(a.registered.read_text())
        n_designers = len({s["designer"] for s in reg["sessions"]})
        if reg.get("cells"):          # throwaway/smoke registrations carry their own (smaller) cell plan
            cells = dict(reg["cells"])
    reps = json.loads(a.replacements.read_text())["replacements"] if a.replacements and a.replacements.exists() else []
    report = check(rows, cells=cells, n_designers=n_designers, decoys_per_designer=a.decoys_per_designer, replacements=reps)
    print(json.dumps(report, indent=1))
    sys.stderr.write(markdown(report))
    return 2 if report["refused"] else (0 if report["passed"] else 1)


if __name__ == "__main__":
    sys.exit(main())
