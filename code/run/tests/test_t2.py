"""Offline tests for the T2 generative tier: sandbox, verifiers, cache, interface validity rules."""
import os
import sys
import unittest

sys.path.insert(0, "/path/to/metabench/run")
from metabench.t2_generative import (T2Item, run_sandboxed, verify_math, verify_code, verify_factual, answers_equivalent,
                                     ScoreCache, T2Interface, T2_TOOLS, T2_RULES, wrong_label_channel)


class SandboxTests(unittest.TestCase):
    def test_runs_and_returns_last_line(self):
        r = run_sandboxed("print('a')\nprint(6*7)")
        self.assertTrue(r.ok)
        self.assertEqual(r.last_line, "42")

    def test_file_write_blocked(self):
        path = "/tmp/mb_t2_sandbox_probe.txt"
        if os.path.exists(path):
            os.remove(path)
        r = run_sandboxed(f"open('{path}','w').write('x')\nprint('WROTE')")
        self.assertFalse(r.ok and "WROTE" in r.stdout, "sandbox allowed a file write")
        self.assertFalse(os.path.exists(path) and os.path.getsize(path) > 0, "file appeared with content")

    def test_os_open_write_blocked(self):
        path = "/tmp/mb_t2_sandbox_probe2.txt"
        r = run_sandboxed(f"import os\nfd=os.open('{path}', os.O_WRONLY|os.O_CREAT)\nos.write(fd,b'x')\nprint('WROTE')")
        self.assertFalse(r.ok and "WROTE" in r.stdout)
        self.assertFalse(os.path.exists(path) and os.path.getsize(path) > 0)

    def test_network_blocked(self):
        r = run_sandboxed("import socket\ns=socket.socket()\ns.settimeout(3)\ns.connect(('1.1.1.1',80))\nprint('CONNECTED')", timeout_s=8)
        self.assertFalse(r.ok and "CONNECTED" in r.stdout, "sandbox allowed a network connection")

    def test_subprocess_blocked(self):
        r = run_sandboxed("import subprocess\nprint(subprocess.run(['ls'],capture_output=True).returncode)\nprint('SPAWNED')")
        self.assertFalse(r.ok and "SPAWNED" in r.stdout)

    def test_infinite_loop_killed(self):
        r = run_sandboxed("while True:\n    pass", timeout_s=2)
        self.assertTrue(r.timed_out or (r.returncode not in (0, None)))
        self.assertLess(r.wall_s, 10)


class EquivalenceTests(unittest.TestCase):
    def test_half(self):
        self.assertTrue(answers_equivalent("1/2", "0.5"))
        self.assertTrue(answers_equivalent("\\frac{1}{2}", "0.5"))
        self.assertTrue(answers_equivalent("1,000", "1000"))
        self.assertFalse(answers_equivalent("1/2", "0.51"))
        self.assertFalse(answers_equivalent("12", "13"))


class MathVerifierTests(unittest.TestCase):
    def _item(self, key, code):
        return T2Item(id="m1", construct="math", text="What is 7 * 6?", designer_key=key, designer_reference={"solution_code": code})

    def test_verified_when_independent_agrees(self):
        it = verify_math(self._item("42", "print(7*6)"), lambda text: "42")
        self.assertEqual(it.verification_status, "verified")
        self.assertEqual(it.verified_key, "42")
        self.assertFalse(it.verification_detail["designer_key_wrong"])

    def test_contested_when_independent_disagrees(self):
        it = verify_math(self._item("42", "print(7*6)"), lambda text: "41")
        self.assertEqual(it.verification_status, "contested")
        self.assertIsNone(it.verified_key)

    def test_designer_key_wrong_is_recorded_not_used(self):
        it = verify_math(self._item("43", "print(7*6)"), lambda text: "42")
        self.assertEqual(it.verification_status, "verified")
        self.assertEqual(it.verified_key, "42")          # key comes from execution, not the designer
        self.assertTrue(it.verification_detail["designer_key_wrong"])

    def test_failed_when_solution_crashes(self):
        it = verify_math(self._item("42", "raise ValueError('x')"), lambda text: "42")
        self.assertEqual(it.verification_status, "failed")


