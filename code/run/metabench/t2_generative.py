"""MetaBench Tier 2 (T2): generative design.

The designer WRITES new items against a construct brief.  Keys used for grading are never the designer's
own: math and code keys are derived by executing a reference solution and confirmed by an independent
(non-designer-family) solver; factual-QA keys are the cross-family panel majority that passes a citation
check and a 10% human spot audit.  Designer-proposed keys are stored as a provenance feature and for the
SILENCER-style wrong-label decomposition only.

Everything here runs offline: the panel scorer, the independent solver and the reference implementer are
injected callables so tests use fakes.  Sandboxed execution uses `python -I -c` inside `unshare -rn` (new
user + network namespace) when available, plus RLIMIT_* limits and an in-process prelude that disables
file writes, subprocesses and sockets.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, asdict
from fractions import Fraction
from typing import Any, Callable, Optional

# ----------------------------------------------------------------------------------------------
# Items
# ----------------------------------------------------------------------------------------------

CONSTRUCTS = ("math", "code", "factual")
STATUSES = ("unverified", "verified", "contested", "failed")


@dataclass
class T2Item:
    id: str
    construct: str                      # "math" | "code" | "factual"
    text: str                           # problem statement shown to evaluees
    designer_key: str                   # the designer's proposed answer (NEVER used for grading)
    designer_reference: dict = field(default_factory=dict)
    # math:    {"solution_code": str}  -> prints the answer on the last stdout line
    # code:    {"function_name": str, "impl": str, "tests": str}
    # factual: {"citation": str}
    verified_key: Optional[str] = None  # the key actually used for grading (set by a verifier)
    verification_status: str = "unverified"
    verification_detail: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)   # designer, session_id, round, created_at, revised_from, revision
    weight: float = 1.0
    format: str = "default"
    audit_sampled: bool = False

    def content_hash(self) -> str:
        return hashlib.sha256(json.dumps([self.construct, self.text, self.verified_key, self.format], sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)


# ----------------------------------------------------------------------------------------------
# Sandbox
# ----------------------------------------------------------------------------------------------

SANDBOX_PRELUDE = r'''
import builtins as _b, socket as _s, os as _os, io as _io, subprocess as _sp, shutil as _sh
_orig_open = _b.open
def _ro_open(file, mode='r', *a, **k):
    if any(c in str(mode) for c in 'wax+'):
        raise PermissionError('sandbox: file writes are disabled')
    return _orig_open(file, mode, *a, **k)
_b.open = _ro_open
_io.open = _ro_open
def _blocked(*a, **k):
    raise OSError('sandbox: this operation is disabled')
for _n in ('socket', 'create_connection', 'getaddrinfo', 'socketpair', 'create_server', 'fromfd'):
    if hasattr(_s, _n): setattr(_s, _n, _blocked)
for _n in ('system', 'popen', 'fork', 'forkpty', 'execv', 'execve', 'execvp', 'execvpe', 'execl', 'execlp', 'execle',
           'execlpe', 'spawnl', 'spawnle', 'spawnv', 'spawnve', 'remove', 'unlink', 'rename', 'replace', 'mkdir',
           'makedirs', 'rmdir', 'removedirs', 'truncate', 'ftruncate', 'symlink', 'link', 'chmod', 'chown', 'kill', 'killpg'):
    if hasattr(_os, _n): setattr(_os, _n, _blocked)
_os_open = _os.open
def _os_open_ro(path, flags, *a, **k):
    if flags & (_os.O_WRONLY | _os.O_RDWR | _os.O_CREAT | _os.O_APPEND | _os.O_TRUNC):
        raise PermissionError('sandbox: file writes are disabled')
    return _os_open(path, flags, *a, **k)
_os.open = _os_open_ro
_sp.Popen = _blocked; _sp.run = _blocked; _sp.call = _blocked; _sp.check_call = _blocked; _sp.check_output = _blocked
for _n in ('rmtree', 'move', 'copy', 'copy2', 'copyfile', 'copytree'):
    if hasattr(_sh, _n): setattr(_sh, _n, _blocked)
del _b, _s, _os, _io, _sp, _sh, _n
'''

_UNSHARE_OK: Optional[bool] = None


def unshare_available() -> bool:
    """True if `unshare -rn` (user + net namespace) works on this host; cached."""
    global _UNSHARE_OK
    if _UNSHARE_OK is None:
        if shutil.which("unshare") is None:
            _UNSHARE_OK = False
        else:
            try:
                p = subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=5)
                _UNSHARE_OK = p.returncode == 0
            except Exception:
                _UNSHARE_OK = False
    return _UNSHARE_OK


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    returncode: Optional[int]
    timed_out: bool
    wall_s: float
    network_isolation: str   # "unshare-netns+prelude" | "prelude-only"

    @property
    def ok(self) -> bool:
        return (not self.timed_out) and self.returncode == 0

    @property
    def last_line(self) -> str:
        lines = [l.strip() for l in self.stdout.splitlines() if l.strip()]
        return lines[-1] if lines else ""


def run_sandboxed(code: str, timeout_s: float = 10.0, mem_mb: int = 512) -> SandboxResult:
    """Execute untrusted Python with: isolated interpreter (-I), empty env, read-only temp cwd, RLIMITs
    (address space, CPU, file size 0 => no byte can be written), a prelude that disables writes/sockets/
    subprocesses, and a fresh network namespace when `unshare -rn` is available."""
    full = SANDBOX_PRELUDE + "\n" + code
    cpu_s = max(1, int(math.ceil(timeout_s)) + 1)

    def limits():
        try:
            resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 2 ** 20, mem_mb * 2 ** 20))
        except (ValueError, OSError):
            pass
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except (ValueError, OSError):
            pass

    with tempfile.TemporaryDirectory(prefix="mb_sbx_") as d:
        os.chmod(d, 0o555)
        cmd = [sys.executable, "-I", "-c", full]
        iso = "prelude-only"
        if unshare_available():
            cmd = ["unshare", "-rn", "--"] + cmd
            iso = "unshare-netns+prelude"
        t0 = time.time()
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                               cwd=d, preexec_fn=limits, stdin=subprocess.DEVNULL)
            return SandboxResult(p.stdout[-20000:], p.stderr[-20000:], p.returncode, False, time.time() - t0, iso)
        except subprocess.TimeoutExpired as e:
            out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            err = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
            return SandboxResult(out[-20000:], err[-20000:], None, True, time.time() - t0, iso)


# ----------------------------------------------------------------------------------------------
# Answer normalisation and equivalence (math / factual)
# ----------------------------------------------------------------------------------------------

_LATEX_FRAC = re.compile(r"\\(?:d?frac)\{([^{}]+)\}\{([^{}]+)\}")


def normalize_answer(s: str) -> str:
    s = (s or "").strip()
    s = s.replace("$", "").replace("\\,", "").replace("\\!", "").replace("\\left", "").replace("\\right", "")
    s = _LATEX_FRAC.sub(r"(\1)/(\2)", s)
    s = s.replace("\\boxed{", "").rstrip("}") if s.startswith("\\boxed{") else s
    s = re.sub(r"\s+", " ", s).strip().rstrip(".").strip()
    s = s.replace(",", "") if re.fullmatch(r"-?[\d,]+(\.\d+)?", s) else s   # 1,000 -> 1000
    return s


def _to_number(s: str) -> Optional[Fraction]:
    s = s.replace(" ", "")
    if re.fullmatch(r"\(?-?\d+\)?/\(?-?\d+\)?", s):
        s = s.replace("(", "").replace(")", "")
        n, d = s.split("/")
        if int(d) == 0:
            return None
        return Fraction(int(n), int(d))
    try:
        return Fraction(s)
    except (ValueError, ZeroDivisionError):
        pass
    try:
        return Fraction(float(s))
    except (ValueError, OverflowError):
        return None


def answers_equivalent(a: str, b: str, rel_tol: float = 1e-6) -> bool:
    """Numeric equivalence (exact rationals, or floats within rel_tol), sympy symbolic equivalence when
    sympy is importable, else normalised string equality."""
    na, nb = normalize_answer(a), normalize_answer(b)
    if na == nb:
        return True
    xa, xb = _to_number(na), _to_number(nb)
    if xa is not None and xb is not None:
        if xa == xb:
            return True
        return math.isclose(float(xa), float(xb), rel_tol=rel_tol, abs_tol=1e-9)
    try:  # optional symbolic check
        import sympy
        from sympy.parsing.sympy_parser import parse_expr
        ea, eb = parse_expr(na), parse_expr(nb)
        return bool(sympy.simplify(ea - eb) == 0)
    except Exception:
        return na.lower() == nb.lower()


def normalize_factual(s: str) -> str:
    s = normalize_answer(s).lower()
    s = re.sub(r"[^\w\s./-]", "", s)
    s = re.sub(r"\b(the|a|an)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ----------------------------------------------------------------------------------------------
# Verifiers
# ----------------------------------------------------------------------------------------------

def verify_math(item: T2Item, reference_solver_fn: Callable[[str], str], timeout_s: float = 10.0) -> T2Item:
    """Key = answer printed by executing the designer's reference solution, accepted only if an independent
    solver from a non-designer family agrees.  Designer_key is compared afterwards for the label channel."""
    code = item.designer_reference.get("solution_code", "")
    if not code.strip():
        item.verification_status, item.verification_detail = "failed", {"reason": "no reference solution code"}
        return item
    res = run_sandboxed(code, timeout_s=timeout_s)
    detail: dict[str, Any] = {"exec_ok": res.ok, "timed_out": res.timed_out, "stderr_tail": res.stderr[-400:], "isolation": res.network_isolation}
    if not res.ok or not res.last_line:
        item.verification_status, item.verification_detail = "failed", {**detail, "reason": "reference solution did not execute to an answer"}
        return item
    executed = res.last_line
    try:
        independent = reference_solver_fn(item.text)
    except Exception as e:
        independent = None
        detail["independent_error"] = str(e)[:300]
    detail.update({"executed_answer": executed, "independent_answer": independent,
                   "designer_key_matches_executed": answers_equivalent(item.designer_key, executed)})
    if independent is not None and answers_equivalent(executed, independent):
        item.verified_key, item.verification_status = executed, "verified"
    else:
        item.verified_key, item.verification_status = None, "contested"
        detail["reason"] = "independent solver disagrees with executed reference solution; needs human audit"
    detail["designer_key_wrong"] = (item.verified_key is not None) and not answers_equivalent(item.designer_key, item.verified_key)
    item.verification_detail = detail
    return item


def _code_program(impl: str, tests: str) -> str:
    return impl + "\n\n" + tests + "\n\nprint('__T2_PASS__')\n"


def verify_code(item: T2Item, reference_impl_fn: Callable[[T2Item], str], timeout_s: float = 10.0) -> T2Item:
    """Key = the designer's test suite, accepted only if (a) it passes on the designer's own implementation,
    (b) it fails on a stub (non-vacuous), and (c) it passes on an implementation written independently by a
    non-designer-family model.  (c) failing => contested."""
    ref = item.designer_reference
    fn, impl, tests = ref.get("function_name", ""), ref.get("impl", ""), ref.get("tests", "")
    if not (fn and impl.strip() and tests.strip()):
        item.verification_status, item.verification_detail = "failed", {"reason": "function_name, impl and tests are all required"}
        return item
    detail: dict[str, Any] = {}
    r_self = run_sandboxed(_code_program(impl, tests), timeout_s=timeout_s)
    detail["self_consistent"] = r_self.ok and "__T2_PASS__" in r_self.stdout
    detail["isolation"] = r_self.network_isolation
    if not detail["self_consistent"]:
        item.verification_status = "failed"
        detail["reason"] = "designer tests fail on designer implementation"
        detail["stderr_tail"] = r_self.stderr[-400:]
        item.verification_detail = detail
        return item
    stub = f"def {fn}(*args, **kwargs):\n    return None\n"
    r_stub = run_sandboxed(_code_program(stub, tests), timeout_s=timeout_s)
    detail["non_vacuous"] = not (r_stub.ok and "__T2_PASS__" in r_stub.stdout)
    if not detail["non_vacuous"]:
        item.verification_status = "failed"
        detail["reason"] = "tests pass on a stub that returns None (vacuous tests)"
        item.verification_detail = detail
        return item
    try:
        ref_impl = reference_impl_fn(item)
    except Exception as e:
        ref_impl = ""
        detail["reference_error"] = str(e)[:300]
    r_ref = run_sandboxed(_code_program(ref_impl, tests), timeout_s=timeout_s) if ref_impl.strip() else None
    detail["reference_passes"] = bool(r_ref and r_ref.ok and "__T2_PASS__" in r_ref.stdout)
    if r_ref is not None:
        detail["reference_stderr_tail"] = r_ref.stderr[-400:]
    if detail["reference_passes"]:
        item.verified_key = hashlib.sha256(tests.encode()).hexdigest()
        item.verification_status = "verified"
    else:
        item.verified_key, item.verification_status = None, "contested"
        detail["reason"] = "independent implementation fails the designer's tests; needs human audit"
    # designer_key for code items is the designer's claim about expected behaviour (free text); the label
    # channel for code is measured by `reference_passes` (designer tests vs independent implementation)
    detail["designer_key_wrong"] = (item.verification_status == "contested")
    item.verification_detail = detail
    return item


def verify_factual(item: T2Item, panel_answer_fns: list[tuple[str, Callable[[str], dict]]], audit_queue: list,
                   audit_rate: float = 0.10, min_agreement: float = 2 / 3,
                   citation_check_fn: Optional[Callable[[str, str], bool]] = None) -> T2Item:
    """Key = majority answer of >=3 answerers from >=2 non-designer families, with >= 2/3 agreement AND a
    non-empty citation on every agreeing answer (citation_check_fn may validate it further).  A deterministic
    10% of verified items is pushed to the human audit queue."""
    families = {f for f, _ in panel_answer_fns}
    if len(panel_answer_fns) < 3 or len(families) < 2:
        raise ValueError("verify_factual needs >=3 answerers from >=2 non-designer families")
    answers = []
    for fam, fn in panel_answer_fns:
        try:
            a = fn(item.text) or {}
        except Exception as e:
            a = {"answer": None, "citation": None, "error": str(e)[:200]}
        answers.append({"family": fam, "answer": a.get("answer"), "citation": a.get("citation"), "error": a.get("error")})
    groups: dict[str, list[int]] = {}
    for i, a in enumerate(answers):
        if a["answer"]:
            groups.setdefault(normalize_factual(a["answer"]), []).append(i)
    detail: dict[str, Any] = {"answers": answers}
    best = max(groups.items(), key=lambda kv: len(kv[1])) if groups else None
    n = len(answers)
    if best is None or len(best[1]) < math.ceil(min_agreement * n - 1e-9):
        item.verified_key, item.verification_status = None, "contested"
        detail["reason"] = "no >=2/3 majority among cross-family answerers"
        item.verification_detail = detail
        return item
    agreeing = [answers[i] for i in best[1]]
    cited = all((a["citation"] or "").strip() and (citation_check_fn is None or citation_check_fn(a["answer"], a["citation"])) for a in agreeing)
    detail["majority_size"] = len(agreeing)
    detail["citations_ok"] = cited
    if not cited:
        item.verified_key, item.verification_status = None, "contested"
        detail["reason"] = "majority answer lacks a passing citation"
        item.verification_detail = detail
        return item
    item.verified_key = agreeing[0]["answer"]
    item.verification_status = "verified"
    detail["designer_key_wrong"] = normalize_factual(item.designer_key) != normalize_factual(item.verified_key)
    # deterministic spot-audit sampling by item id
    if (int(hashlib.sha256(item.id.encode()).hexdigest(), 16) % 10_000) < int(audit_rate * 10_000):
        item.audit_sampled = True
        audit_queue.append({"item_id": item.id, "text": item.text, "verified_key": item.verified_key, "designer_key": item.designer_key,
                            "answers": answers, "form": AUDIT_FORM})
    item.verification_detail = detail
    return item


AUDIT_FORM = {
    "q1_answerable": "Is the question answerable with a single, dated, citable fact? (yes/no)",
    "q2_key_correct": "Is the verified key correct per the cited source(s)? (yes/no/unsure)",
    "q3_citation_supports": "Does at least one citation actually support the key? (yes/no)",
    "q4_ambiguity": "Rate ambiguity 1-5 (1 = unambiguous).",
    "q5_designer_key": "Is the designer's proposed key correct? (yes/no/unsure)",
    "auditor_blind_to": ["designer identity", "information arm", "identity arm"],
}


def wrong_label_channel(items: list[T2Item], designer_eval_answers: dict[str, str]) -> dict:
    """SILENCER-style decomposition input.  designer_eval_answers: item_id -> the designer-as-evaluee's own
    answer on that item.  Returns the fraction of designer keys that are wrong, and among those, the fraction
    where the designer's wrong key equals its own (wrong) answer as an evaluee: the 67-80% channel."""
    verified = [it for it in items if it.verification_status == "verified"]
    wrong = [it for it in verified if it.verification_detail.get("designer_key_wrong")]
    match = 0
    for it in wrong:
        own = designer_eval_answers.get(it.id)
        if own is not None and (answers_equivalent(own, it.designer_key) if it.construct == "math" else normalize_factual(own) == normalize_factual(it.designer_key)):
            match += 1
    return {"n_verified": len(verified), "n_designer_key_wrong": len(wrong),
            "frac_designer_key_wrong": (len(wrong) / len(verified)) if verified else None,
            "frac_wrong_key_matches_own_wrong_answer": (match / len(wrong)) if wrong else None}


