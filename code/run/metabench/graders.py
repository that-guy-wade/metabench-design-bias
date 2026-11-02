"""Free-response graders and evaluee prompting for the main-study pools (Builder 2, 2026-10-25).

One entry point for the panel precompute, the live re-score of edited items and session scoring:
    grade(item, response_text) -> Grade(correct, parsed, pred, method, error)
dispatching on item["key_type"]:

  letter      pilot / held-out multiple-choice: unchanged pilot grader (pool.parse_answer, exact letter).
  integer     EXACT-ANSWER RULE.  The last line of the response of the form "Answer: <x>" is parsed (deterministic
  expression  regex; no "Answer:" line -> parse failure, scored 0 and counted).  Both key and prediction are
              normalised by `normalize_math`: last \\boxed{...} unwrapped; $, \\( \\), \\[ \\], \\displaystyle,
              \\left/\\right, thin spaces, \\text{..}/\\mathrm{..} wrappers, degree signs removed; \\dfrac/\\tfrac ->
              \\frac; \\frac{a}{b} and \\frac12 -> a/b ((a)/(b) when an argument is compound); braces around a single
              token dropped ({100} -> 100); \\cdot/\\times -> *; \\sqrt{x} -> sqrt(x); \\pi -> pi; function names lose
              the backslash; trailing . , ; : stripped; ALL whitespace removed; casefold.  Equal normalised strings ->
              correct ("exact").  Integer keys additionally accept any prediction whose normalised form is an integer
              literal (thousands separators removed, leading zeros ignored) equal to the key ("int").  Otherwise the
              SYMPY FALLBACK: both strings are converted to sympy (^ -> **, braces -> parentheses, \\binom -> binomial,
              ! factorial, ln -> log, inf -> oo, % -> /100, implicit multiplication) and are equivalent when
              (i) neither has free symbols and |a - b| <= 1e-9 * max(1, |a|, |b|) at 30-digit evaluation, or
              (ii) both have the same free symbols and agree at three fixed pseudo-random rational points to the same
              tolerance, with expand(a - b) == 0 as the symbolic confirmation when the numeric probe passes.
              Comma lists (tuples, solution sets, intervals) are compared element-wise after splitting at top-level
              commas; bracket shapes must match; an unordered match of <= 5 elements is also accepted ("sympy_set").
              Equations with one "=" are equivalent when (lhs - rhs) of one is +/- (lhs - rhs) of the other.
              Anything sympy cannot parse, or longer than 300 normalised characters, falls back to the string rule
              only.  Decimal keys are compared numerically, so 0.015 == 3/200; 1.4 != 1.4000001.
  string      FACTUAL-QA RULE (pools/factual_qa/PROVENANCE.md, `cited_page_substring_match_v1`, applied with the
              answer line in the role of the page).  normalise(s) = NFKC -> casefold -> every char that is not a letter,
              digit or whitespace becomes a space -> collapse whitespace -> strip (imported from the pool author's
              scripts/verify.py so the code is literally the same).  Correct when one of the three forms holds, in
              order: exact (normalise(key), >= 2 chars, appears in normalise(answer) at word boundaries); digits
              (numeric keys: thousands commas removed, the digits-only key, >= 2 digits, appears bounded by
              non-digits); date (any of the deterministic English renderings of a date-shaped key appears at word
              boundaries).  Two tightenings for grading (the page rule has none): the answer line must not hedge
              (" or " / "either" / "/" between alternatives -> incorrect, method "hedge") and its normalised form is
              at most 120 characters (longer -> incorrect, "too_long").  No LLM judge.
  tests       CODE RULE.  The last fenced ```python block of the response is the program (none -> parse failure).  It
              is executed in the Pool Author's bwrap sandbox (pools/code/scripts/sandbox.py + sbx_driver.py: no
              network, read-only system, 256 MiB tmpfs, system python3, RLIMIT_AS) against every stored test with the
              item's limits (verification.evidence.timeout_s = max(2 s, 3 x time_limit_s) and
              memory_limit_bytes_sandbox = max(1 GiB, 2 x memory limit), the same numbers the reference solution was
              verified with), stopping at the first failing test; token-wise output comparison with 1e-6 float
              tolerance (the driver's rule).  Correct iff every test passes.  Any sandbox/driver failure is scored
              incorrect and recorded in Grade.error (and in the precompute row as "grade_error").

Prompting (`evaluee_prompt`): one fixed instruction per key type (INSTRUCTIONS) + the item text; code items also show
the time and memory limits.  Letter items keep the pilot prompt byte-for-byte.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import itertools
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .pool import EVALUEE_INSTRUCTIONS, format_item_for_evaluee as _format_mc, parse_answer

ROOT = Path(__file__).resolve().parents[1]
SANDBOX_PY = ROOT / "pools" / "code" / "scripts" / "sandbox.py"
FACTUAL_VERIFY_PY = ROOT / "pools" / "factual_qa" / "scripts" / "verify.py"
GRADE_WORKERS = 6            # concurrent sandbox executions (CPU-bound; the API calls are the other bottleneck)
MAX_SYMPY_CHARS = 300
NUM_TOL = 1e-9
# Largest integer (in bits) the sympy fallback may evaluate: about 1.26 million decimal digits.  The pool's biggest key
# is 2024^{4046} (45 kbit).  Builder 5, 2026-10-26: unbounded towers such as 10^{10^{10}} in model output occupied the
# event-loop thread for hours and gigabytes; the estimate below is taken on the unevaluated parse tree.
MAX_EVAL_BITS = 1 << 22


@dataclass
class Grade:
    correct: int
    parsed: int
    pred: Optional[str]      # parsed answer (code: sha256[:16] of the program)
    method: str
    error: Optional[str] = None


# ----------------------------------------------------------------------------------------------
# Evaluee prompting
# ----------------------------------------------------------------------------------------------

INSTRUCTIONS = {
    "letter": EVALUEE_INSTRUCTIONS,
    "integer": ("Solve the following problem. You may reason briefly first. End your response with a final line of the "
                "form 'Answer: N' where N is the final integer answer (digits only, no units)."),
    "expression": ("Solve the following problem. You may reason briefly first. End your response with a final line of the "
                   "form 'Answer: X' where X is the exact final answer in LaTeX or plain text (for example "
                   "'Answer: \\frac{3}{4}' or 'Answer: 2\\sqrt{2}'); give one answer only."),
    "string": ("Answer the following question. You may reason briefly first. End your response with a final line of the "
               "form 'Answer: X' where X is only the answer itself (a name, date, number or short phrase), with no "
               "explanation on that line; give one answer only."),
    "tests": ("Write a complete Python 3 program that solves the following problem, reading its input from standard input "
              "and writing the result to standard output. You may reason briefly first. Your response must end with "
              "exactly one fenced code block (```python ... ```) containing the whole program and nothing after it."),
}


def key_type(item: dict) -> str:
    kt = item.get("key_type")
    if kt:
        return kt
    return "letter" if item.get("options") else "string"


def format_item_for_evaluee(item: dict) -> str:
    kt = key_type(item)
    if kt == "letter":
        return _format_mc(item)
    if kt == "tests":
        return (f"{item['question']}\n\nTime limit: {item.get('time_limit_s', 2)} s. Memory limit: "
                f"{int(round(float(item.get('memory_limit_mb', 256))))} MB. Input via stdin, output via stdout.")
    return item["question"]


def evaluee_prompt(item: dict) -> str:
    return INSTRUCTIONS[key_type(item)] + "\n\n" + format_item_for_evaluee(item)


# ----------------------------------------------------------------------------------------------
# Parsing (deterministic)
# ----------------------------------------------------------------------------------------------

_ANSWER_LINE = re.compile(r"^\s*(?:\*\*|__|`)*\s*answer\s*(?:\*\*|__|`)*\s*[:：]\s*(?:\*\*|__)*\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_FENCE = re.compile(r"```[ \t]*(?:python3?|py)?[ \t]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)


def parse_final_answer(text: str) -> Optional[str]:
    """The LAST 'Answer: <x>' line; None when absent."""
    m = _ANSWER_LINE.findall(text or "")
    if not m:
        return None
    a = m[-1].strip()
    a = a.strip("`").strip()
    while a.startswith("**") and a.endswith("**") and len(a) > 4:
        a = a[2:-2].strip()
    a = re.sub(r"[.\s]+$", "", a)   # trailing full stops / spaces
    return a or None


def parse_program(text: str) -> Optional[str]:
    """The LAST fenced code block; None when there is none."""
    blocks = _FENCE.findall(text or "")
    if not blocks:
        return None
    prog = blocks[-1]
    return prog if prog.strip() else None


# ----------------------------------------------------------------------------------------------
# Math: normalisation + sympy fallback
# ----------------------------------------------------------------------------------------------

_FUNCS = ("sqrt", "pi", "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan", "ln", "log", "exp",
          "infty", "div", "pm", "mp", "max", "min", "gcd", "lcm")


def _unbox(s: str) -> str:
    """Return the content of the LAST \\boxed{...} (brace balanced), or s unchanged."""
    idx = s.rfind("\\boxed")
    if idx < 0:
        return s
    j = s.find("{", idx)
    if j < 0:
        return s
    depth, k = 0, j
    while k < len(s):
        if s[k] == "{":
            depth += 1
        elif s[k] == "}":
            depth -= 1
            if depth == 0:
                return s[j + 1:k]
        k += 1
    return s[j + 1:]


def _unwrap(s: str, cmd: str) -> str:
    """\\cmd{inner} -> inner (brace balanced, repeated)."""
    pat = "\\" + cmd + "{"
    while True:
        i = s.find(pat)
        if i < 0:
            return s
        j = i + len(pat)
        depth, k = 1, j
        while k < len(s) and depth:
            depth += {"{": 1, "}": -1}.get(s[k], 0)
            k += 1
        s = s[:i] + s[j:k - 1] + s[k:]


def _frac_to_slash(s: str) -> str:
    """\\frac{a}{b} -> a/b (parenthesised when compound); \\frac12 -> 1/2."""
    out, i = [], 0
    while True:
        j = s.find("\\frac", i)
        if j < 0:
            out.append(s[i:]); break
        out.append(s[i:j])
        k = j + 5
        args = []
        for _ in range(2):
            if k < len(s) and s[k] == "{":
                depth, m = 1, k + 1
                while m < len(s) and depth:
                    depth += {"{": 1, "}": -1}.get(s[m], 0)
                    m += 1
                args.append(s[k + 1:m - 1]); k = m
            elif k < len(s):
                args.append(s[k]); k += 1
            else:
                args.append("")
        a, b = (_frac_to_slash(x) for x in args)
        wrap = lambda x: x if re.fullmatch(r"-?[\w.]+", x) else f"({x})"
        out.append(f"{wrap(a)}/{wrap(b)}")
        i = k
    return "".join(out)


def normalize_math(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"^\s*answer\s*[:：]\s*", "", s, flags=re.IGNORECASE)
    s = _unbox(s)
    s = s.replace("$$", "").replace("$", "").replace("\\(", "").replace("\\)", "").replace("\\[", "").replace("\\]", "")
    s = s.replace("\\\\", ";")                                   # matrix/row separator
    s = s.replace("\\displaystyle", "").replace("\\left", "").replace("\\right", "")
    for cmd in ("text", "textbf", "mathrm", "mathbf", "mathit", "operatorname"):
        s = _unwrap(s, cmd)
    s = re.sub(r"\\[,;!: ]|\\quad|\\qquad|~", "", s)
    s = s.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    s = re.sub(r"\^\s*(\{\\circ\}|\\circ)|°|\\degree", "", s)
    s = s.replace("\\%", "%")
    s = s.replace("\\cdot", "*").replace("\\times", "*")
    s = _frac_to_slash(s)
    s = re.sub(r"\\binom\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"binomial(\1,\2)", s)
    s = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"sqrt(\1)", s)
    s = re.sub(r"\\sqrt\s*(\w)", r"sqrt(\1)", s)
    s = re.sub(r"\\(" + "|".join(_FUNCS) + r")\b", r"\1", s)
    s = re.sub(r"\{(-?[\w.]+)\}", r"\1", s)          # braces around a single token
    s = re.sub(r"\s+", "", s)
    s = s.rstrip(".,;:")
    return s.casefold()


def _to_sympy(s: str):
    import sympy
    from sympy.parsing.sympy_parser import (parse_expr, standard_transformations, implicit_multiplication_application,
                                            convert_xor, factorial_notation)
    t = s.replace("\\", "").replace("{", "(").replace("}", ")")
    t = re.sub(r"\bln\b", "log", t).replace("infty", "oo").replace("inf", "oo")
    t = t.replace("%", "/100")
    if re.search(r"[^\w\s()+\-*/^.,!<>=]", t):
        raise ValueError("unsupported character")
    tr = standard_transformations + (implicit_multiplication_application, convert_xor, factorial_notation)
    local = {"e": sympy.E, "pi": sympy.pi}
    try:
        tree = parse_expr(t, transformations=tr, evaluate=False, local_dict=local)
    except Exception:  # noqa: BLE001 - the evaluating parse below reports (and did report) the failure
        tree = None
    if tree is not None and _est_bits(tree) > MAX_EVAL_BITS:
        raise ValueError("magnitude guard")
    return parse_expr(t, transformations=tr, evaluate=True, local_dict=local)


def _est_value(e) -> float:
    """Rough |value| of an unevaluated numeric tree (inf when it overflows a float; 1.0 for symbols/functions)."""
    import math
    try:
        if e.is_Number:
            return abs(float(e))
        if e.is_Pow:
            b, x = (_est_value(a) for a in e.args)
            return math.inf if b > 1 and x == math.inf else (b ** x if b else 0.0)
        if e.is_Add:
            return sum(_est_value(a) for a in e.args)
        if e.is_Mul:
            return math.prod(_est_value(a) for a in e.args)
        if e.func.__name__ == "factorial":
            return math.exp(math.lgamma(_est_value(e.args[0]) + 1))
        if e.func.__name__ == "binomial":
            return 2.0 ** _est_value(e.args[0])
    except (OverflowError, ValueError, ZeroDivisionError, TypeError):
        return math.inf
    return 1.0


def _est_bits(e) -> float:
    """Rough size in bits of the exact result of evaluating an unevaluated tree (inf when astronomically large)."""
    import math
    try:
        if e.is_Integer:
            return float(abs(int(e)).bit_length() or 1)
        if e.is_Rational:
            return float(abs(e.p).bit_length() + e.q.bit_length())
        if e.is_Pow:
            return _est_value(e.args[1]) * _est_bits(e.args[0])
        if e.func.__name__ == "factorial":
            n = _est_value(e.args[0])
            return n * math.log2(n) if n > 2 else 2.0
        if e.func.__name__ == "binomial":
            return _est_value(e.args[0])
        if e.args:
            return sum(_est_bits(a) for a in e.args)
    except (OverflowError, ValueError, ZeroDivisionError, TypeError):
        return math.inf
    return 64.0


def _num_equal(a, b) -> bool:
    import sympy
    d0 = a - b
    if d0.is_Rational:                       # exact arithmetic (integers, fractions, binomials, factorials): no tolerance
        return d0 == 0
    d = sympy.N(d0, 30)
    if d.has(sympy.I) or not d.is_number:
        return False
    try:
        scale = max(1.0, abs(float(sympy.N(a, 30))), abs(float(sympy.N(b, 30))))
        return abs(float(d)) <= NUM_TOL * scale
    except (TypeError, ValueError, OverflowError):
        return False


def _expr_equal(a, b) -> bool:
    import sympy
    fa, fb = a.free_symbols, b.free_symbols
    if not fa and not fb:
        return _num_equal(a, b)
    if fa != fb:
        return False
    syms = sorted(fa, key=str)
    probes = [[sympy.Rational(7 + 3 * i + 5 * j, 11 + i) for j in range(len(syms))] for i in range(3)]
    for pt in probes:
        sub = dict(zip(syms, pt))
        try:
            if not _num_equal(a.subs(sub), b.subs(sub)):
                return False
        except Exception:  # noqa: BLE001 - domain error at a probe point: not equivalent under this rule
            return False
    try:
        return sympy.expand(a - b) == 0 or sympy.simplify(a - b) == 0
    except Exception:  # noqa: BLE001
        return False


def _split_top(s: str) -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur)); cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def _bracket_shape(s: str) -> tuple[str, str]:
    if s and s[0] in "([{" and s[-1] in ")]}":
        return s[0], s[-1]
    return "", ""


def sympy_equivalent(a: str, b: str) -> Optional[str]:
    """Method name when the two normalised strings are equivalent under the sympy rule, else None.

    sympy memoises Integer/Rational/Pow construction and much else in 1,000-entry LRU caches whose entries can be
    arbitrarily large: every big integer a model answer produced (2^{50000000} is 6 MB) stayed resident, and the math
    precompute grew to 29 GB (Builder 5, 2026-10-26).  The caches only speed sympy up, so they are cleared after each
    comparison; the verdict is unchanged."""
    try:
        return _sympy_equivalent(a, b)
    finally:
        from sympy.core.cache import clear_cache
        clear_cache()


def _sympy_equivalent(a: str, b: str) -> Optional[str]:
    if len(a) > MAX_SYMPY_CHARS or len(b) > MAX_SYMPY_CHARS:
        return None
    sa, sb = _bracket_shape(a), _bracket_shape(b)
    if sa != sb:
        return None
    inner_a, inner_b = (a[1:-1], b[1:-1]) if sa[0] else (a, b)
    pa, pb = _split_top(inner_a), _split_top(inner_b)
    if len(pa) != len(pb):
        return None
    if len(pa) > 1:
        try:
            ea, eb = [_single(x) for x in pa], [_single(x) for x in pb]
        except Exception:  # noqa: BLE001
            return None
        if all(_pair_equal(x, y) for x, y in zip(ea, eb)):
            return "sympy_seq"
        if sa[0] == "" and len(pa) <= 5:                     # bare comma list: order-free (solution sets)
            for perm in itertools.permutations(range(len(pa))):
                if all(_pair_equal(ea[i], eb[perm[i]]) for i in range(len(pa))):
                    return "sympy_set"
        return None
    try:
        return "sympy" if _pair_equal(_single(a), _single(b)) else None
    except Exception:  # noqa: BLE001
        return None


def _single(s: str):
    if s.count("=") == 1:
        l, r = s.split("=")
        return ("eq", _to_sympy(l) - _to_sympy(r))
    return ("ex", _to_sympy(s))


def _pair_equal(x, y) -> bool:
    if x[0] != y[0]:
        return False
    if x[0] == "eq":
        return _expr_equal(x[1], y[1]) or _expr_equal(x[1], -y[1])
    return _expr_equal(x[1], y[1])


def grade_math(item: dict, text: str) -> Grade:
    pred = parse_final_answer(text)
    if pred is None:
        return Grade(0, 0, None, "parse_fail")
    a, k = normalize_math(pred), normalize_math(item["answer"])
    if a == k:
        return Grade(1, 1, pred, "exact")
    if item.get("key_type") == "integer":
        ai = a.replace(",", "").lstrip("+")
        if re.fullmatch(r"-?\d+", ai) and int(ai) == int(k):
            return Grade(1, 1, pred, "int")
    m = sympy_equivalent(a, k)
    return Grade(int(m is not None), 1, pred, m or "mismatch")


# ----------------------------------------------------------------------------------------------
# Factual QA: the pool author's normalisation rule
# ----------------------------------------------------------------------------------------------

_factual_mod = None


def _factual():
    global _factual_mod
    if _factual_mod is None:
        spec = importlib.util.spec_from_file_location("mb_factual_verify", FACTUAL_VERIFY_PY)
        _factual_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_factual_mod)
    return _factual_mod


_HEDGE = re.compile(r"\b(or|either)\b|\s/\s", re.IGNORECASE)
MAX_STRING_CHARS = 120


def grade_string(item: dict, text: str) -> Grade:
    v = _factual()
    pred = parse_final_answer(text)
    if pred is None:
        return Grade(0, 0, None, "parse_fail")
    key = item["answer"]
    nk = v.normalise(key)
    if _HEDGE.search(pred) and not _HEDGE.search(key):             # a key that itself contains "or" cannot be a hedge
        return Grade(0, 1, pred, "hedge")
    na = v.normalise(pred)
    if len(na) > max(MAX_STRING_CHARS, 2 * len(nk) + 20):
        return Grade(0, 1, pred, "too_long")
    if len(nk) >= 2 and re.search(r"(?<!\w)" + re.escape(nk) + r"(?!\w)", na):
        return Grade(1, 1, pred, "exact")
    atype = (item.get("strata") or {}).get("answer_type", "")
    if v.is_numeric(key, atype):
        dg = v.digits_form(key)
        nt = re.sub(r"\D", "", v._THOUSANDS.sub("", pred)) if False else v.normalise(v._THOUSANDS.sub("", pred))
        if len(dg) >= 2 and re.search(r"(?<!\d)" + re.escape(dg) + r"(?!\d)", nt):
            return Grade(1, 1, pred, "digits")
    for f in v.date_forms(key):
        if re.search(r"(?<!\w)" + re.escape(f) + r"(?!\w)", na):
            return Grade(1, 1, pred, "date")
    return Grade(0, 1, pred, "mismatch")


# ----------------------------------------------------------------------------------------------
# Code: the pool author's bwrap sandbox
# ----------------------------------------------------------------------------------------------

_sandbox_mod = None


def _sandbox():
    global _sandbox_mod
    if _sandbox_mod is None:
        spec = importlib.util.spec_from_file_location("mb_code_sandbox", SANDBOX_PY)
        _sandbox_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_sandbox_mod)
    return _sandbox_mod


def code_limits(item: dict) -> tuple[float, int]:
    ev = (item.get("verification") or {}).get("evidence") or {}
    timeout = float(ev.get("timeout_s") or max(2.0, 3.0 * float(item.get("time_limit_s") or 1.0)))
    mem = int(ev.get("memory_limit_bytes_sandbox") or max(1 << 30, 2 * int(float(item.get("memory_limit_mb") or 256) * 1e6)))
    return timeout, mem


def grade_code(item: dict, text: str) -> Grade:
    prog = parse_program(text)
    if prog is None:
        return Grade(0, 0, None, "parse_fail")
    sha = hashlib.sha256(prog.encode()).hexdigest()[:16]
    timeout, mem = code_limits(item)
    try:
        r = _sandbox().run_suite(prog, item["tests"], timeout, mem, "stop")
    except Exception as e:  # noqa: BLE001 - any host-side sandbox failure is incorrect, and logged
        return Grade(0, 1, sha, "sandbox_error", error=f"{type(e).__name__}: {str(e)[:200]}")
    if r.get("driver_error"):
        return Grade(0, 1, sha, "sandbox_error", error=str(r["driver_error"])[:300])
    ok = r["n_run"] == len(item["tests"]) and r["n_pass"] == len(item["tests"])
    return Grade(int(ok), 1, sha, "tests_pass" if ok else "tests_fail")


# ----------------------------------------------------------------------------------------------
# Dispatch
# ----------------------------------------------------------------------------------------------

def grade(item: dict, text: str) -> Grade:
    kt = key_type(item)
    if kt == "letter":
        pred = parse_answer(text, len(item["options"]))
        return Grade(int(pred == item["answer"]), int(pred is not None), pred, "letter" if pred is not None else "parse_fail")
    if kt in ("integer", "expression"):
        return grade_math(item, text)
    if kt == "string":
        return grade_string(item, text)
    if kt == "tests":
        return grade_code(item, text)
    raise ValueError(f"unknown key_type {kt}")


_sems: dict[int, asyncio.Semaphore] = {}


def _sem() -> asyncio.Semaphore:
    """One semaphore per event loop (the runner uses a fresh loop per command)."""
    loop = asyncio.get_running_loop()
    s = _sems.get(id(loop))
    if s is None:
        s = _sems[id(loop)] = asyncio.Semaphore(GRADE_WORKERS)
    return s


async def grade_async(item: dict, text: str) -> Grade:
    if key_type(item) == "tests":
        async with _sem():
            return await asyncio.to_thread(grade, item, text)
    return grade(item, text)