class CodeVerifierTests(unittest.TestCase):
    IMPL = "def add(a, b):\n    return a + b\n"
    GOOD_TESTS = "assert add(1, 2) == 3\nassert add(-1, 1) == 0\nassert add(0.5, 0.25) == 0.75\n"
    WRONG_TESTS = "assert add(1, 2) == 4\n"            # wrong key
    WRONG_IMPL = "def add(a, b):\n    return a + b + 1\n"  # designer impl consistent with its wrong tests

    def _item(self, impl, tests):
        return T2Item(id="c1", construct="code", text="Write add(a, b) returning the sum.", designer_key="returns a+b",
                      designer_reference={"function_name": "add", "impl": impl, "tests": tests})

    def test_correct_item_verified(self):
        it = verify_code(self._item(self.IMPL, self.GOOD_TESTS), lambda item: "def add(a, b):\n    return b + a\n")
        self.assertEqual(it.verification_status, "verified", it.verification_detail)
        self.assertIsNotNone(it.verified_key)

    def test_wrong_key_rejected(self):
        # designer's impl and tests agree with each other but are wrong; independent impl exposes it
        it = verify_code(self._item(self.WRONG_IMPL, self.WRONG_TESTS), lambda item: "def add(a, b):\n    return a + b\n")
        self.assertEqual(it.verification_status, "contested")
        self.assertIsNone(it.verified_key)
        self.assertTrue(it.verification_detail["designer_key_wrong"])

    def test_inconsistent_designer_item_failed(self):
        it = verify_code(self._item(self.IMPL, self.WRONG_TESTS), lambda item: self.IMPL)
        self.assertEqual(it.verification_status, "failed")

    def test_vacuous_tests_failed(self):
        it = verify_code(self._item(self.IMPL, "x = add(1, 2)\n"), lambda item: self.IMPL)
        self.assertEqual(it.verification_status, "failed")
        self.assertIn("vacuous", it.verification_detail["reason"])


class FactualVerifierTests(unittest.TestCase):
    def _panel(self, answers):
        return [(fam, (lambda a, c: (lambda text: {"answer": a, "citation": c}))(a, c)) for fam, a, c in answers]

    def test_majority_with_citations_verified(self):
        q = []
        it = T2Item(id="f1", construct="factual", text="In what year did X happen?", designer_key="1969")
        it = verify_factual(it, self._panel([("gemini", "1969", "u1"), ("deepseek", "1969", "u2"), ("llama", "1970", "u3")]), q)
        self.assertEqual(it.verification_status, "verified")
        self.assertEqual(it.verified_key, "1969")

    def test_no_majority_contested(self):
        it = T2Item(id="f2", construct="factual", text="Q?", designer_key="a")
        it = verify_factual(it, self._panel([("gemini", "a", "u"), ("deepseek", "b", "u"), ("llama", "c", "u")]), [])
        self.assertEqual(it.verification_status, "contested")

    def test_missing_citation_contested(self):
        it = T2Item(id="f3", construct="factual", text="Q?", designer_key="a")
        it = verify_factual(it, self._panel([("gemini", "a", ""), ("deepseek", "a", "u"), ("llama", "a", "u")]), [])
        self.assertEqual(it.verification_status, "contested")

    def test_single_family_rejected(self):
        it = T2Item(id="f4", construct="factual", text="Q?", designer_key="a")
        with self.assertRaises(ValueError):
            verify_factual(it, self._panel([("gemini", "a", "u"), ("gemini", "a", "u"), ("gemini", "a", "u")]), [])

    def test_audit_sampling_is_deterministic_and_about_10pct(self):
        q = []
        n = 400
        for i in range(n):
            it = T2Item(id=f"fa{i}", construct="factual", text=f"Q{i}?", designer_key="a")
            verify_factual(it, self._panel([("gemini", "a", "u"), ("deepseek", "a", "u"), ("llama", "a", "u")]), q)
        self.assertTrue(20 <= len(q) <= 70, len(q))
        q2 = []
        for i in range(n):
            it = T2Item(id=f"fa{i}", construct="factual", text=f"Q{i}?", designer_key="a")
            verify_factual(it, self._panel([("gemini", "a", "u"), ("deepseek", "a", "u"), ("llama", "a", "u")]), q2)
        self.assertEqual([r["item_id"] for r in q], [r["item_id"] for r in q2])


