"""Evaluee panel and per-item x per-model x per-sample correctness precompute.

The panel is fixed before any designer runs.  Every panel entry is a (model, effort) configuration;
the identical-model placebo is a second configuration of the same model under a different key.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from .llm import LLM, ModelSpec
from . import graders

# ----------------------------------------------------------------------------------------------
# Panels.  Two are defined: the PILOT panel (two developers; the pilot domain) and the CONFIRMATORY panel
# (four developers: Anthropic, OpenAI, Google, xAI; BLINDING.md section 6).  Module-level constants
# (DISPLAYED_KEYS, PLACEBO_KEYS, HELDOUT_KEYS, TIERS, DISPLAY_NAMES, PANEL) are mutable containers that
# `set_active()` fills in place, so modules that did `from .panel import DISPLAYED_KEYS` see the switch.
# The default is the pilot panel (legacy scripts and tests); the confirmatory runner, the freeze script and
# the synthetic generator call `set_active("confirmatory")` explicitly.
# ----------------------------------------------------------------------------------------------

# roles: designer / sibling / small (distilled-descendant analogue) / older / unrelated-weak / placebo / heldout
PILOT_PANEL: list[ModelSpec] = [
    ModelSpec("opus55",   "anthropic", "claude-opus-5-5",   "low", 2048, "anthropic", "designer A; Anthropic frontier"),
    ModelSpec("sonnet55", "anthropic", "claude-sonnet-5-5", "low", 2048, "anthropic", "designer B; Anthropic mid-frontier"),
    ModelSpec("sonnet46", "anthropic", "claude-sonnet-4-6", "low", 2048, "anthropic", "older Anthropic sibling"),
    ModelSpec("haiku45",  "anthropic", "claude-haiku-4-5",  None,  2048, "anthropic", "small Anthropic"),
    ModelSpec("gpt55",    "openai",    "gpt-5.5",           "low", 2048, "openai",    "designer C; OpenAI frontier"),
    ModelSpec("gpt54mini","openai",    "gpt-5.4-mini",      "low", 2048, "openai",    "small OpenAI sibling (descendant analogue)"),
    ModelSpec("gpt54nano","openai",    "gpt-5.4-nano",      "low", 2048, "openai",    "tiny OpenAI"),
    ModelSpec("gpt51",    "openai",    "gpt-5.1",           "low", 2048, "openai",    "older OpenAI reasoning"),
    ModelSpec("gpt41",    "openai",    "gpt-4.1",           None,  2048, "openai",    "older OpenAI non-reasoning"),
    ModelSpec("gpt4omini","openai",    "gpt-4o-mini",       None,  2048, "openai",    "old small OpenAI"),
    # identical-model placebo: same configuration as sonnet55, independent samples
    ModelSpec("placebo_sonnet55", "anthropic", "claude-sonnet-5-5", "low", 2048, "anthropic", "identical-model placebo of sonnet55"),
    # held-out: never shown to any designer
    ModelSpec("heldout_opus5", "anthropic", "claude-opus-5", "low", 2048, "anthropic", "held-out (never displayed)"),
    ModelSpec("heldout_gpt54", "openai",    "gpt-5.4",       "low", 2048, "openai",    "held-out (never displayed)"),
]
PILOT_DISPLAYED_KEYS = ["opus55", "sonnet55", "sonnet46", "haiku45", "gpt55", "gpt54mini", "gpt54nano", "gpt51", "gpt41", "gpt4omini"]
PILOT_PLACEBO_KEYS = ["placebo_sonnet55"]
PILOT_HELDOUT_KEYS = ["heldout_opus5", "heldout_gpt54"]
PILOT_TIERS = {
    "opus55": 1, "gpt55": 1, "sonnet55": 1,
    "sonnet46": 2, "gpt51": 2, "gpt54mini": 2,
    "haiku45": 3, "gpt41": 3, "gpt54nano": 3, "gpt4omini": 3,
    "placebo_sonnet55": 1,
}
PILOT_DISPLAY_NAMES = {
    "opus55": "Claude Opus 5.5", "sonnet55": "Claude Sonnet 5.5", "sonnet46": "Claude Sonnet 4.6", "haiku45": "Claude Haiku 4.5",
    "gpt55": "GPT-5.5", "gpt54mini": "GPT-5.4 mini", "gpt54nano": "GPT-5.4 nano", "gpt51": "GPT-5.1", "gpt41": "GPT-4.1",
    "gpt4omini": "GPT-4o mini", "placebo_sonnet55": "Claude Sonnet 5.5 (B)",
}
# (designer key -> (display name, developer)) for the identity arms
PILOT_DESIGNER_IDENTITY = {
    "opus55": ("Claude Opus 5.5", "Anthropic"),
    "sonnet55": ("Claude Sonnet 5.5", "Anthropic"),
    "gpt55": ("GPT-5.5", "OpenAI"),
}

# ---- Confirmatory panel (registered 2026-10-25 from each provider's live model list; see docs/BUILD_REPORT.md) ----
# Three designers per developer: current strongest / mid (current-generation smaller model, or for xAI the previous
# flagship) / older generation.  Evaluee configuration: reasoning at LOW effort (Gemini thinkingLevel low; xAI
# reasoning_effort low where accepted), fixed evaluee instruction, output cap per pool (EVALUEE_MAX_TOKENS below; the
# ModelSpec's 2048 is the fallback for pools without a registered cap).  Designer configuration (see designer.py):
# same model ids at MEDIUM effort, 8000 output tokens.
CONFIRMATORY_PANEL: list[ModelSpec] = [
    # Anthropic
    ModelSpec("fable51",      "anthropic", "claude-fable-5-1",        "low", 2048, "anthropic", "designer; Anthropic current strongest (Mythos-class)"),
    ModelSpec("sonnet55",     "anthropic", "claude-sonnet-5-5",       "low", 2048, "anthropic", "designer; Anthropic mid (current generation)"),
    ModelSpec("opus5",        "anthropic", "claude-opus-5",           "low", 2048, "anthropic", "designer; Anthropic older generation (5.0)"),
    # OpenAI
    ModelSpec("gpt61sol",     "openai",    "gpt-6.1-sol",             "low", 2048, "openai",    "designer; OpenAI current strongest"),
    ModelSpec("gpt6luna",     "openai",    "gpt-6-luna",              "low", 2048, "openai",    "designer; OpenAI mid (current generation, small)"),
    ModelSpec("gpt55",        "openai",    "gpt-5.5",                 "low", 2048, "openai",    "designer; OpenAI older generation (5.5)"),
    # Google
    ModelSpec("gemini4argon", "google",    "gemini-4-argon",          "low", 2048, "google",    "designer; Google current strongest"),
    ModelSpec("gemini38flash","google",    "gemini-3.8-flash",        "low", 2048, "google",    "designer; Google mid (current generation, flash)"),
    ModelSpec("gemini31pro",  "google",    "gemini-3.1-pro-preview",  "low", 2048, "google",    "designer; Google older generation (3.1 Pro)"),
    # xAI
    ModelSpec("grok47",       "xai",       "grok-4.7",                "low", 2048, "xai",       "designer; xAI current strongest"),
    ModelSpec("grok45",       "xai",       "grok-4.5",                "low", 2048, "xai",       "designer; xAI mid (previous flagship)"),
    ModelSpec("grok43",       "xai",       "grok-4.3",                "low", 2048, "xai",       "designer; xAI older generation (4.3)"),
    # identical-model placebo: a second configuration of sonnet55 (independent samples), shown under pseudonyms only
    ModelSpec("placebo_sonnet55", "anthropic", "claude-sonnet-5-5",   "low", 2048, "anthropic", "identical-model placebo of sonnet55"),
    # held-out: scored on every pool item, never displayed to any confirmatory designer.  One older-generation model
    # per developer; these are also the replication designers (BLINDING.md section 6, PREREGISTRATION section 15).
    ModelSpec("heldout_sonnet46",   "anthropic", "claude-sonnet-4-6",         "low", 2048, "anthropic", "held-out; replication designer (Anthropic 4.6)"),
    ModelSpec("heldout_gpt54",      "openai",    "gpt-5.4",                   "low", 2048, "openai",    "held-out; replication designer (OpenAI 5.4)"),
    ModelSpec("heldout_gemini35flash","google",  "gemini-3.5-flash",          "low", 2048, "google",    "held-out; replication designer (Google 3.5 Flash; 2.5 Pro is closed to new users)"),
    ModelSpec("heldout_grok420",    "xai",       "grok-4.20-0309-reasoning",  "low", 2048, "xai",       "held-out; replication designer (xAI 4.20)"),
]
CONFIRMATORY_DISPLAYED_KEYS = ["fable51", "sonnet55", "opus5", "gpt61sol", "gpt6luna", "gpt55",
                               "gemini4argon", "gemini38flash", "gemini31pro", "grok47", "grok45", "grok43"]
CONFIRMATORY_PLACEBO_KEYS = ["placebo_sonnet55"]
CONFIRMATORY_HELDOUT_KEYS = ["heldout_sonnet46", "heldout_gpt54", "heldout_gemini35flash", "heldout_grok420"]
# Reputation tiers for the constrained within-tier shuffles of named sham arms (C7): 1 = current flagships,
# 2 = previous-generation flagships and the Anthropic mid model, 3 = small current-generation models and xAI 4.3.
CONFIRMATORY_TIERS = {
    "fable51": 1, "gpt61sol": 1, "gemini4argon": 1, "grok47": 1,
    "sonnet55": 2, "opus5": 2, "gpt55": 2, "gemini31pro": 2, "grok45": 2, "placebo_sonnet55": 2,
    "gpt6luna": 3, "gemini38flash": 3, "grok43": 3,
}
CONFIRMATORY_DISPLAY_NAMES = {
    "fable51": "Claude Fable 5.1", "sonnet55": "Claude Sonnet 5.5", "opus5": "Claude Opus 5",
    "gpt61sol": "GPT-6.1 Sol", "gpt6luna": "GPT-6 Luna", "gpt55": "GPT-5.5",
    "gemini4argon": "Gemini 4 Argon", "gemini38flash": "Gemini 3.8 Flash", "gemini31pro": "Gemini 3.1 Pro",
    "grok47": "Grok 4.7", "grok45": "Grok 4.5", "grok43": "Grok 4.3",
    "placebo_sonnet55": "Claude Sonnet 5.5 (B)",
}
CONFIRMATORY_DESIGNER_IDENTITY = {
    "fable51": ("Claude Fable 5.1", "Anthropic"), "sonnet55": ("Claude Sonnet 5.5", "Anthropic"), "opus5": ("Claude Opus 5", "Anthropic"),
    "gpt61sol": ("GPT-6.1 Sol", "OpenAI"), "gpt6luna": ("GPT-6 Luna", "OpenAI"), "gpt55": ("GPT-5.5", "OpenAI"),
    "gemini4argon": ("Gemini 4 Argon", "Google"), "gemini38flash": ("Gemini 3.8 Flash", "Google"), "gemini31pro": ("Gemini 3.1 Pro", "Google"),
    "grok47": ("Grok 4.7", "xAI"), "grok45": ("Grok 4.5", "xAI"), "grok43": ("Grok 4.3", "xAI"),
    # replication designers (never confirmatory designers)
    "heldout_sonnet46": ("Claude Sonnet 4.6", "Anthropic"), "heldout_gpt54": ("GPT-5.4", "OpenAI"),
    "heldout_gemini35flash": ("Gemini 2.5 Pro", "Google"), "heldout_grok420": ("Grok 4.20", "xAI"),
}
DEVELOPERS = ["anthropic", "openai", "google", "xai"]

# Evaluee output cap per main-study pool (coordinator decision 2026-10-25 10:58 UTC, prereg/DEVIATIONS.md): reasoning
# models lost 8.5-13% of math/code answers to truncation at 2048.  Applies to every evaluee call on that pool, i.e.
# the precompute and the in-session live re-score of edited items alike (`set_pool`); designer and monitor settings
# are untouched.  Pools not listed keep the ModelSpec cap.
EVALUEE_MAX_TOKENS = {"math": 4096, "factual": 4096, "code": 8192}
ACTIVE_POOL = {"name": None, "max_tokens": None}


def evaluee_max_tokens(pool_name: str | None) -> int | None:
    return EVALUEE_MAX_TOKENS.get(pool_name) if pool_name else None


def set_pool(pool_name: str | None) -> None:
    """Make `pool_name`'s evaluee cap the default for score_item in this process (runner calls it per pool)."""
    ACTIVE_POOL["name"] = pool_name
    ACTIVE_POOL["max_tokens"] = evaluee_max_tokens(pool_name)

