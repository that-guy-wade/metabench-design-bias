"""Builder 8: bounded, non-blocking live re-score of edited items (`--live-rescore-wait-s`).

(a) default None reproduces the pre-Builder-8 blocking behaviour exactly (golden digest of a scripted session computed
    on the pristine code); (b) with W = 1 s and a panel entry that takes 5 s, edit_item returns in about 1 s, the scores
    view shows that entry as pending, a later view shows the real value, every number shown equals the blocking run's and
    the final outcomes equal the blocking run's (interface and full runner path, where the runner drains the calls
    before the outputs are written and sealed); (c) a panel call that exhausts its retries is recorded identically in
    both modes; (d) `run` refuses a W that differs from the registration; the run script passes MB_LIVE_RESCORE_WAIT_S."""
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from metabench import panel  # noqa: E402
from metabench.arms import make_session_config  # noqa: E402
from metabench.designer import make_live_scorer, run_session  # noqa: E402
from metabench.interface import T1Interface  # noqa: E402
from metabench.llm import LLMResponse, ToolCall  # noqa: E402
from metabench.scoring import reference_scores  # noqa: E402

SLOW_KEY = "grok43"          # the panel entry whose live re-score is slow (an xAI entry, as in the math pool)
SLOW_S = 5.0


def _resp(text="", calls=None, spec=None):
    return LLMResponse(text=text, tool_calls=calls or [], stop_reason="tool_use" if calls else "end_turn", in_tokens=10, out_tokens=5,
                       latency=0.01, raw_assistant_message={"role": "assistant", "content": text},
                       provider=getattr(spec, "provider", "google"), model_id=getattr(spec, "model_id", "fake"))


class PanelFake:
    """Deterministic evaluee: the answer depends only on (model key, prompt, how many times this model saw this prompt),
    so the blocking and the bounded run draw identical answers whatever the interleaving.  `slow` maps a model key to
    a delay applied to prompts containing 'EDIT' (live re-scores only); `fail` lists model keys whose calls raise as
    after exhausting the client's retries."""

    def __init__(self, slow=None, fail=()):
        self.slow = slow or {}
        self.fail = set(fail)
        self.seen: dict = {}
        self.totals = {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "errors": 0}
        self.by_tag: dict = {}
        self.done_at: dict = {}       # (model key, prompt) -> time its last live call returned

    async def chat(self, spec, system, messages, tools=None, max_tokens=None, tag="", temperature=None, max_attempts=7):
        prompt = messages[0]["content"] if messages else ""
        if tag.startswith("panel:"):
            live = "EDIT" in prompt
            if live and spec.key in self.slow:
                await asyncio.sleep(self.slow[spec.key])
            if live and spec.key in self.fail:
                self.totals["errors"] += max_attempts
                raise RuntimeError("retries exhausted (fake)")
            n = self.seen[(spec.key, prompt)] = self.seen.get((spec.key, prompt), 0) + 1
            h = int(hashlib.sha256(f"{spec.key}|{prompt}|{n}".encode()).hexdigest()[:8], 16)
            if live:
                self.done_at[(spec.key, prompt)] = time.time()
            return _resp(text=f"Reasoning. Answer: {'A' if h % 100 < 55 else 'B'}", spec=spec)
        return _resp(text='{"evidence_score": 3, "favoured_label": null, "disfavoured_label": null, "rationale": "none", "steering_actions": []}', spec=spec)


class ScriptedDesigner(PanelFake):
    """PanelFake plus a scripted designer: add 10 items, view, edit two items (one twice), view, weights + format, view,
    submit; probes answered in text."""

    def __init__(self, pool_ids, **kw):
        super().__init__(**kw)
        self.ids = pool_ids
        self.steps: dict = {}

    async def chat_conv(self, spec, system, conv, tools=None, max_tokens=None, tag="", max_attempts=7):
        sid = tag.split(":", 1)[1]
        bt = self.by_tag.setdefault(tag, {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "errors": 0})
        bt["calls"] += 1
        if tag.startswith("probe:"):
            return _resp(text="MDL-01, MDL-02, MDL-03. Ordinary work.", spec=spec)
        k = self.steps[sid] = self.steps.get(sid, 0) + 1
        ids = self.ids
        script = {
            1: [("add_items", {"ids": ids[:10]})],
            2: [("request_panel_scores", {})],
            3: [("edit_item", {"id": ids[1], "question": "EDIT one: reworded question 1?"})],
            4: [("edit_item", {"id": ids[2], "question": "EDIT two: reworded question 2?", "options": ["w", "x", "y", "z"]})],
            5: [("request_panel_scores", {})],
            6: [("edit_item", {"id": ids[1], "question": "EDIT three: reworded again?"})],
            7: [("set_weights", {"weights": {ids[0]: 2.0, ids[1]: 3.0}}), ("set_format", {"scoring_rule": "weighted_accuracy"})],
            8: [("request_panel_scores", {})],
            9: [("submit", {"final_notes": "done"})],
        }
        if k in script:
            return _resp(calls=[ToolCall(f"c{k}{j}", n, a) for j, (n, a) in enumerate(script[k])], spec=spec)
        return _resp(text="(no further changes)", spec=spec)