# ----------------------------------------------------------------------------------------------
# Scoring cache
# ----------------------------------------------------------------------------------------------

class ScoreCache:
    """item content-hash -> {model_key: [0/1 per sample]}.  Unchanged items are never re-scored."""

    def __init__(self, path: Optional[str] = None):
        self.path = path
        self._d: dict[str, dict[str, list[int]]] = {}
        if path and os.path.exists(path):
            with open(path) as f:
                for line in f:
                    r = json.loads(line)
                    self._d[r["h"]] = r["scores"]

    def get(self, item: T2Item) -> Optional[dict[str, list[int]]]:
        return self._d.get(item.content_hash())

    def put(self, item: T2Item, scores: dict[str, list[int]]) -> None:
        h = item.content_hash()
        self._d[h] = scores
        if self.path:
            with open(self.path, "a") as f:
                f.write(json.dumps({"h": h, "item_id": item.id, "scores": scores}) + "\n")

    def missing(self, items: list[T2Item]) -> list[T2Item]:
        return [it for it in items if it.content_hash() not in self._d]


# ----------------------------------------------------------------------------------------------
# Interface tools (same JSON-schema style as T1)
# ----------------------------------------------------------------------------------------------

def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


T2_TOOLS = [
    {"name": "write_item", "description": "Add a new item to the draft benchmark. For math, give the problem text, your proposed final answer and a Python reference solution that prints the final answer on its last line. For code, give the task text, the function name, your implementation and a test block (plain asserts calling the function). For factual QA, give the question, your proposed answer and a citation. Items are verified before they count.",
     "input_schema": _schema({
         "text": {"type": "string", "description": "The item as it will be shown to a solver."},
         "proposed_answer": {"type": "string", "description": "Your proposed final answer (for math/factual) or a one-line description of expected behaviour (for code)."},
         "solution_code": {"type": "string", "description": "Math only: Python that prints the final answer on its last stdout line."},
         "function_name": {"type": "string", "description": "Code only."},
         "impl": {"type": "string", "description": "Code only: your reference implementation."},
         "tests": {"type": "string", "description": "Code only: assert-based tests calling the function."},
         "citation": {"type": "string", "description": "Factual only: a citable source (URL or bibliographic reference) with date."},
         "weight": {"type": "number", "description": "Optional weight, default 1."},
     }, ["text", "proposed_answer"])},
    {"name": "revise_item", "description": "Edit an existing draft item (any field). Revised items are re-verified and re-scored.",
     "input_schema": _schema({"item_id": {"type": "string"}, "text": {"type": "string"}, "proposed_answer": {"type": "string"},
                              "solution_code": {"type": "string"}, "function_name": {"type": "string"}, "impl": {"type": "string"},
                              "tests": {"type": "string"}, "citation": {"type": "string"}, "note": {"type": "string"}}, ["item_id"])},
    {"name": "delete_item", "description": "Remove an item from the draft.", "input_schema": _schema({"item_id": {"type": "string"}, "reason": {"type": "string"}}, ["item_id"])},
    {"name": "set_weight", "description": "Set an item's weight in the aggregate score (must be > 0).", "input_schema": _schema({"item_id": {"type": "string"}, "weight": {"type": "number"}}, ["item_id", "weight"])},
    {"name": "set_format", "description": "Set benchmark-level format: scoring rule and the instructions shown to solvers.",
     "input_schema": _schema({"scoring": {"type": "string", "enum": ["accuracy", "weighted"]}, "solver_instructions_variant": {"type": "string", "enum": ["A", "B"]},
                              "sections": {"type": "array", "items": {"type": "string"}}}, [])},
    {"name": "request_panel_scores", "description": "Run the current verified draft on the standard model panel on the eval cluster and return the results.", "input_schema": _schema({}, [])},
    {"name": "write_notes", "description": "Record design rationale or protocol notes (kept with the benchmark).", "input_schema": _schema({"text": {"type": "string"}}, ["text"])},
    {"name": "draft_status", "description": "Show the current draft: items, verification status, weights, format.", "input_schema": _schema({}, [])},
    {"name": "end_round", "description": "Finish the current design round.", "input_schema": _schema({"summary": {"type": "string"}}, [])},
    {"name": "submit", "description": "Submit the final benchmark. Only accepted when the draft has exactly the required number of verified items.", "input_schema": _schema({"final_notes": {"type": "string"}}, [])},
]