PANELS = {
    "pilot": dict(panel=PILOT_PANEL, displayed=PILOT_DISPLAYED_KEYS, placebo=PILOT_PLACEBO_KEYS, heldout=PILOT_HELDOUT_KEYS,
                  tiers=PILOT_TIERS, names=PILOT_DISPLAY_NAMES, identity=PILOT_DESIGNER_IDENTITY),
    "confirmatory": dict(panel=CONFIRMATORY_PANEL, displayed=CONFIRMATORY_DISPLAYED_KEYS, placebo=CONFIRMATORY_PLACEBO_KEYS,
                         heldout=CONFIRMATORY_HELDOUT_KEYS, tiers=CONFIRMATORY_TIERS, names=CONFIRMATORY_DISPLAY_NAMES,
                         identity=CONFIRMATORY_DESIGNER_IDENTITY),
}

# Active panel (mutable containers; filled by set_active).  Default: pilot.
PANEL: list[ModelSpec] = []
DISPLAYED_KEYS: list[str] = []
PLACEBO_KEYS: list[str] = []
HELDOUT_KEYS: list[str] = []
TIERS: dict[str, int] = {}
DISPLAY_NAMES: dict[str, str] = {}
DESIGNER_IDENTITY: dict[str, tuple[str, str]] = {}
ACTIVE = {"name": None}