def _world(seed=0, n_pool=40, k=3):
    panel.set_active("confirmatory")
    rng = np.random.default_rng(seed)
    keys = panel.all_panel_keys()
    pool = {f"P{i:04d}": {"id": f"P{i:04d}", "category": ["a", "b", "c"][i % 3], "question": f"Question {i}?",
                          "options": ["one", "two", "three", "four"], "answer": "A"} for i in range(n_pool)}
    p_model = {m: 0.35 + 0.03 * j for j, m in enumerate(keys)}
    corr = {(i, m): [int(rng.random() < p_model[m]) for _ in range(k)] for i in pool for m in keys}
    return pool, corr, reference_scores(list(pool), keys, corr)


def _canon(sdir: Path) -> dict:
    """A session's outputs minus wall-clock fields."""
    def rows(name, drop=("t",)):
        p = sdir / name
        return [{k: v for k, v in json.loads(l).items() if k not in drop} for l in p.read_text().splitlines()] if p.exists() else None
    bench = json.loads((sdir / "benchmark.json").read_text())
    bench.pop("wall_s", None)
    return {"actions": rows("actions.jsonl"), "scores_views": rows("scores_views.jsonl"), "transcript": rows("transcript.jsonl"),
            "item_outcomes": rows("item_outcomes.jsonl", drop=()), "benchmark": bench, "probes": json.loads((sdir / "probes.json").read_text())}


def scripted_session(tmp: Path, arm: str, **session_kw) -> tuple[dict, ScriptedDesigner]:
    pool, corr, ref = _world()
    ident = "true" if arm == "true_named" else "blinded"
    cfg = make_session_config(f"b8_{arm}", "gemini38flash", arm, ident, 0, 777, ref, n_items_required=10, with_monitors=True)
    llm = ScriptedDesigner(sorted(pool), **session_kw.pop("fake", {}))
    asyncio.run(run_session(cfg, llm, pool, corr, ref, tmp, **session_kw))
    return _canon(tmp / cfg.session_id), llm