class WrongLabelChannelTests(unittest.TestCase):
    def test_decomposition(self):
        items = []
        for i, (dk, vk) in enumerate([("42", "42"), ("41", "42"), ("40", "42"), ("5", "5")]):
            it = T2Item(id=f"w{i}", construct="math", text="t", designer_key=dk, verified_key=vk, verification_status="verified",
                        verification_detail={"designer_key_wrong": dk != vk})
            items.append(it)
        out = wrong_label_channel(items, {"w1": "41", "w2": "39"})
        self.assertEqual(out["n_designer_key_wrong"], 2)
        self.assertAlmostEqual(out["frac_designer_key_wrong"], 0.5)
        self.assertAlmostEqual(out["frac_wrong_key_matches_own_wrong_answer"], 0.5)


def fake_verify(it: T2Item) -> T2Item:
    # verified unless the designer's proposed answer is literally "BAD"
    if it.designer_key == "BAD":
        it.verification_status, it.verified_key = "contested", None
        it.verification_detail = {"reason": "fake contested"}
    else:
        it.verification_status, it.verified_key = "verified", it.designer_key
        it.verification_detail = {"designer_key_wrong": False}
    return it


class FakePanel:
    def __init__(self):
        self.calls = 0
        self.scored_ids = []

    def __call__(self, items):
        self.calls += 1
        self.scored_ids.extend(it.id for it in items)
        return {m: {it.id: [1, 0, 1] for it in items} for m in ("A", "B", "C")}


def view_fn(scores, items, state):
    return "VIEW " + " ".join(f"{m}:{sum(sum(v) for v in d.values())}" for m, d in sorted(scores.items())) + f" fresh={state['n_scored_fresh']}"