def set_active(name: str) -> None:
    """Switch the active panel in place ('pilot' or 'confirmatory')."""
    p = PANELS[name]
    PANEL[:] = list(p["panel"])
    DISPLAYED_KEYS[:] = list(p["displayed"])
    PLACEBO_KEYS[:] = list(p["placebo"])
    HELDOUT_KEYS[:] = list(p["heldout"])
    TIERS.clear(); TIERS.update(p["tiers"])
    DISPLAY_NAMES.clear(); DISPLAY_NAMES.update(p["names"])
    DESIGNER_IDENTITY.clear(); DESIGNER_IDENTITY.update(p["identity"])
    ACTIVE["name"] = name


set_active("pilot")


def all_panel_keys() -> list[str]:
    return list(DISPLAYED_KEYS) + list(PLACEBO_KEYS) + list(HELDOUT_KEYS)


def designer_keys() -> list[str]:
    """Confirmatory designers: every displayed key that is a model (the placebo is not a designer)."""
    return [k for k in DISPLAYED_KEYS if k not in PLACEBO_KEYS]


def spec_by_key(key: str) -> ModelSpec:
    for s in PANEL:
        if s.key == key:
            return s
    for s in PILOT_PANEL + CONFIRMATORY_PANEL:   # cross-panel lookup (e.g. pilot decoy rows under the confirmatory panel)
        if s.key == key:
            return s
    raise KeyError(key)