def digest(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()


# (a) ------------------------------------------------------------------------------------------------------------------
# sha256 of _canon() per arm, computed with this file's scripted_session on the pristine pre-Builder-8 code
# (/tmp/build8_orig, 2026-10-28): the default (live_wait_s=None) path must reproduce the old outputs exactly.
GOLDEN = {
    "sham": "03eed907dc423f84ebf5d73cce60c21d50dcdcbe7bc9b0891f4f276ca3358feb",
    "true_blinded": "b6303f6609aaa12dc7a6409d9aa97672346fec5afcdc360a189db2dceefbd6f8",
    "none": "e48d47342c0632f9fad98137adaa51133d1421a244038dd49e7f952af488573f",
}


@pytest.mark.parametrize("arm", sorted(GOLDEN))
def test_default_reproduces_blocking_behaviour_exactly(tmp_path, arm):
    out, _ = scripted_session(tmp_path, arm)
    assert digest(out) == GOLDEN[arm]
    assert not any("pending" in v for v in out["scores_views"])


def test_default_blocks_until_every_panel_call_returns(tmp_path):
    pool, corr, ref = _world()
    cfg = make_session_config("b8_block", "gemini38flash", "true_blinded", "blinded", 0, 5, ref, n_items_required=10)
    llm = PanelFake(slow={SLOW_KEY: 1.5})
    iface = T1Interface(cfg, pool, corr, tmp_path / "s", live_scorer=make_live_scorer(llm), reference=ref)

    async def go():
        await iface.handle_tool("add_items", {"ids": sorted(pool)[:10]})
        t0 = time.time()
        await iface.handle_tool("edit_item", {"id": sorted(pool)[0], "question": "EDIT q?"})
        return time.time() - t0
    assert asyncio.run(go()) >= 1.4 and not getattr(iface, "live_tasks", None)   # passes on the pre-Builder-8 code too


# (b) ------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("arm", ["true_blinded", "sham", "inverted", "instructed"])
def test_bounded_wait_shows_pending_then_the_value(tmp_path, arm):
    pool, corr, ref = _world()
    ids = sorted(pool)
    cfg = make_session_config(f"b8_{arm}", "gemini38flash", arm, "blinded", 0, 11, ref, n_items_required=10, with_monitors=True)

    def build(wait, d):
        llm = PanelFake(slow={SLOW_KEY: SLOW_S})
        return T1Interface(cfg, pool, corr, tmp_path / d, live_scorer=make_live_scorer(llm), reference=ref, live_wait_s=wait), llm

    async def script(iface, wait_for_slow):
        await iface.handle_tool("add_items", {"ids": ids[:10]})
        t0 = time.time()
        edit_msg = await iface.handle_tool("edit_item", {"id": ids[3], "question": "EDIT: a reworded question?"})
        edit_s = time.time() - t0
        texts = [await iface.handle_tool("request_panel_scores", {})]      # first numeric view while the slow entry is out
        await iface.handle_tool("add_items", {"ids": ids[10:11]})
        texts.append(await iface.handle_tool("request_panel_scores", {}))
        if wait_for_slow:
            await asyncio.sleep(SLOW_S + 0.5)
        texts.append(await iface.handle_tool("request_panel_scores", {}))
        await iface.drain_live()
        iface.finalize_live()
        return edit_msg, edit_s, texts

    blk, _ = build(None, "blocking")
    _, blk_s, blk_texts = asyncio.run(script(blk, False))
    bnd, llm = build(1.0, "bounded")
    msg, edit_s, texts = asyncio.run(script(bnd, True))

    assert blk_s >= SLOW_S - 0.1
    assert 0.9 <= edit_s < 2.0, edit_s                       # bounded: returns after about W
    assert "pending" in msg
    label = cfg.label_map[SLOW_KEY]
    v1, v2, v3 = bnd.scores_views
    for v, t in ((v1, texts[0]), (v2, texts[1])):
        assert SLOW_KEY in v["pending"] and SLOW_KEY not in v["shown"] and SLOW_KEY not in v["order"]
        assert f"{label} | pending" in t and "pending = " in t and f"{label} | 0.0%" not in t
    assert "pending" not in v3 and f"{label} | pending" not in texts[2]
    assert v3["shown"][SLOW_KEY] == blk.scores_views[2]["shown"][SLOW_KEY]
    # the designer never sees a different number: every value shown equals the blocking run's at the same step
    for vb, vk in zip(blk.scores_views, bnd.scores_views):
        assert all(vk["shown"][k] == vb["shown"][k] for k in vk["shown"])
        assert vk["true_all"] == vb["true_all"] and vk["true"] == vb["true"]          # backfilled after the drain
    for tb, tk in zip(blk_texts, texts):                                               # rendered lines likewise
        numeric = [l for l in tk.splitlines() if l.endswith("%")]
        assert set(numeric) <= set(tb.splitlines())
    assert bnd.export(ref) == blk.export(ref)
    assert bnd.item_outcomes() == blk.item_outcomes()
    rewritten = [json.loads(l) for l in (tmp_path / "bounded" / "scores_views.jsonl").read_text().splitlines()]
    assert rewritten == bnd.scores_views


def test_pending_rendering_is_the_same_in_every_numeric_arm(tmp_path):
    pool, corr, ref = _world()
    ids = sorted(pool)
    shapes = {}
    for arm in ("true_named", "true_blinded", "sham", "inverted", "instructed"):
        ident = "true" if arm == "true_named" else "blinded"
        cfg = make_session_config(f"b8r_{arm}", "gemini38flash", arm, ident, 0, 3, ref, n_items_required=10)
        iface = T1Interface(cfg, pool, corr, tmp_path / arm, live_scorer=make_live_scorer(PanelFake(slow={SLOW_KEY: 2.0})),
                            reference=ref, live_wait_s=0.2)

        async def go():
            await iface.handle_tool("add_items", {"ids": ids[:10]})
            await iface.handle_tool("edit_item", {"id": ids[0], "question": "EDIT q?"})
            t = await iface.handle_tool("request_panel_scores", {})
            await iface.drain_live()
            return t
        text = asyncio.run(go())
        label = cfg.label_map[SLOW_KEY]
        pend = [l for l in text.splitlines() if "pending" in l]
        shapes[arm] = [l.replace(label, "<L>") for l in pend]
    assert len(set(map(tuple, shapes.values()))) == 1, shapes
    assert shapes["sham"][0] == "<L> | pending"


def test_stale_generation_never_overwrites_a_newer_edit(tmp_path):
    """The item is edited again while the first wording's slow call is out: the late answer for the old wording must
    not replace the new wording's value (as in blocking mode, where the second edit overwrites the first)."""
    pool, corr, ref = _world()
    ids = sorted(pool)
    cfg = make_session_config("b8_gen", "gemini38flash", "true_blinded", "blinded", 0, 13, ref, n_items_required=10)

    class SlowFirst(PanelFake):
        async def chat(self, spec, system, messages, **kw):
            if spec.key == SLOW_KEY and "ZQSLOW" in messages[0]["content"]:
                await asyncio.sleep(1.5)
            return await super().chat(spec, system, messages, **kw)

    def run(wait, d):
        iface = T1Interface(cfg, pool, corr, tmp_path / d, live_scorer=make_live_scorer(SlowFirst()), reference=ref, live_wait_s=wait)

        async def go():
            await iface.handle_tool("add_items", {"ids": ids[:10]})
            await iface.handle_tool("edit_item", {"id": ids[0], "question": "EDIT ZQSLOW first wording?"})
            await iface.handle_tool("edit_item", {"id": ids[0], "question": "EDIT second wording?"})
            await iface.handle_tool("request_panel_scores", {})
            await iface.drain_live()
            iface.finalize_live()
        asyncio.run(go())
        return iface
    blk, bnd = run(None, "b"), run(0.1, "k")
    assert "pending" not in bnd.scores_views[0]          # the current wording's answers were all back (the stale one is not waited for)
    assert bnd.item_outcomes() == blk.item_outcomes() and bnd.scores_views[0]["shown"] == blk.scores_views[0]["shown"]


def test_session_outputs_equal_blocking_outputs(tmp_path):
    """run_session end to end: bounded wait, slow entry; the drained outputs equal the blocking run's (apart from the
    edit tool's wording, the pending marker and the transcript text that carries them)."""
    blk, _ = scripted_session(tmp_path / "blk", "sham", fake={"slow": {SLOW_KEY: 1.0}})
    bnd, _ = scripted_session(tmp_path / "bnd", "sham", fake={"slow": {SLOW_KEY: 1.0}}, live_wait_s=0.1)
    assert bnd["item_outcomes"] == blk["item_outcomes"]
    assert bnd["benchmark"] == blk["benchmark"]
    assert any("pending" in v for v in bnd["scores_views"])
    for vb, vk in zip(blk["scores_views"], bnd["scores_views"]):
        assert {k: v for k, v in vk.items() if k not in ("pending", "order", "shown")} == {k: v for k, v in vb.items() if k not in ("order", "shown")}
        assert all(vb["shown"][k] == x for k, x in vk["shown"].items())


# (c) ------------------------------------------------------------------------------------------------------------------
def test_exhausted_retries_recorded_identically_in_both_modes(tmp_path):
    blk, _ = scripted_session(tmp_path / "blk", "true_blinded", fake={"fail": {SLOW_KEY}})
    bnd, _ = scripted_session(tmp_path / "bnd", "true_blinded", fake={"fail": {SLOW_KEY}}, live_wait_s=1.0)
    assert bnd["item_outcomes"] == blk["item_outcomes"] and bnd["benchmark"] == blk["benchmark"]
    assert bnd["scores_views"] == blk["scores_views"]           # nothing left pending: a failed call is a returned call
    edited = {r["item_id"] for r in blk["item_outcomes"] if r["item_id"] in blk["benchmark"]["edited_items"]}
    # as the blocking path records it: no live sample returned -> the precomputed counts stand in
    pool, corr, _ = _world()
    for r in bnd["item_outcomes"]:
        if r["item_id"] in edited and r["model_key"] == SLOW_KEY:
            assert r["n_samples"] == len(corr[(r["item_id"], SLOW_KEY)])


# runner: drain before outputs, registration of W, refusal (d), run script -----------------------------------------------
class RunnerFake(PanelFake):
    """Runner-path designer: add 8 items, edit one, request scores, submit."""

    def __init__(self, pool_ids, **kw):
        super().__init__(**kw)
        self.ids = pool_ids
        self.steps: dict = {}
        self.started: dict = {}         # session id -> time of its first designer turn
        self.ended: dict = {}           # session id -> time of its last designer/probe turn

    async def chat_conv(self, spec, system, conv, tools=None, max_tokens=None, tag="", max_attempts=7):
        sid = tag.split(":", 1)[1]
        bt = self.by_tag.setdefault(tag, {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "errors": 0})
        bt["calls"] += 1
        self.started.setdefault(sid, time.time())
        self.ended[sid] = time.time()
        if tag.startswith("probe:"):
            return _resp(text="MDL-01, MDL-02, MDL-03. Ordinary work.", spec=spec)
        k = self.steps[sid] = self.steps.get(sid, 0) + 1
        script = {1: ("add_items", {"ids": self.ids[:8]}), 2: ("edit_item", {"id": self.ids[0], "question": f"EDIT {sid}: reworded?"}),
                  3: ("request_panel_scores", {}), 4: ("submit", {"final_notes": "done"})}
        if k in script:
            return _resp(calls=[ToolCall(f"c{k}", *script[k])], spec=spec)
        return _resp(text="(no further changes)", spec=spec)


def _runner_mod():
    sys.path.insert(0, str(ROOT / "tests"))
    import test_runner as TR  # the runner tests' pool and argv helpers
    return TR


def _run_pool(tmp_path, wait):
    import scripts_freeze as F
    TR = _runner_mod()
    (tmp_path / "prereg").mkdir(parents=True)
    pool = TR._pool(tmp_path)
    pool_ids = [json.loads(l)["id"] for l in open(pool)]
    F.freeze(ROOT, "test", tmp_path / "prereg" / "frozen_code.json")
    fakes = []

    def factory():
        fakes.append(RunnerFake(pool_ids, slow={SLOW_KEY: 4.0}))
        return fakes[-1]
    kw = {"cells": "true_blinded:blinded:1,sham:blinded:1", "concurrency": 1}
    if wait is not None:
        kw["live_rescore_wait_s"] = wait
    r = TR._runner(tmp_path, pool, "all", llm=factory, **kw)
    r.cmd_precompute(); r.cmd_register()
    t0 = time.time()
    r.cmd_run()
    return r, fakes[-1], time.time() - t0


def test_runner_bounded_wait_drains_before_outputs_and_matches_blocking(tmp_path, capsys):
    pytest.importorskip("scripts_health_view")
    _, blk_fake, _ = _run_pool(tmp_path / "blk", None)
    r, fake, _ = _run_pool(tmp_path / "bnd", 0.5)
    out = capsys.readouterr().out
    work_b, work_k = tmp_path / "blk" / "work", tmp_path / "bnd" / "work"
    key = lambda x: (x["session_id"], x["item_id"], x["model_key"])
    rows_b = sorted((json.loads(l) for l in open(work_b / "results" / "item_outcomes.jsonl")), key=key)
    rows_k = sorted((json.loads(l) for l in open(work_k / "results" / "item_outcomes.jsonl")), key=key)
    assert rows_k == rows_b and rows_k
    sids = sorted(fake.started, key=fake.started.get)
    assert len(sids) == 4       # 2 designers x 2 cells, one at a time
    for sid in sids:
        sdir = work_k / "sessions" / sid
        b = json.loads((sdir / "benchmark.json").read_text())
        bb = json.loads((work_b / "sessions" / sid / "benchmark.json").read_text())
        assert {k: b[k] for k in ("produced_scores", "displayed_order", "offsets_applied", "items", "valid")} == \
               {k: bb[k] for k in ("produced_scores", "displayed_order", "offsets_applied", "items", "valid")}
        slow_done = fake.done_at[(SLOW_KEY, next(p for (m, p) in fake.done_at if m == SLOW_KEY and sid in p))]
        assert fake.ended[sid] < slow_done                       # the designer finished before its slow live calls returned ...
        assert (sdir / "item_outcomes.jsonl").stat().st_mtime >= slow_done - 0.05    # ... and the outputs were written after them
        views = [json.loads(l) for l in (sdir / "scores_views.jsonl").read_text().splitlines()]
        assert SLOW_KEY in views[0]["pending"] and SLOW_KEY in views[0]["true_all"]     # shown pending, truth backfilled
    # concurrency 1: the second session starts while the first one's slow calls are still draining (blocking: after)
    first_slow = max(t for (m, p), t in fake.done_at.items() if m == SLOW_KEY and sids[0] in p)
    assert fake.started[sids[1]] < first_slow
    bsids = sorted(blk_fake.started, key=blk_fake.started.get)
    assert blk_fake.started[bsids[1]] > max(t for (m, p), t in blk_fake.done_at.items() if m == SLOW_KEY and bsids[0] in p)
    assert not r.live_outstanding
    reg = json.loads((tmp_path / "bnd" / "prereg" / "confirmatory_hashes_smoke.json").read_text())
    man = json.loads((work_k / "run_manifest.json").read_text())
    assert reg["live_rescore_wait_s"] == 0.5 and man["live_rescore_wait_s"] == 0.5
    assert json.loads((tmp_path / "blk" / "prereg" / "confirmatory_hashes_smoke.json").read_text())["live_rescore_wait_s"] is None
    assert "live re-score: 0 calls still outstanding" in out
    # sealed after the drain: the sealed item outcomes are the drained ones (same plaintext size as the final file)
    man_s = json.loads((tmp_path / "bnd" / "sealed" / "MANIFEST.json").read_text())
    for sid in sids:
        rel = f"sessions/{sid}/item_outcomes.jsonl"
        assert man_s["files"][rel]["plaintext_bytes"] == (work_k / rel).stat().st_size


# (d) ------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("reg_w,run_w", [(None, 1.0), (1.0, None), (1.0, 2.0)])
def test_run_refuses_mismatched_wait(tmp_path, reg_w, run_w):
    import scripts_freeze as F
    TR = _runner_mod()
    pool = TR._pool(tmp_path)
    (tmp_path / "prereg").mkdir()
    pool_ids = [json.loads(l)["id"] for l in open(pool)]
    F.freeze(ROOT, "test", tmp_path / "prereg" / "frozen_code.json")
    kw = {} if reg_w is None else {"live_rescore_wait_s": reg_w}
    r = TR._runner(tmp_path, pool, "all", llm=lambda: RunnerFake(pool_ids), **kw)
    r.cmd_precompute(); r.cmd_register()
    kw2 = {} if run_w is None else {"live_rescore_wait_s": run_w}
    r2 = TR._runner(tmp_path, pool, "run", llm=lambda: RunnerFake(pool_ids), **kw2)
    with pytest.raises(SystemExit, match="live-rescore-wait-s"):
        r2.cmd_run()
    assert not (tmp_path / "work" / "sessions").exists() or not any((tmp_path / "work" / "sessions").iterdir())
    # re-registering with a different W without --force is refused too
    r3 = TR._runner(tmp_path, pool, "register", llm=lambda: RunnerFake(pool_ids), **kw2)
    with pytest.raises(SystemExit, match="live_rescore_wait_s"):
        r3.cmd_register()


def test_registration_without_the_field_means_blocking(tmp_path):
    """Registrations written before Builder 8 (math, factual) have no live_rescore_wait_s: run without the flag proceeds
    past the check, run with it refuses."""
    import scripts_runner as R
    a = R.build_parser().parse_args(["run", "--pool", "p", "--pool-name", "x"])
    assert a.live_rescore_wait_s is None and R.live_wait_option(None) is None
    for bad in (-1.0, float("inf"), float("nan")):
        with pytest.raises(SystemExit):
            R.live_wait_option(bad)


def test_run_script_passes_the_env_value_to_register_and_run(tmp_path):
    import scripts_freeze as F
    sys.path.insert(0, str(ROOT / "tests"))
    import test_run_confirmatory as RC
    root = RC._root(tmp_path)
    F.freeze(root, "test")
    env = {"PATH": RC._stub_gcloud(root), "MB_RUN_ROOT": str(root), "MB_POOLS": "code", "MB_LIVE_RESCORE_WAIT_S": "900"}
    r = subprocess.run(["bash", str(RC.SCRIPT), "--dry-run"], cwd=root.parent, env=env, capture_output=True, text=True)
    dry = [ln[4:] for ln in r.stdout.splitlines() if ln.startswith("DRY ")]
    assert r.returncode == 0 and len(dry) == 5, r.stdout + r.stderr
    assert dry[2].endswith("--live-rescore-wait-s 900") and dry[3].endswith("--live-rescore-wait-s 900")
    assert not any("live-rescore" in c for c in (dry[0], dry[1], dry[4]))
    env.pop("MB_LIVE_RESCORE_WAIT_S")
    shutil.rmtree(root / "docs", ignore_errors=True)
    r2 = subprocess.run(["bash", str(RC.SCRIPT), "--dry-run"], cwd=root.parent, env=env, capture_output=True, text=True)
    assert r2.returncode == 0 and "live-rescore" not in r2.stdout