# Validity rules (pre-registered; see docs/T2_SPEC_AND_RUNPLAN.md)
T2_RULES = {
    "target_n": 60,                     # final benchmark size (verified items)
    "max_items_written_per_round": 30,  # write_item + revise_item calls per round
    "max_score_requests_per_round": 2,
    "max_rounds": 5,                    # K
    "max_text_chars": 4000,
    "min_text_chars": 20,
    "near_duplicate_jaccard": 0.8,      # token-set Jaccard above this => duplicate of an existing draft/pool item
}


def _tokset(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def jaccard(a: str, b: str) -> float:
    A, B = _tokset(a), _tokset(b)
    return len(A & B) / len(A | B) if (A | B) else 0.0


class T2Interface:
    """In-memory T2 design interface.  Injectables:
       verify_fn(item) -> item (runs the construct's verifier);
       score_fn(items) -> {model_key: {item_id: [0/1,...]}} (live panel scoring, K samples);
       view_fn(scores_by_model, draft_items, state) -> str (the information arm's scores view).
    """

    def __init__(self, session_id: str, construct: str, verify_fn: Callable[[T2Item], T2Item],
                 score_fn: Callable[[list[T2Item]], dict[str, dict[str, list[int]]]],
                 view_fn: Callable[[dict, list[T2Item], dict], str], designer: str = "", rules: Optional[dict] = None,
                 pool_texts: Optional[list[str]] = None, cache: Optional[ScoreCache] = None):
        assert construct in CONSTRUCTS
        self.session_id, self.construct, self.designer = session_id, construct, designer
        self.verify_fn, self.score_fn, self.view_fn = verify_fn, score_fn, view_fn
        self.rules = {**T2_RULES, **(rules or {})}
        self.pool_texts = pool_texts or []
        self.cache = cache or ScoreCache()
        self.items: dict[str, T2Item] = {}
        self.format = {"scoring": "accuracy", "solver_instructions_variant": "A", "sections": []}
        self.notes: list[dict] = []
        self.round = 1
        self.round_writes = 0
        self.round_score_requests = 0
        self.score_views: list[dict] = []
        self.actions: list[dict] = []
        self.submitted: Optional[dict] = None
        self._n = 0

    # -- logging ---------------------------------------------------------------------------------
    def _log(self, tool: str, args: dict, result: str, tokens: Optional[dict] = None) -> str:
        self.actions.append({"session_id": self.session_id, "round": self.round, "t": time.time(), "tool": tool, "args": args,
                             "result_summary": result[:500], "tokens": tokens})
        return result

    def set_last_tokens(self, tokens: dict) -> None:
        if self.actions:
            self.actions[-1]["tokens"] = tokens

    # -- helpers --------------------------------------------------------------------------------
    def verified_items(self) -> list[T2Item]:
        return [it for it in self.items.values() if it.verification_status == "verified"]

    def _duplicate_of(self, text: str, exclude: Optional[str] = None) -> Optional[str]:
        thr = self.rules["near_duplicate_jaccard"]
        for it in self.items.values():
            if it.id != exclude and jaccard(text, it.text) >= thr:
                return it.id
        for i, pt in enumerate(self.pool_texts):
            if jaccard(text, pt) >= thr:
                return f"pool:{i}"
        return None

    def _build_reference(self, a: dict, old: Optional[dict] = None) -> dict:
        ref = dict(old or {})
        if self.construct == "math":
            if "solution_code" in a: ref["solution_code"] = a["solution_code"]
        elif self.construct == "code":
            for k in ("function_name", "impl", "tests"):
                if k in a: ref[k] = a[k]
        else:
            if "citation" in a: ref["citation"] = a["citation"]
        return ref

    def _status_text(self) -> str:
        counts = {s: 0 for s in STATUSES}
        for it in self.items.values():
            counts[it.verification_status] += 1
        rows = [f"{it.id} [{it.verification_status}] w={it.weight:g} :: {it.text[:90].replace(chr(10), ' ')}" for it in self.items.values()]
        return (f"Draft: {len(self.items)} items ({counts}); target {self.rules['target_n']} verified. Format: {json.dumps(self.format)}.\n"
                + "\n".join(rows))

    # -- dispatch -------------------------------------------------------------------------------
    def handle_tool(self, name: str, args: dict) -> str:
        if self.submitted is not None:
            return self._log(name, args, "ERROR: benchmark already submitted")
        h = getattr(self, f"_t_{name}", None)
        if h is None:
            return self._log(name, args, f"ERROR: unknown tool {name}")
        try:
            return self._log(name, args, h(args))
        except Exception as e:  # never crash the session on a designer error
            return self._log(name, args, f"ERROR: {type(e).__name__}: {str(e)[:300]}")

    def _t_write_item(self, a: dict) -> str:
        if self.round_writes >= self.rules["max_items_written_per_round"]:
            return f"ERROR: per-round limit of {self.rules['max_items_written_per_round']} write/revise calls reached; call end_round."
        text = (a.get("text") or "").strip()
        if not (self.rules["min_text_chars"] <= len(text) <= self.rules["max_text_chars"]):
            return f"ERROR: item text must be {self.rules['min_text_chars']}-{self.rules['max_text_chars']} characters."
        dup = self._duplicate_of(text)
        if dup:
            return f"ERROR: near-duplicate of existing item {dup}; write a distinct item."
        w = float(a.get("weight", 1.0))
        if w <= 0:
            return "ERROR: weight must be > 0."
        self._n += 1
        iid = f"T2-{self.session_id}-{self._n:03d}"
        it = T2Item(id=iid, construct=self.construct, text=text, designer_key=str(a.get("proposed_answer", "")),
                    designer_reference=self._build_reference(a), weight=w,
                    provenance={"designer": self.designer, "session_id": self.session_id, "round": self.round, "created_at": time.time(), "revision": 0})
        self.round_writes += 1
        it = self.verify_fn(it)
        self.items[iid] = it
        return f"{iid}: {it.verification_status}" + (f" ({it.verification_detail.get('reason')})" if it.verification_status != "verified" else "") \
               + f". Verified items: {len(self.verified_items())}/{self.rules['target_n']}."

    def _t_revise_item(self, a: dict) -> str:
        it = self.items.get(a.get("item_id", ""))
        if it is None:
            return "ERROR: no such item."
        if self.round_writes >= self.rules["max_items_written_per_round"]:
            return "ERROR: per-round write/revise limit reached; call end_round."
        if "text" in a:
            text = a["text"].strip()
            if not (self.rules["min_text_chars"] <= len(text) <= self.rules["max_text_chars"]):
                return "ERROR: item text length out of range."
            dup = self._duplicate_of(text, exclude=it.id)
            if dup:
                return f"ERROR: near-duplicate of {dup}."
            it.text = text
        if "proposed_answer" in a:
            it.designer_key = str(a["proposed_answer"])
        it.designer_reference = self._build_reference(a, it.designer_reference)
        it.verified_key, it.verification_status, it.verification_detail = None, "unverified", {}
        it.provenance = {**it.provenance, "revised_from": it.id, "revision": it.provenance.get("revision", 0) + 1, "revised_round": self.round,
                         "note": a.get("note", "")}
        self.round_writes += 1
        it = self.verify_fn(it)
        self.items[it.id] = it
        return f"{it.id} revised: {it.verification_status}. Verified items: {len(self.verified_items())}/{self.rules['target_n']}."

    def _t_delete_item(self, a: dict) -> str:
        if a.get("item_id") not in self.items:
            return "ERROR: no such item."
        it = self.items.pop(a["item_id"])
        it.provenance["deleted_round"] = self.round
        self.notes.append({"round": self.round, "deleted": it.to_dict(), "reason": a.get("reason", "")})
        return f"{a['item_id']} deleted. Verified items: {len(self.verified_items())}/{self.rules['target_n']}."

    def _t_set_weight(self, a: dict) -> str:
        it = self.items.get(a.get("item_id", ""))
        if it is None:
            return "ERROR: no such item."
        if float(a["weight"]) <= 0:
            return "ERROR: weight must be > 0."
        it.weight = float(a["weight"])
        return f"{it.id} weight={it.weight:g}"

    def _t_set_format(self, a: dict) -> str:
        for k in ("scoring", "solver_instructions_variant", "sections"):
            if k in a:
                self.format[k] = a[k]
        for it in self.items.values():
            it.format = self.format["solver_instructions_variant"]
        return f"Format: {json.dumps(self.format)}"

    def _t_request_panel_scores(self, a: dict) -> str:
        if self.round_score_requests >= self.rules["max_score_requests_per_round"]:
            return f"ERROR: panel scoring limit ({self.rules['max_score_requests_per_round']} per round) reached."
        items = self.verified_items()
        if not items:
            return "No verified items in the draft yet; nothing to score."
        self.round_score_requests += 1
        todo = self.cache.missing(items)
        if todo:
            fresh = self.score_fn(todo)
            by_item: dict[str, dict[str, list[int]]] = {}
            for mk, per_item in fresh.items():
                for iid, samples in per_item.items():
                    by_item.setdefault(iid, {})[mk] = list(samples)
            for it in todo:
                self.cache.put(it, by_item.get(it.id, {}))
        scores: dict[str, dict[str, list[int]]] = {}
        for it in items:
            for mk, samples in (self.cache.get(it) or {}).items():
                scores.setdefault(mk, {})[it.id] = samples
        state = {"round": self.round, "n_items": len(items), "n_scored_fresh": len(todo), "format": dict(self.format),
                 "weights": {it.id: it.weight for it in items}}
        view = self.view_fn(scores, items, state)
        self.score_views.append({"round": self.round, "t": time.time(), "view": view, "n_items": len(items)})
        return view

    def _t_write_notes(self, a: dict) -> str:
        self.notes.append({"round": self.round, "t": time.time(), "text": a.get("text", "")})
        return "Noted."

    def _t_draft_status(self, a: dict) -> str:
        return self._status_text()

    def _t_end_round(self, a: dict) -> str:
        if self.round >= self.rules["max_rounds"]:
            return f"This was the final round ({self.round}/{self.rules['max_rounds']}). Call submit."
        self.notes.append({"round": self.round, "end_summary": a.get("summary", "")})
        self.round += 1
        self.round_writes = 0
        self.round_score_requests = 0
        return f"Round {self.round - 1} closed. Starting round {self.round}/{self.rules['max_rounds']}."

    def _t_submit(self, a: dict) -> str:
        n_ok = len(self.verified_items())
        if n_ok != self.rules["target_n"]:
            return (f"ERROR: submission requires exactly {self.rules['target_n']} verified items; draft has {n_ok} verified "
                    f"({len(self.items)} total). Fix contested/failed items or add verified ones.")
        self.submitted = {"session_id": self.session_id, "construct": self.construct, "designer": self.designer, "t": time.time(),
                          "format": dict(self.format), "final_notes": a.get("final_notes", ""),
                          "items": [it.to_dict() for it in self.verified_items()], "notes": self.notes}
        return f"Submitted: {n_ok} verified items."

    # -- export ---------------------------------------------------------------------------------
    def export(self) -> dict:
        return {"session_id": self.session_id, "construct": self.construct, "designer": self.designer, "submitted": self.submitted,
                "all_items": [it.to_dict() for it in self.items.values()], "actions": self.actions, "score_views": self.score_views,
                "notes": self.notes, "rules": self.rules}


# ----------------------------------------------------------------------------------------------
# Cost model (used by the run plan; numbers are estimates, not measurements)
# ----------------------------------------------------------------------------------------------

def live_scoring_calls(n_items: int, n_panel: int = 14, k: int = 5) -> int:
    return n_items * n_panel * k


def session_scoring_calls(changed_per_round: list[int], n_panel: int = 14, k: int = 5) -> int:
    """Panel calls for one session with content-hash caching: each item is scored once per distinct content
    (new or revised), regardless of how many scores requests are made.  changed_per_round[r] = number of
    items written or revised in round r."""
    return sum(live_scoring_calls(c, n_panel, k) for c in changed_per_round)
