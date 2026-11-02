"""Free-response graders (metabench.graders): exact-answer rule with sympy fallback, factual-QA string rule, code
test-execution in the pool author's bwrap sandbox, unchanged letter grader, fixed evaluee prompts.  Every test can fail:
each positive case has a mutated negative twin."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from metabench import graders as G  # noqa: E402
from metabench.pool import EVALUEE_INSTRUCTIONS, format_item_for_evaluee as mc_format  # noqa: E402


def _it(key, kt, **kw):
    d = {"id": "X0001", "category": "c", "question": "q?", "options": [], "answer": key, "key_type": kt}
    d.update(kw)
    return d


# ---------------------------------------------------------------- parsing

def test_parse_final_answer_takes_last_answer_line_and_strips_markup():
    assert G.parse_final_answer("blah\nAnswer: 12\nmore\n**Answer:** $\\frac{3}{4}$.") == "$\\frac{3}{4}$"
    assert G.parse_final_answer("answer : `42`") == "42"
    assert G.parse_final_answer("I think it is 42.") is None
    assert G.parse_final_answer("") is None


def test_parse_program_takes_last_fenced_block_only():
    txt = "first\n```python\nprint(1)\n```\nthen\n```py\nprint(2)\n```\n"
    assert G.parse_program(txt) == "print(2)\n"
    assert G.parse_program("no fences print(1)") is None
    assert G.parse_program("```python\n\n```") is None


# ---------------------------------------------------------------- math

@pytest.mark.parametrize("key,kt,resp,method", [
    ("180", "integer", "so the answer is\nAnswer: 180", "exact"),
    ("180", "integer", "Answer: 0180.", "int"),
    ("180", "integer", "Answer: $\\boxed{180}$", "exact"),
    ("180", "integer", "Answer: 1,80", "int"),            # thousands separator removed -> 180
    ("-7", "integer", "Answer: -7", "exact"),
    ("180", "integer", "Answer: 180.0", "sympy"),
    ("\\frac{7}{12}", "expression", "Answer: 7/12", "exact"),
    ("-\\frac{7}{12}", "expression", "Answer: \\boxed{-\\dfrac{7}{12}}", "exact"),
    ("\\frac19", "expression", "Answer: \\frac{1}{9}", "exact"),
    ("0.015", "expression", "Answer: \\frac{3}{200}", "sympy"),
    ("2024 \\sqrt{2} - 2003", "expression", "Answer: -2003+2024\\sqrt{2}", "sympy"),
    ("\\frac{1+\\sqrt{31}}{2}", "expression", "Answer: (1+\\sqrt{31})/2", "exact"),
    ("2^{100}", "expression", "Answer: 2^100", "exact"),
    ("49\\pi", "expression", "Answer: $49 \\pi$", "exact"),
    ("74^\\circ", "expression", "Answer: 74", "exact"),
    ("\\text{Monday}", "expression", "Answer: monday", "exact"),
    ("(7,21,35)", "expression", "Answer: (7, 21, 35)", "exact"),
    ("2 + \\sqrt{3}, -2 + \\sqrt{3}", "expression", "Answer: -2+\\sqrt{3}, 2+\\sqrt{3}", "sympy_set"),
    ("(-\\infty,4)", "expression", "Answer: (-\\infty, 4)", "exact"),
    ("y = x^2 + 2", "expression", "Answer: y - 2 = x^2", "sympy"),
    ("3(x-2)(x+1)", "expression", "Answer: 3x^2-3x-6", "sympy"),
    ("\\frac{2^{100}}{\\binom{100}{50}}-1", "expression", "Answer: 2^{100}/\\binom{100}{50} - 1", "sympy"),
    ("1/91", "expression", "Answer: \\frac{1}{91}", "exact"),
    ("\\begin{pmatrix} 1 \\\\ -2 \\\\ -1 \\end{pmatrix}", "expression", "Answer: \\begin{pmatrix}1\\\\-2\\\\-1\\end{pmatrix}", "exact"),
])
def test_math_positive_cases(key, kt, resp, method):
    g = G.grade(_it(key, kt), resp)
    assert (g.correct, g.parsed, g.method) == (1, 1, method), g


@pytest.mark.parametrize("key,kt,resp", [
    ("180", "integer", "Answer: 181"),
    ("180", "integer", "Answer: 18"),
    ("180", "integer", "The answer is 180"),            # no Answer line -> parse failure
    ("\\frac{7}{12}", "expression", "Answer: 7/13"),
    ("0.015", "expression", "Answer: 0.0150001"),
    ("(7,21,35)", "expression", "Answer: (21,7,35)"),   # ordered tuple
    ("(-\\infty,4)", "expression", "Answer: (-\\infty,4]"),
    ("y = x^2 + 2", "expression", "Answer: y = x^2 + 3"),
    ("3(x-2)(x+1)", "expression", "Answer: 3(x-2)(x-1)"),
    ("2 + \\sqrt{3}, -2 + \\sqrt{3}", "expression", "Answer: 2+\\sqrt{3}"),
    ("\\text{Monday}", "expression", "Answer: Tuesday"),
])
def test_math_negative_cases(key, kt, resp):
    g = G.grade(_it(key, kt), resp)
    assert g.correct == 0, g
    if "Answer" not in resp:
        assert g.parsed == 0 and g.method == "parse_fail"


def test_every_real_math_key_grades_itself_correct_and_a_mutation_incorrect():
    """Self-consistency on the real pool keys (item text only; no model): 'Answer: <key>' is correct for every item,
    and a perturbed key is not."""
    path = ROOT / "pools" / "math" / "pool.jsonl"
    if not path.exists():
        pytest.skip("math pool absent")
    bad, bad_mut = [], []
    for line in open(path):
        it = json.loads(line)
        g = G.grade(it, "work...\nAnswer: " + it["answer"])
        if g.correct != 1:
            bad.append((it["id"], it["answer"], g.method))
        mut = it["answer"] + "1" if it["key_type"] == "integer" else "(" + it["answer"] + ")+1"
        if G.grade(it, "Answer: " + mut).correct:
            bad_mut.append((it["id"], it["answer"]))
    assert not bad, bad[:20]
    assert not bad_mut, bad_mut[:20]


# ---------------------------------------------------------------- factual QA

def _f(key, atype="Other"):
    return _it(key, "string", strata={"answer_type": atype})


@pytest.mark.parametrize("key,atype,resp,method", [
    ("1886", "Date", "Answer: 1886", "exact"),
    ("1886", "Date", "Answer: It was founded in 1886.", "exact"),
    ("1984.", "Date", "Answer: 1984", "exact"),
    ("18 August 1987", "Date", "Answer: August 18, 1987", "date"),
    ("December 26, 1978", "Date", "Answer: 26 December 1978", "date"),
    (" 70,435 spectators", "Number", "Answer: 70435", "digits"),
    ("20 feet.", "Number", "Answer: 20 feet", "exact"),
    (" O'Reilly", "Person", "Answer: Bill O'Reilly", "exact"),
    ("Fleury-Mérogis Prison", "Place", "Answer: fleury merogis prison", "mismatch_or_exact"),
    ('"Painfully Employed"', "Other", "Answer: Painfully Employed", "exact"),
])
def test_factual_positive_cases(key, atype, resp, method):
    g = G.grade(_f(key, atype), resp)
    if method == "mismatch_or_exact":    # NFKC does not strip accents; the rule is literal (documented)
        assert g.parsed == 1
        return
    assert (g.correct, g.parsed, g.method) == (1, 1, method), g


@pytest.mark.parametrize("key,atype,resp,method", [
    ("1886", "Date", "Answer: 1887", "mismatch"),
    ("1886", "Date", "Answer: 18869", "mismatch"),                        # word boundary
    ("1886", "Date", "Answer: 1886 or 1887", "hedge"),
    ("1886", "Date", "Answer: either 1886 or 1887", "hedge"),
    ("1886", "Date", "It was 1886", "parse_fail"),
    (" 70,435 spectators", "Number", "Answer: 170435", "mismatch"),
    ("Marcelo Langieri", "Person", "Answer: Langieri", "mismatch"),         # whole key must appear
    ("1886", "Date", "Answer: " + "x " * 70 + "1886", "too_long"),
])
def test_factual_negative_cases(key, atype, resp, method):
    g = G.grade(_f(key, atype), resp)
    assert (g.correct, g.method) == (0, method), g


def test_every_real_factual_key_grades_itself_correct():
    path = ROOT / "pools" / "factual_qa" / "pool.jsonl"
    if not path.exists():
        pytest.skip("factual pool absent")
    bad = []
    for line in open(path):
        it = json.loads(line)
        g = G.grade(it, "Answer: " + it["answer"].strip())
        if g.correct != 1:
            bad.append((it["id"], it["answer"], g.method))
    assert not bad, bad[:20]


# ---------------------------------------------------------------- code (real sandbox)

def _code_item(tests, time_limit=1.0):
    return {"id": "C9999", "category": "c", "question": "Read two ints, print their sum.", "options": [], "answer": "tests",
            "key_type": "tests", "tests": tests, "reference_solution": "a,b=map(int,input().split());print(a+b)\n",
            "language": "python3", "time_limit_s": time_limit, "memory_limit_mb": 256.0,
            "verification": {"method": "sandbox", "verified": True, "evidence": {"timeout_s": max(2.0, 3 * time_limit), "memory_limit_bytes_sandbox": 1 << 30}}}


SUM_TESTS = [{"input": "1 2\n", "output": "3\n"}, {"input": "10 -4\n", "output": "6\n"}, {"input": "0 0\n", "output": "0\n"}]


@pytest.mark.skipif(not Path("/usr/bin/bwrap").exists(), reason="bwrap absent")
def test_code_grader_executes_in_sandbox_and_scores_failures_incorrect():
    it = _code_item(SUM_TESTS)
    good = "Here is my solution:\n```python\na,b=map(int,input().split())\nprint(a+b)\n```\n"
    assert G.grade(it, good).correct == 1 and G.grade(it, good).method == "tests_pass"
    wrong = "```python\na,b=map(int,input().split())\nprint(a-b)\n```"
    g = G.grade(it, wrong)
    assert (g.correct, g.parsed, g.method) == (0, 1, "tests_fail")
    partial = "```python\nprint(3)\n```"                       # passes test 1 only
    assert G.grade(it, partial).correct == 0
    crash = "```python\nraise SystemExit(3)\n```"
    assert G.grade(it, crash).correct == 0
    nofence = "a,b=map(int,input().split())\nprint(a+b)"
    g = G.grade(it, nofence)
    assert (g.correct, g.parsed, g.method) == (0, 0, "parse_fail")
    # float tolerance of the driver's token rule
    ft = _code_item([{"input": "\n", "output": "0.3333333\n"}])
    assert G.grade(ft, "```python\nprint(1/3)\n```").correct == 1
    assert G.grade(ft, "```python\nprint(0.3334)\n```").correct == 0


@pytest.mark.skipif(not Path("/usr/bin/bwrap").exists(), reason="bwrap absent")
def test_code_grader_time_limit_and_no_network_and_sandbox_error_logged(monkeypatch):
    it = _code_item(SUM_TESTS, time_limit=0.5)        # timeout 2 s
    loop = "```python\nwhile True: pass\n```"
    g = G.grade(it, loop)
    assert g.correct == 0 and g.method == "tests_fail"
    net = "```python\nimport socket\ns=socket.create_connection(('1.1.1.1',80),timeout=2)\nprint(3)\n```"
    assert G.grade(it, net).correct == 0
    # a host-side sandbox failure is incorrect and carried in error (logged), never an exception
    class Boom:
        @staticmethod
        def run_suite(*a, **k):
            raise OSError("bwrap missing")
    monkeypatch.setattr(G, "_sandbox", lambda: Boom)
    g = G.grade(it, "```python\nprint(3)\n```")
    assert (g.correct, g.parsed, g.method) == (0, 1, "sandbox_error") and "bwrap missing" in g.error
    monkeypatch.setattr(G, "_sandbox", lambda: type("D", (), {"run_suite": staticmethod(lambda *a, **k: {"results": [], "max_time": 0, "n_pass": 0, "n_run": 0, "driver_error": "driver exit 1"})}))
    g = G.grade(it, "```python\nprint(3)\n```")
    assert g.correct == 0 and g.method == "sandbox_error" and "driver exit 1" in g.error


@pytest.mark.skipif(not Path("/usr/bin/bwrap").exists(), reason="bwrap absent")
def test_real_code_items_reference_passes_and_wrong_program_fails():
    """Five seeded real items: the pool author's reference solution grades correct under the item's own limits; the
    print(0) program does not."""
    path = ROOT / "pools" / "code" / "pool.jsonl"
    if not path.exists():
        pytest.skip("code pool absent")
    import random
    rows = [json.loads(l) for l in open(path)]
    rng = random.Random(20261025)
    for it in rng.sample(rows, 5):
        t, m = G.code_limits(it)
        assert t == it["verification"]["evidence"]["timeout_s"] and m == it["verification"]["evidence"]["memory_limit_bytes_sandbox"]
        assert G.grade(it, "```python\n" + it["reference_solution"] + "\n```").correct == 1, it["id"]
        assert G.grade(it, "```python\nprint(0)\n```").correct == 0, it["id"]


def test_grade_async_runs_code_in_threads_per_loop():
    it = _code_item(SUM_TESTS)
    async def go():
        return await asyncio.gather(*(G.grade_async(it, "```python\na,b=map(int,input().split())\nprint(a+b)\n```") for _ in range(3)))
    if not Path("/usr/bin/bwrap").exists():
        pytest.skip("bwrap absent")
    r1 = asyncio.run(go()); r2 = asyncio.run(go())          # two loops, as the runner's commands
    assert all(g.correct == 1 for g in r1 + r2)


# ---------------------------------------------------------------- letter (unchanged) and prompts

def test_letter_grader_and_prompt_unchanged_from_pilot():
    it = {"id": "P1", "category": "c", "question": "Q?", "options": ["a", "b", "c", "d"], "answer": "C"}
    assert G.grade(it, "Answer: C").correct == 1 and G.grade(it, "Answer: B").correct == 0
    assert G.grade(it, "I do not know").parsed == 0
    assert G.evaluee_prompt(it) == EVALUEE_INSTRUCTIONS + "\n\n" + mc_format(it)


def test_prompts_are_fixed_per_key_type_and_name_the_format():
    assert "Answer: N" in G.evaluee_prompt(_it("5", "integer"))
    assert "Answer: X" in G.evaluee_prompt(_it("x", "expression")) and "LaTeX" in G.evaluee_prompt(_it("x", "expression"))
    assert "Answer: X" in G.evaluee_prompt(_f("k"))
    p = G.evaluee_prompt(_code_item(SUM_TESTS, 2.0))
    assert "```python" in p and "Time limit: 2.0 s" in p and "Memory limit: 256 MB" in p and "stdin" in p
    assert "options" not in G.evaluee_prompt(_it("5", "integer")).lower()