async def score_item(llm: LLM, spec: ModelSpec, item: dict, sample: int, max_tokens: int | None = None) -> dict:
    """One evaluee call + grading.  The same grader (metabench.graders.grade) serves the precompute, the live re-score
    of edited items and therefore session scoring; parse failures are scored 0 with parsed=0; sandbox failures are
    scored 0 and carried in grade_error.  Output cap: `max_tokens`, else the active pool's (set_pool), else the spec's."""
    prompt = graders.evaluee_prompt(item)
    temp = 1.0 if spec.effort is None else None   # non-reasoning models: sample at T=1 for independent draws
    r = await llm.chat(spec, None, [{"role": "user", "content": prompt}], tag=f"panel:{spec.key}", temperature=temp,
                       max_tokens=max_tokens or ACTIVE_POOL["max_tokens"])
    t0 = time.time()
    g = await graders.grade_async(item, r.text)
    return {"item": item["id"], "model": spec.key, "sample": sample, "pred": g.pred, "correct": g.correct,
            "parsed": g.parsed, "grade": g.method, "grade_error": g.error, "grade_s": round(time.time() - t0, 4),
            "in": r.in_tokens, "out": r.out_tokens, "stop": r.stop_reason, "text_tail": r.text[-200:]}


async def precompute(pool: dict[str, dict], specs: list[ModelSpec], k: int, out_path: Path, llm: LLM, concurrency: int = 48,
                     max_tokens: int | None = None, providers: set[str] | None = None):
    """Resumable and append-only.  Rule: the LAST row per (item, model, sample) triple in out_path wins.  A triple is
    done when its last row has no `error`; a triple whose last row is an error row (score_item raised after the client's
    retries) is retried and the new row is appended after it, superseding it for every reader (`latest_rows`,
    `load_correctness`, `error_counts_by_provider`).  Existing rows are never rewritten.
    `providers`: if given, only the triples of specs from these providers are processed in this invocation; the plan,
    seed and shuffle are those of a full run (the filter is applied after the shuffle), so a later invocation without it
    fills the remaining triples.  `max_tokens` is the pool's evaluee cap."""
    latest = latest_rows(out_path, lambda r: bool(r.get("error"))) if out_path.exists() else {}
    done = {t for t, err in latest.items() if not err}
    todo = [(it, s, smp) for it in pool.values() for smp in range(k) for s in specs if (it["id"], s.key, smp) not in done]
    # interleaved by item so both providers are busy at once; then shuffled with a fixed seed so that a resumed run
    # never front-loads one slow model and starves the other provider's semaphore
    import random as _r
    _r.Random(20261025).shuffle(todo)
    if providers is not None:
        todo = [(it, s, smp) for it, s, smp in todo if s.provider in providers]
    print(f"precompute: {len(done)} done, {len(latest) - len(done)} error rows to retry, {len(todo)} to do"
          + (f" (providers {sorted(providers)})" if providers is not None else ""), flush=True)
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    t0 = time.time()
    n = 0
    counts = {"parse_fail": 0, "grade_error": 0, "api_error": 0}

    async def one(it, s, smp):
        nonlocal n
        async with sem:
            try:
                rec = await score_item(llm, s, it, smp, max_tokens=max_tokens)
            except Exception as e:  # record failures; the next invocation retries them (last row per triple wins)
                rec = {"item": it["id"], "model": s.key, "sample": smp, "pred": None, "correct": 0, "parsed": 0, "error": str(e)[:300]}
            async with lock:
                with open(out_path, "a") as f:
                    f.write(json.dumps(rec) + "\n")
                n += 1
                if rec.get("error"):
                    counts["api_error"] += 1
                elif not rec.get("parsed"):
                    counts["parse_fail"] += 1
                if rec.get("grade_error"):
                    counts["grade_error"] += 1
                if n % 500 == 0:
                    el = time.time() - t0
                    print(f"  {n}/{len(todo)} in {el:.0f}s  ({n/el:.1f}/s)  cost so far ${llm.totals['cost']:.2f}", flush=True)

    await asyncio.gather(*(one(it, s, smp) for it, s, smp in todo))
    # totals only (never per model: parse rates per model could rank the panel)
    print(f"precompute finished: {n} new records in {time.time()-t0:.0f}s, est cost ${llm.totals['cost']:.2f}; "
          f"parse failures {counts['parse_fail']}, grader errors {counts['grade_error']}, api errors {counts['api_error']}", flush=True)
    return counts