class InterfaceTests(unittest.TestCase):
    def _iface(self, **rules):
        self.panel = FakePanel()
        return T2Interface("S1", "math", fake_verify, self.panel, view_fn, designer="d", rules={"target_n": 3, **rules})

    def test_tools_schema_shape(self):
        names = {t["name"] for t in T2_TOOLS}
        self.assertEqual(names, {"write_item", "revise_item", "delete_item", "set_weight", "set_format", "request_panel_scores",
                                 "write_notes", "draft_status", "end_round", "submit"})
        for t in T2_TOOLS:
            self.assertFalse(t["input_schema"]["additionalProperties"])
            self.assertIn("required", t["input_schema"])

    def test_submit_requires_exact_verified_count(self):
        f = self._iface()
        f.handle_tool("write_item", {"text": "What is one plus one, in words?", "proposed_answer": "two"})
        f.handle_tool("write_item", {"text": "What is two plus two, in words?", "proposed_answer": "four"})
        r = f.handle_tool("submit", {})
        self.assertTrue(r.startswith("ERROR"))
        f.handle_tool("write_item", {"text": "What is three plus three, in words?", "proposed_answer": "BAD"})  # contested: does not count
        self.assertTrue(f.handle_tool("submit", {}).startswith("ERROR"))
        f.handle_tool("write_item", {"text": "What is four plus four, in words?", "proposed_answer": "eight"})
        r = f.handle_tool("submit", {"final_notes": "done"})
        self.assertTrue(r.startswith("Submitted"), r)
        self.assertEqual(len(f.submitted["items"]), 3)
        self.assertTrue(f.handle_tool("write_item", {"text": "late item text here", "proposed_answer": "x"}).startswith("ERROR"))

    def test_duplicates_rejected(self):
        f = self._iface()
        f.handle_tool("write_item", {"text": "Compute the sum of the first ten positive integers.", "proposed_answer": "55"})
        r = f.handle_tool("write_item", {"text": "Compute the sum of the first ten positive integers!", "proposed_answer": "55"})
        self.assertIn("near-duplicate", r)

    def test_pool_duplicate_rejected(self):
        panel = FakePanel()
        f = T2Interface("S2", "math", fake_verify, panel, view_fn, rules={"target_n": 1},
                        pool_texts=["How many primes are there below twenty?"])
        r = f.handle_tool("write_item", {"text": "How many primes are there below twenty", "proposed_answer": "8"})
        self.assertIn("near-duplicate", r)

    def test_per_round_write_and_score_limits(self):
        f = self._iface(max_items_written_per_round=2, max_score_requests_per_round=1)
        f.handle_tool("write_item", {"text": "Item number one about something", "proposed_answer": "1"})
        f.handle_tool("write_item", {"text": "Item number two about something else", "proposed_answer": "2"})
        r = f.handle_tool("write_item", {"text": "Item number three about another thing", "proposed_answer": "3"})
        self.assertTrue(r.startswith("ERROR"))
        self.assertTrue(f.handle_tool("request_panel_scores", {}).startswith("VIEW"))
        self.assertTrue(f.handle_tool("request_panel_scores", {}).startswith("ERROR"))
        self.assertIn("round 2", f.handle_tool("end_round", {}))
        self.assertFalse(f.handle_tool("write_item", {"text": "Item number three about another thing", "proposed_answer": "3"}).startswith("ERROR"))

    def test_scoring_cache_only_scores_changed_items(self):
        f = self._iface(max_score_requests_per_round=5)
        f.handle_tool("write_item", {"text": "Alpha item text for scoring", "proposed_answer": "1"})
        f.handle_tool("write_item", {"text": "Beta item text for scoring", "proposed_answer": "2"})
        f.handle_tool("request_panel_scores", {})
        self.assertEqual(sorted(self.panel.scored_ids), sorted(list(f.items)))
        f.handle_tool("request_panel_scores", {})               # nothing changed -> no new calls
        self.assertEqual(self.panel.calls, 1)
        f.handle_tool("revise_item", {"item_id": list(f.items)[0], "text": "Alpha item text for scoring, revised"})
        f.handle_tool("request_panel_scores", {})
        self.assertEqual(self.panel.calls, 2)
        self.assertEqual(len(self.panel.scored_ids), 3)

    def test_weights_and_action_log(self):
        f = self._iface()
        f.handle_tool("write_item", {"text": "Gamma item text for weights", "proposed_answer": "1"})
        iid = list(f.items)[0]
        self.assertTrue(f.handle_tool("set_weight", {"item_id": iid, "weight": 0}).startswith("ERROR"))
        self.assertIn("weight=2", f.handle_tool("set_weight", {"item_id": iid, "weight": 2}))
        for a in f.actions:
            self.assertEqual(set(a), {"session_id", "round", "t", "tool", "args", "result_summary", "tokens"})

    def test_max_rounds(self):
        f = self._iface(max_rounds=2)
        f.handle_tool("end_round", {})
        self.assertIn("final round", f.handle_tool("end_round", {}))
        self.assertEqual(f.round, 2)


class CacheTests(unittest.TestCase):
    def test_hash_changes_with_content(self):
        c = ScoreCache()
        a = T2Item(id="x", construct="math", text="t", designer_key="1", verified_key="1", verification_status="verified")
        c.put(a, {"A": [1]})
        self.assertEqual(c.get(a), {"A": [1]})
        a.text = "t2"
        self.assertIsNone(c.get(a))
        self.assertEqual(c.missing([a]), [a])


if __name__ == "__main__":
    unittest.main(verbosity=2)