def latest_rows(path: Path, keep=lambda r: r) -> dict[tuple[str, str, int], object]:
    """(item, model, sample) -> keep(row) of the LAST row for that triple in file order: a retry's row is appended after
    the error row it supersedes (see precompute), so the last row is the one that counts.  Unparsable lines (a partial
    last line after a crash) are skipped."""
    out: dict[tuple[str, str, int], object] = {}
    with open(path) as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            out[(r["item"], r["model"], r["sample"])] = keep(r)
    return out


def load_correctness(path: Path) -> dict[tuple[str, str], list[int]]:
    """(item_id, model_key) -> list of 0/1 over samples.  Last row per triple wins; a triple whose last row is an error
    row is excluded, so a retried triple is counted exactly once (never both its error row and its retry)."""
    out: dict[tuple[str, str], list[int]] = {}
    for (item, model, _), c in latest_rows(path, lambda r: None if r.get("error") else int(r["correct"])).items():
        if c is not None:
            out.setdefault((item, model), []).append(c)
    return out


def error_counts_by_provider(path: Path, specs: list[ModelSpec] | None = None) -> dict[str, int]:
    """Error rows remaining per provider: triples whose LAST row is an error row (superseded error rows do not count).
    Counts only, keyed by provider (model keys mapped through `specs`, default: the active panel), never per model."""
    provider = {s.key: s.provider for s in (PANEL if specs is None else specs)}
    out = {d: 0 for d in DEVELOPERS}
    for (_, model, _), err in latest_rows(path, lambda r: bool(r.get("error"))).items():
        if err:
            p = provider.get(model, "unknown")
            out[p] = out.get(p, 0) + 1
    return out
