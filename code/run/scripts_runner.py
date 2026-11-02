"""Confirmatory runner (BLINDING.md sections 2-4).  A script, not an agent.

Everything it produces (panel precompute, registration, sessions, traces, scores, monitor outputs, health secrets,
endpoints) is written into a tmpfs working directory and sealed file-by-file with gpg to the public key registered in
prereg/sealing_key.json (GNUPGHOME = run/sealing/gnupg; no private key exists on any box).  Stdout carries only
session ids, exit codes, validity flags, API error counts and timings.

Commands (one process per command; the working directory lives in tmpfs between commands and is removed by `run` on
normal completion, or by `wipe`):
  precompute --pool pools/math.jsonl --pool-name math [--samples 5]
  register   --pool pools/math.jsonl --pool-name math        # writes prereg/confirmatory_hashes.json (commitments only)
  run        --pool pools/math.jsonl --pool-name math        # refuses unless prereg/frozen_code.json verifies
  all        (precompute + register + run in one process)
  wipe
Smoke / throwaway plans: --designers k1,k2 --cells sham:blinded:1,true_named:true:1 --n-items 10 --k-rounds 1 --samples 1
Bounded live re-score (Builder 8): `--live-rescore-wait-s W` on register and run (default: edit_item blocks on the live
re-score, the math and factual registrations).  W is recorded in the registration and the run manifest; run refuses
if it differs from the registration.  Outstanding live calls are drained before a session's outputs are written.
Partial precompute while one provider is down (precompute only; register/run refuse the flags):
  precompute ... --skip-providers google      # or --only-providers anthropic,openai,xai; a later full precompute fills the rest
Error rows (a call that failed after the client's retries) are retried by the next precompute invocation; the last row per
(item, model, sample) wins for every reader (metabench.panel.precompute), and precompute prints the error rows remaining per
provider at the end.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from metabench import panel  # noqa: E402
from metabench.llm import LLM, load_keys_from_env_file  # noqa: E402
from metabench.pool import load_pool  # noqa: E402
from metabench.scoring import reference_scores  # noqa: E402
from metabench.briefs import pool_description_for  # noqa: E402

MASTER_SEED = 20261025
K_ROUNDS = 4
GNUPGHOME = ROOT / "sealing" / "gnupg"
SEALED = ROOT / "sealed"
HEALTH_DIR = ROOT / "health"
PREREG = ROOT / "prereg"
DECOYS_PER_DESIGNER = 3
# per-provider client concurrency in make_llm; MB_<PROVIDER>_CONCURRENCY (positive integer) overrides one for a new process
LLM_CONCURRENCY = {"anthropic": 40, "openai": 56, "google": 32, "xai": 64}
_concurrency_warned: set[str] = set()


def llm_concurrency() -> dict[str, int]:
    """LLM_CONCURRENCY with each MB_<PROVIDER>_CONCURRENCY override applied; an invalid value keeps the default and
    prints one stderr warning line per variable per process."""
    out = dict(LLM_CONCURRENCY)
    for p, default in LLM_CONCURRENCY.items():
        var = f"MB_{p.upper()}_CONCURRENCY"
        raw = os.environ.get(var)
        if raw is None:
            continue
        n = int(raw) if raw.isascii() and raw.isdigit() else 0
        if n > 0:
            out[p] = n
        elif var not in _concurrency_warned:
            print(f"warning: {var}={raw!r} is not a positive integer; using {default}", file=sys.stderr)
            _concurrency_warned.add(var)
    return out


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def session_seed(designer: str, arm: str, ident: str, rep: int, suffix: str = "") -> int:
    h = hashlib.sha256(f"{MASTER_SEED}|{designer}|{arm}|{ident}|{rep}{('|' + suffix) if suffix else ''}".encode()).hexdigest()
    return int(h[:8], 16)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------------------------------
# Sealing
# ----------------------------------------------------------------------------------------------

class Sealer:
    def __init__(self, sealed_dir: Path = SEALED, gnupghome: Path = GNUPGHOME, key_file: Path = PREREG / "sealing_key.json"):
        self.sealed_dir = sealed_dir
        self.gnupghome = gnupghome
        self.fpr = json.loads(key_file.read_text())["unblinding_key_fingerprint"]
        self.manifest_path = sealed_dir / "MANIFEST.json"
        self.manifest: dict = json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else {"files": {}}

    def _gpg(self, *args: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "GNUPGHOME": str(self.gnupghome)}
        return subprocess.run(["gpg", "--batch", "--yes", "--quiet", "--no-tty", *args], env=env, capture_output=True, text=True)

    def check_keyring(self) -> None:
        r = self._gpg("--list-keys", "--with-colons")
        fprs = [l.split(":")[9] for l in r.stdout.splitlines() if l.startswith("fpr:")]
        if self.fpr not in fprs:
            raise SystemExit(f"sealing: fingerprint {self.fpr} not in keyring {self.gnupghome}")
        r2 = self._gpg("--list-secret-keys", "--with-colons")
        if any(l.startswith("sec:") for l in r2.stdout.splitlines()):
            raise SystemExit("sealing: a SECRET key is present in the sealing keyring; refusing to run (the private key must not exist on this box)")

    def seal(self, src: Path, rel: str) -> str:
        """Encrypt src to sealed/<rel>.gpg; returns the ciphertext sha256.  Idempotent per rel (re-seals)."""
        out = self.sealed_dir / (rel + ".gpg")
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            out.unlink()
        r = self._gpg("--trust-model", "always", "--encrypt", "--recipient", self.fpr, "--output", str(out), str(src))
        if r.returncode != 0 or not out.exists():
            raise RuntimeError(f"gpg encrypt failed for {rel}: rc={r.returncode}")
        h = sha256_file(out)
        self.manifest["files"][rel] = {"ciphertext_sha256": h, "plaintext_bytes": src.stat().st_size, "sealed_at": utc()}
        self.write_manifest()
        return h

    def seal_tree(self, work: Path, skip_existing: bool = True) -> int:
        n = 0
        for p in sorted(work.rglob("*")):
            if p.is_file():
                rel = str(p.relative_to(work))
                if skip_existing and rel in self.manifest["files"] and (self.sealed_dir / (rel + ".gpg")).exists() \
                        and self.manifest["files"][rel]["plaintext_bytes"] == p.stat().st_size:
                    continue
                self.seal(p, rel); n += 1
        return n

    def write_manifest(self) -> None:
        self.sealed_dir.mkdir(parents=True, exist_ok=True)
        self.manifest["written_at"] = utc()
        self.manifest["recipient_fingerprint"] = self.fpr
        txt = json.dumps(self.manifest, indent=1, sort_keys=True)
        self.manifest_path.write_text(txt)
        (self.sealed_dir / "MANIFEST.sha256").write_text(hashlib.sha256(txt.encode()).hexdigest() + "\n")


# ----------------------------------------------------------------------------------------------
# Plan: the registered session list
# ----------------------------------------------------------------------------------------------

def infer_provider(model_id: str) -> str:
    """Provider from a model id prefix (smoke substitutes only)."""
    for prefix, prov in (("claude", "anthropic"), ("gpt", "openai"), ("o1", "openai"), ("o3", "openai"), ("o4", "openai"),
                         ("gemini", "google"), ("grok", "xai")):
        if model_id.startswith(prefix):
            return prov
    raise SystemExit(f"cannot infer the provider of substitute model id {model_id}")


def provider_filter(a) -> Optional[set]:
    """Providers whose triples this `precompute` invocation processes (None = every provider).  Refused on any other
    command: register and run need the complete precompute."""
    if not (a.skip_providers or a.only_providers):
        return None
    if a.cmd != "precompute":
        raise SystemExit("--skip-providers/--only-providers apply to `precompute` only; register and run need the complete precompute")
    skip = set(a.skip_providers.split(",")) if a.skip_providers else set()
    only = set(a.only_providers.split(",")) if a.only_providers else set(panel.DEVELOPERS)
    unknown = (skip | only) - set(panel.DEVELOPERS)
    if unknown:
        raise SystemExit(f"unknown providers {sorted(unknown)}; known: {panel.DEVELOPERS}")
    return only - skip


def frozen_cells() -> dict[str, int]:
    fs = json.loads((PREREG / "frozen_sizes.json").read_text())
    return dict(fs["sessions_per_designer_confirmatory"])


def parse_cells(spec: Optional[str]) -> dict[str, int]:
    """'sham:blinded:5,none:blinded:5' -> {'sham_blinded': 5, ...}; None -> frozen sizes."""
    if not spec:
        return frozen_cells()
    out = {}
    for part in spec.split(","):
        arm, ident, n = part.split(":")
        out[f"{arm}_{ident}"] = int(n)
    return out


def split_cell(cell: str) -> tuple[str, str]:
    arm, ident = cell.rsplit("_", 1)
    return arm, ident


def build_plan(designers: list[str], cells: dict[str, int], pool_name: str) -> list[dict]:
    """Interleaved order: replicate-major, then arm cell, then designer; a fixed-seed shuffle within each replicate
    block so that neither designer nor arm order is systematic.  Concurrency then keeps many arms in flight at once."""
    import numpy as np
    rng = np.random.default_rng(MASTER_SEED)
    max_rep = max(cells.values())
    plan = []
    for rep in range(max_rep):
        block = []
        for cell, n in cells.items():
            if rep >= n:
                continue
            arm, ident = split_cell(cell)
            for d in designers:
                block.append({"session_id": f"T1_{pool_name}_{d}_{arm}_{ident}_r{rep}", "designer": d, "info_arm": arm,
                              "identity_arm": ident, "replicate": rep})
        perm = rng.permutation(len(block))
        plan += [block[i] for i in perm]
    return plan


def exception_row(cfg, exc: BaseException, pool: dict, corr: dict, ref: dict, sdir: Path, wall_s: float) -> dict:
    """benchmark.json for a session whose writer raised: the full ARTEFACT_SCHEMA section 2 field set (an empty benchmark)
    from the interface's own exporter, so every analysis can index it like any other invalid row."""
    from metabench.designer import designer_spec_for
    from metabench.interface import T1Interface
    spec = designer_spec_for(cfg.designer)
    extra = {"status": f"exception:{type(exc).__name__}", "n_llm_calls": 0, "designer_model_id": spec.model_id, "designer_effort": spec.effort,
             "est_cost_usd": 0.0, "wall_s": round(wall_s, 1)}
    return T1Interface(cfg, pool, corr, sdir, reference=ref).export(ref, extra)


def make_cfg(row: dict, ref: dict, pool_name: str, n_items: int, k_rounds: int, samples: int, suffix: str = ""):
    from metabench.arms import make_session_config
    seed = session_seed(row["designer"], row["info_arm"], row["identity_arm"], row["replicate"], suffix)
    sid = row["session_id"] + (f"_{suffix}" if suffix else "")
    return make_session_config(sid, row["designer"], row["info_arm"], row["identity_arm"], row["replicate"], seed, ref,
                               k_rounds=k_rounds, n_items_required=n_items, samples_per_item=samples, pool_name=pool_name,
                               pool_description=pool_description_for(pool_name), with_monitors=True)


# ----------------------------------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------------------------------

class SessionSlot:
    """`async with` one concurrency slot that can be given back early, at most once: with a bounded live re-score the
    session frees its slot when the designer conversation ends, while its outstanding panel calls drain."""

    def __init__(self, sem: asyncio.Semaphore):
        self.sem = sem
        self.held = False

    async def __aenter__(self) -> "SessionSlot":
        await self.sem.acquire()
        self.held = True
        return self

    def release(self) -> None:
        if self.held:
            self.held = False
            self.sem.release()

    async def __aexit__(self, *exc) -> None:
        self.release()


class Runner:
    def __init__(self, a):
        self.a = a
        panel.set_active("confirmatory")
        self.pool_path = Path(a.pool)
        self.pool_name = a.pool_name
        panel.set_pool(self.pool_name)      # evaluee output cap for the precompute and the in-session re-score alike
        self.work = Path(a.work_dir) if a.work_dir else Path("/dev/shm") / f"metabench_{a.pool_name}"
        self.designers = a.designers.split(",") if a.designers else panel.designer_keys()
        for d in self.designers:
            assert d in panel.DISPLAYED_KEYS, f"designer {d} is not a displayed panel key"
        self.cells = parse_cells(a.cells)
        self.providers = provider_filter(a)
        self.substitutes = dict(kv.split("=") for kv in a.substitute.split(",")) if a.substitute else {}
        if self.substitutes:
            if self.cells == frozen_cells():
                raise SystemExit("--substitute is for throwaway/smoke plans only; refusing with the frozen session cells")
            from metabench.llm import ModelSpec
            for i, spec in enumerate(panel.PANEL):
                if spec.key in self.substitutes:
                    mid = self.substitutes[spec.key]
                    panel.PANEL[i] = ModelSpec(spec.key, infer_provider(mid), mid, spec.effort, spec.max_tokens, spec.family, spec.note + " [SUBSTITUTED for smoke]")
        self.n_items = a.n_items
        self.k_rounds = a.k_rounds
        self.samples = a.samples
        self.models = panel.all_panel_keys()
        self.sealer = Sealer(sealed_dir=Path(a.sealed_dir) if a.sealed_dir else SEALED)
        self.prereg = Path(a.prereg_dir) if a.prereg_dir else PREREG
        self.health_dir = Path(a.health_dir) if a.health_dir else HEALTH_DIR
        self.frozen_path = Path(a.frozen_code) if a.frozen_code else None
        self.live_wait_s = live_wait_option(a.live_rescore_wait_s)
        self.live_outstanding: dict[str, set] = {}   # session id -> that session's live re-score calls still running
        self.reg_path = self.prereg / (a.registration or f"confirmatory_hashes_{self.pool_name}.json")
        self.rep_path = self.prereg / (a.replacements or f"confirmatory_replacements_{self.pool_name}.json")
        self.llm = None
        self.llm_factory = self.make_llm     # one fresh client set per command: asyncio locks/semaphores bind to one loop
        self.pool = None
        self.corr = None
        self.ref = None

    # -- helpers --------------------------------------------------------------------------------
    def say(self, msg: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    def check_tmpfs(self) -> None:
        self.work.mkdir(parents=True, exist_ok=True, mode=0o700)
        r = subprocess.run(["df", "--output=fstype", str(self.work)], capture_output=True, text=True)
        fstype = r.stdout.strip().splitlines()[-1].strip() if r.returncode == 0 else "?"
        if fstype != "tmpfs" and not self.a.allow_non_tmpfs:
            raise SystemExit(f"working directory {self.work} is on {fstype}, not tmpfs; refusing (use --allow-non-tmpfs only for offline tests)")

    def load_pool(self) -> None:
        self.pool = load_pool(self.pool_path)
        self.pool_sha = sha256_file(self.pool_path)

    def precompute_path(self) -> Path:
        return self.work / "precompute" / f"{self.pool_name}.jsonl"

    def load_correctness(self) -> None:
        from metabench.panel import load_correctness
        p = self.precompute_path()
        if not p.exists():
            raise SystemExit(f"precompute missing in {p}; run `precompute` first (in the same tmpfs working directory)")
        self.corr = load_correctness(p)
        n_expected = len(self.pool) * self.samples
        cover = {m: sum(len(self.corr.get((i, m), [])) for i in self.pool) for m in self.models}
        short = {m: n for m, n in cover.items() if n < 0.98 * n_expected}
        if short and not self.a.allow_partial_precompute:
            raise SystemExit(f"precompute incomplete for {sorted(short)} (expected {n_expected} per model); refusing")
        self.ref = reference_scores(list(self.pool), self.models, self.corr)
        bad = [m for m in self.models if not (self.ref[m] == self.ref[m])]
        if bad:
            raise SystemExit(f"reference score NaN for {bad}")
        self.cover = cover

    def make_llm(self) -> LLM:
        load_keys_from_env_file()
        # the per-call log stays inside the working directory (it carries tags with session ids and costs, no content)
        # xai 64: the xAI tail (BUILD2_REPORT section 5) bounds every pool's precompute wall; decision 2026-10-25 10:58 UTC
        return LLM(**{f"{p}_concurrency": n for p, n in llm_concurrency().items()}, log_path=str(self.work / "llm_calls.jsonl"))

    # -- precompute -----------------------------------------------------------------------------
    def cmd_precompute(self) -> None:
        from metabench.panel import precompute
        self.check_tmpfs(); self.load_pool()
        self.llm = self.llm_factory()
        out = self.precompute_path(); out.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        asyncio.run(precompute(self.pool, panel.PANEL, self.samples, out, self.llm, concurrency=self.a.panel_concurrency,
                               max_tokens=panel.evaluee_max_tokens(self.pool_name), providers=self.providers))
        self.say(f"precompute done in {time.time()-t0:.0f}s; api errors {self.llm.totals['errors']}"
                 + (f"; providers {sorted(self.providers)}" if self.providers is not None else ""))
        auth = {k: v for k, v in getattr(self.llm, "auth_failures", {}).items() if v}
        if auth:
            self.say(f"precompute auth failures (calls refused on provider authentication, not retried): {json.dumps(auth, sort_keys=True)}")
        if out.exists():   # error rows remaining = triples whose latest row is an error; a further precompute retries them
            self.say(f"precompute error rows remaining by provider: {json.dumps(panel.error_counts_by_provider(out, panel.PANEL), sort_keys=True)}")
        self.sealer.check_keyring()
        self.sealer.seal(out, f"precompute/{self.pool_name}.jsonl")
        self.say("precompute sealed")

    # -- register -------------------------------------------------------------------------------
    def registration_payload(self, cfgs: list) -> dict:
        ok, rep = __import__("scripts_freeze").verify(ROOT, self.frozen_path)
        return {"written_at": utc(), "master_seed": MASTER_SEED, "pool_name": self.pool_name, "pool_sha256": self.pool_sha,
                "panel_correctness_sha256": sha256_file(self.precompute_path()), "samples_per_item": self.samples,
                "k_rounds": self.k_rounds, "n_items": self.n_items, "cells": self.cells, "designers": self.designers,
                "live_rescore_wait_s": self.live_wait_s,
                "frozen_code_sha256": rep.get("combined_sha256"), "frozen_code_verified": ok,
                "panel": [{"key": s.key, "provider": s.provider, "model_id": s.model_id, "effort": s.effort} for s in panel.PANEL],
                "sessions": [{"session_id": c.session_id, "designer": c.designer, "info_arm": c.info_arm, "identity_arm": c.identity_arm,
                              "replicate": c.replicate, "config_hash": c.config_hash} for c in cfgs]}

    def cmd_register(self) -> None:
        self.check_tmpfs(); self.load_pool(); self.load_correctness()
        plan = build_plan(self.designers, self.cells, self.pool_name)
        cfgs = [make_cfg(r, self.ref, self.pool_name, self.n_items, self.k_rounds, self.samples) for r in plan]
        reg = self.registration_payload(cfgs)
        reg["sessions_sha256"] = hashlib.sha256(json.dumps(reg["sessions"], sort_keys=True).encode()).hexdigest()
        if self.reg_path.exists() and not self.a.force:
            old = json.loads(self.reg_path.read_text())
            if old.get("sessions_sha256") != reg["sessions_sha256"]:
                raise SystemExit(f"{self.reg_path} exists and its sessions do not match the recomputed configs; refusing to overwrite (use --force to re-register, which is a logged deviation)")
            if old.get("live_rescore_wait_s") != self.live_wait_s:
                raise SystemExit(f"{self.reg_path} exists with live_rescore_wait_s={old.get('live_rescore_wait_s')}, not {self.live_wait_s}; refusing to overwrite (use --force to re-register, which is a logged deviation)")
            self.say(f"registration unchanged: {len(cfgs)} sessions")
        else:
            self.reg_path.write_text(json.dumps(reg, indent=1))
            self.say(f"registered {len(cfgs)} sessions -> {self.reg_path.name} sessions_sha256={reg['sessions_sha256'][:16]}")
        full = {"registration": reg, "configs": {c.session_id: json.loads(c.to_json()) for c in cfgs},
                "reference_scores": {k: round(v, 6) for k, v in self.ref.items()}, "coverage": self.cover}
        fp = self.work / "registration_full.json"
        fp.write_text(json.dumps(full, indent=1))
        self.sealer.check_keyring()
        self.sealer.seal(fp, "registration_full.json")
        self.say("full registration sealed")

    # -- run ------------------------------------------------------------------------------------
    def cmd_run(self) -> None:
        import scripts_freeze
        ok, rep = scripts_freeze.verify(ROOT, self.frozen_path)
        if not ok:
            raise SystemExit(f"frozen code check failed: {json.dumps({k: rep.get(k) for k in ('error', 'mismatched', 'missing', 'unfrozen')})}; refusing to start")
        self.code_hash = rep["combined_sha256"]
        self.check_tmpfs(); self.load_pool(); self.load_correctness()
        self.sealer.check_keyring()
        if not self.reg_path.exists():
            raise SystemExit(f"{self.reg_path} missing; run `register` first")
        reg = json.loads(self.reg_path.read_text())
        registered = {s["session_id"]: s["config_hash"] for s in reg["sessions"]}
        if reg.get("pool_sha256") != self.pool_sha:
            raise SystemExit("pool file hash differs from the registered pool; refusing")
        if reg.get("frozen_code_sha256") != self.code_hash:
            raise SystemExit("the registration was written under a different frozen code hash; re-freeze and re-register (logged deviation) before running")
        if reg.get("live_rescore_wait_s") != self.live_wait_s:   # absent in registrations written before Builder 8 = blocking
            raise SystemExit(f"--live-rescore-wait-s {self.live_wait_s} differs from the registered value {reg.get('live_rescore_wait_s')}; refusing")
        plan = build_plan(self.designers, self.cells, self.pool_name)
        cfgs = [make_cfg(r, self.ref, self.pool_name, self.n_items, self.k_rounds, self.samples) for r in plan]
        bad = [c.session_id for c in cfgs if registered.get(c.session_id) != c.config_hash]
        if bad or len(cfgs) != len(registered):
            raise SystemExit(f"{len(bad)} session configs do not match their registered commitments (or count differs); refusing")
        self.llm = self.llm_factory()
        sessions_dir = self.work / "sessions"; sessions_dir.mkdir(exist_ok=True)
        (self.work / "monitors").mkdir(exist_ok=True); (self.work / "results").mkdir(exist_ok=True)
        self.write_reference_outcomes()
        manifest = {"run_id": f"{self.pool_name}-{utc()}", "started_at": utc(), "frozen_code_sha256": self.code_hash,
                    "registration_sha256": reg["sessions_sha256"], "pool_sha256": self.pool_sha, "n_registered": len(cfgs),
                    "designers": self.designers, "cells": self.cells, "concurrency": self.a.concurrency,
                    "live_rescore_wait_s": self.live_wait_s,
                    "panel": {"name": "confirmatory", "keys": [s.key for s in panel.PANEL], "displayed_keys": list(panel.DISPLAYED_KEYS),
                              "placebo_keys": list(panel.PLACEBO_KEYS), "heldout_keys": list(panel.HELDOUT_KEYS)},
                    "substitutes": self.substitutes}
        (self.work / "run_manifest.json").write_text(json.dumps(manifest, indent=1))
        self.say(f"run start: {len(cfgs)} registered sessions, concurrency {self.a.concurrency}, code {self.code_hash[:12]}")
        self.registered_hash_ok = {}
        rows = asyncio.run(self.run_registered_then_replacements(cfgs, plan))   # ONE event loop: provider clients are loop-bound
        self.finish(rows, manifest)

    async def drain_live(self, sids: Optional[list[str]] = None) -> int:
        """Wait until every live re-score call of the given sessions (default: all) has returned or exhausted its retries;
        returns the number waited on.  run_session drains its own calls before writing its outputs; this is the runner's
        backstop before a session's files are sealed and before finish()."""
        n = 0
        for sid in [s for s in (sids if sids is not None else list(self.live_outstanding)) if s in self.live_outstanding]:
            tasks = self.live_outstanding.pop(sid)
            while tasks:
                pending = list(tasks)
                n += len(pending)
                await asyncio.gather(*pending, return_exceptions=True)
        return n

    async def run_registered_then_replacements(self, cfgs: list, plan: list[dict]) -> list[dict]:
        t0 = time.time()
        rows = await self.run_many(cfgs, attempt=1)
        # -- replacement rule: each invalid session is replaced exactly once with a new seed from the same generator --
        invalid = [c for c, r in zip(cfgs, rows) if not r.get("valid")]
        self.say(f"registered list complete in {time.time()-t0:.0f}s: {sum(1 for r in rows if r.get('valid'))}/{len(rows)} valid; {len(invalid)} to replace once")
        if invalid:
            by_id = {r["session_id"]: r for r in plan}
            rep_cfgs = [make_cfg(by_id[c.session_id], self.ref, self.pool_name, self.n_items, self.k_rounds, self.samples, suffix="rep1") for c in invalid]
            repl = {"written_at": utc(), "pool_name": self.pool_name,
                    "replacements": [{"original": c.session_id, "replacement": rc.session_id, "designer": rc.designer, "info_arm": rc.info_arm,
                                      "identity_arm": rc.identity_arm, "reason": r.get("status"), "config_hash": rc.config_hash}
                                     for c, rc, r in zip(invalid, rep_cfgs, [x for x in rows if not x.get("valid")])]}
            self.rep_path.write_text(json.dumps(repl, indent=1))
            for rc in rep_cfgs:
                self.registered_hash_ok[rc.session_id] = True
            rows += await self.run_many(rep_cfgs, attempt=2, replacement_of={rc.session_id: c.session_id for c, rc in zip(invalid, rep_cfgs)})
        n = await self.drain_live()
        if self.live_wait_s is not None:
            self.say(f"live re-score: {n} calls still outstanding at the end of the run were drained before finish")
        return rows

    def write_reference_outcomes(self) -> None:
        p = self.work / "results" / "reference_item_outcomes.jsonl"
        with open(p, "w") as f:
            for i in self.pool:
                for m in self.models:
                    v = self.corr.get((i, m), [])
                    f.write(json.dumps({"session_id": "REFERENCE", "item_id": i, "model_key": m, "n_correct": int(sum(v)), "n_samples": len(v)}) + "\n")
        shutil.copy(p, self.work / "reference_item_outcomes.jsonl")

    async def run_many(self, cfgs: list, attempt: int, replacement_of: Optional[dict] = None) -> list[dict]:
        from metabench.designer import run_session
        from metabench.monitors import run_monitor_pair
        sem = asyncio.Semaphore(self.a.concurrency)
        lock = asyncio.Lock()
        sessions_dir = self.work / "sessions"
        results = self.work / "results"
        replacement_of = replacement_of or {}

        async def one(cfg):
            async with SessionSlot(sem) as slot:
                sid = cfg.session_id
                sdir = sessions_dir / sid
                bpath = sdir / "benchmark.json"
                if bpath.exists():   # resume: a completed session in the working directory is not re-run
                    row = json.loads(bpath.read_text())
                    self.say(f"skip  {sid} (already in working dir) valid={row.get('valid')}")
                    return row
                started = utc(); t0 = time.time()
                self.say(f"start {sid}")
                err0 = self.llm.totals["errors"]
                try:
                    row = await run_session(cfg, self.llm, self.pool, self.corr, self.ref, sessions_dir, probes=True,
                                            live_wait_s=self.live_wait_s, live_tracker=self.live_outstanding,
                                            on_designer_done=slot.release if self.live_wait_s is not None else None)
                    exit_code = 0 if row.get("valid") else 1
                except Exception as e:  # noqa: BLE001 - the session writer failed before producing a row
                    row = exception_row(cfg, e, self.pool, self.corr, self.ref, sdir, time.time() - t0)
                    exit_code = 2
                await self.drain_live([sid])
                tag_err = self.llm.by_tag.get(f"designer:{sid}", {}).get("errors", 0)
                row.update({"api_errors": int(tag_err), "started_at": started, "ended_at": utc(), "replacement_of": replacement_of.get(sid),
                            "pool_name": self.pool_name})
                sdir.mkdir(parents=True, exist_ok=True)
                bpath.write_text(json.dumps(row, indent=1))
                self.registered_hash_ok[sid] = (row.get("config_hash") == cfg.config_hash)
                # monitors (never fed back; failures do not fail the session)
                if row.get("status") == "ok" and row.get("items"):
                    mon = await run_monitor_pair(self.llm, row, sdir, self.pool, cfg.monitor_developers)
                    (self.work / "monitors" / f"{sid}.json").write_text(json.dumps(mon, indent=1))
                    async with lock:
                        with open(results / "monitors.jsonl", "a") as f:
                            f.write(json.dumps(mon) + "\n")
                async with lock:
                    with open(results / "benchmarks.jsonl", "a") as f:
                        f.write(json.dumps(row) + "\n")
                    io = sdir / "item_outcomes.jsonl"
                    if io.exists():
                        with open(results / "item_outcomes.jsonl", "a") as f:
                            f.write(io.read_text())
                    log = {"session_id": sid, "designer": cfg.designer, "info_arm": cfg.info_arm, "identity_arm": cfg.identity_arm, "attempt": attempt,
                           "replacement_of": replacement_of.get(sid), "status": row.get("status"), "valid": bool(row.get("valid")), "n_items": row.get("n_items"),
                           "api_errors": int(tag_err), "n_llm_calls": row.get("n_llm_calls"), "wall_s": row.get("wall_s"), "started_at": started,
                           "ended_at": row["ended_at"], "exit_code": exit_code}
                    with open(results / "session_log.jsonl", "a") as f:
                        f.write(json.dumps(log) + "\n")
                    # seal this session's files right away so a crash loses as little as possible
                    for p in sorted(sdir.iterdir()):
                        self.sealer.seal(p, f"sessions/{sid}/{p.name}")
                    mp = self.work / "monitors" / f"{sid}.json"
                    if mp.exists():
                        self.sealer.seal(mp, f"monitors/{sid}.json")
                self.say(f"done  {sid} exit={exit_code} valid={row.get('valid')} status={row.get('status')} api_errors={tag_err} calls={row.get('n_llm_calls')} wall={row.get('wall_s')}s")
                return row

        return list(await asyncio.gather(*(one(c) for c in cfgs)))

    # -- finish: health view, endpoints, seal everything, wipe --------------------------------------
    def finish(self, rows: list[dict], manifest: dict) -> None:
        import scripts_health_view as HV
        manifest["ended_at"] = utc()
        manifest["n_rows"] = len(rows)
        manifest["n_valid"] = sum(1 for r in rows if r.get("valid"))
        manifest["api_errors_total"] = int(self.llm.totals["errors"]) if self.llm else 0
        (self.work / "run_manifest.json").write_text(json.dumps(manifest, indent=1))
        # health view (plaintext copy outside the sealed tree; secrets sealed only)
        self.health_dir.mkdir(exist_ok=True, parents=True)
        (self.work / "health").mkdir(exist_ok=True)
        decoys = self.pilot_decoy_sources()
        reg = json.loads(self.reg_path.read_text())
        view_path = self.health_dir / f"health_view_{self.pool_name}.jsonl"
        summary = HV.build_health_view(self.work, view_path, self.work / "health" / "health_secret.json",
                                       registered=reg, decoys_per_designer=DECOYS_PER_DESIGNER if len(self.designers) >= 12 else 1,
                                       decoy_sources=decoys, code_hash_ok=True, hash_ok_by_session=self.registered_hash_ok)
        shutil.copy(view_path, self.work / "health" / "health_view.jsonl")
        self.say(f"health view written: {json.dumps(summary)}")
        # endpoints from every frozen analysis implementation present (output sealed, never printed)
        self.run_analyses()
        self.run_contamination()
        n = self.sealer.seal_tree(self.work)
        self.say(f"sealed {n} remaining files; manifest lists {len(self.sealer.manifest['files'])} files")
        if not self.a.keep_work:
            shutil.rmtree(self.work)
            self.say("working directory wiped")
        else:
            self.say("working directory kept (--keep-work)")

    def analysis_commands(self) -> list[tuple[str, list[str]]]:
        """(name, argv) per implementation.  metabench.analysis reads the results/ directory (its three jsonl files); the
        analysis_impls read the WORK root, the ARTEFACT_SCHEMA section 1 tree (results/, sessions/, registration_full.json,
        run_manifest.json below it).  The factual pool's finish step passed WORK/results to all three (BUILD4_REPORT)."""
        impls = [("A_metabench_analysis", [sys.executable, "-m", "metabench.analysis"], self.work / "results")]
        for d in sorted((ROOT / "analysis_impls").glob("*/run.py")) if (ROOT / "analysis_impls").exists() else []:
            impls.append((d.parent.name, [sys.executable, str(d)], self.work))
        return [(name, cmd + ["--results", str(results), "--out", str(self.work / "endpoints" / name),
                              "--n-perm", str(self.a.n_perm), "--n-boot", str(self.a.n_boot)]) for name, cmd, results in impls]

    def run_analyses(self) -> None:
        def limit_address_space():
            if self.a.analysis_memory_mib > 0:
                cap = self.a.analysis_memory_mib * 1024 * 1024
                _, hard = resource.getrlimit(resource.RLIMIT_AS)
                if hard != resource.RLIM_INFINITY:
                    cap = min(cap, hard)
                resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
        for name, cmd in self.analysis_commands():
            out = self.work / "endpoints" / name
            out.mkdir(parents=True, exist_ok=True)
            t0 = time.time()
            try:
                r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=self.a.analysis_timeout, preexec_fn=limit_address_space)
                rc, so, se = r.returncode, r.stdout, r.stderr
            except subprocess.TimeoutExpired as e:   # a hung implementation must not block sealing the raw artefacts
                rc, so, se = "timeout", e.stdout or "", e.stderr or ""
                if isinstance(so, bytes): so = so.decode(errors="replace")
                if isinstance(se, bytes): se = se.decode(errors="replace")
            (out / "log.txt").write_text(f"rc={rc}\n--- stdout ---\n{so}\n--- stderr ---\n{se}")
            self.say(f"analysis {name}: rc={rc} in {time.time()-t0:.0f}s")

    def run_contamination(self) -> None:
        """ConStat-style contamination check on the reference item outcomes (docs/CONTAMINATION_SPEC.md); output sealed
        with the endpoints, stdout carries only rc and timing."""
        script = ROOT / "scripts_contamination.py"
        if not script.exists():
            self.say("contamination: scripts_contamination.py absent; skipped")
            return
        out = self.work / "endpoints" / "contamination"
        out.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        r = subprocess.run([sys.executable, str(script), "--reference", str(self.work / "results" / "reference_item_outcomes.jsonl"),
                            "--pool", str(self.pool_path), "--out", str(out), "--n-boot", str(self.a.n_boot)],
                           cwd=ROOT, capture_output=True, text=True)
        (out / "log.txt").write_text(f"rc={r.returncode}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}")
        self.say(f"contamination: rc={r.returncode} in {time.time()-t0:.0f}s")

    def pilot_decoy_sources(self) -> list[dict]:
        """Structural fields of pilot sessions (never scores), used to replay decoys in the health view."""
        src = Path(self.a.pilot_sessions_dir) if self.a.pilot_sessions_dir else ROOT / "sessions"
        out = []
        if not src.exists():
            return out
        for d in sorted(src.iterdir()):
            b = d / "benchmark.json"
            if not b.exists():
                continue
            try:
                r = json.loads(b.read_text())
            except json.JSONDecodeError:
                continue
            acts = [json.loads(l) for l in open(d / "actions.jsonl")] if (d / "actions.jsonl").exists() else []
            ok = [not str(a.get("result_summary", "")).startswith("ERROR") for a in acts]
            n_io = sum(1 for _ in open(d / "item_outcomes.jsonl")) if (d / "item_outcomes.jsonl").exists() else 0
            out.append({"status": r.get("status"), "valid": bool(r.get("valid")), "n_items": r.get("n_items"), "n_llm_calls": r.get("n_llm_calls"),
                        "api_errors": 0, "wall_s": r.get("wall_s"), "n_score_requests": r.get("n_score_requests"), "n_edits": r.get("n_edits"),
                        "files": {"config": (d / "config.json").exists(), "actions": (d / "actions.jsonl").exists(), "transcript": (d / "transcript.jsonl").exists(),
                                  "scores_views": (d / "scores_views.jsonl").exists(), "benchmark": True, "item_outcomes": (d / "item_outcomes.jsonl").exists(),
                                  "probes": (d / "probes.json").exists(), "monitors": 2},
                        "parse": {"actions_ok_rate": (sum(ok) / len(ok)) if ok else 0.0, "monitor_json_rate": 1.0, "item_outcomes_rows": n_io}})
        return out

    def cmd_wipe(self) -> None:
        if self.work.exists():
            shutil.rmtree(self.work)
        self.say("working directory wiped")


def live_wait_option(v: Optional[float]) -> Optional[float]:
    """--live-rescore-wait-s: None (blocking live re-score) or a finite number of seconds >= 0."""
    if v is None:
        return None
    if not (0.0 <= v < float("inf")):
        raise SystemExit(f"--live-rescore-wait-s must be a finite number of seconds >= 0, not {v}")
    return float(v)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["precompute", "register", "run", "all", "wipe"])
    ap.add_argument("--pool", required=True)
    ap.add_argument("--pool-name", required=True)
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--n-items", type=int, default=100)
    ap.add_argument("--k-rounds", type=int, default=K_ROUNDS)
    ap.add_argument("--designers", default=None, help="comma-separated panel keys (default: the 12 confirmatory designers)")
    ap.add_argument("--cells", default=None, help="arm:identity:n,... (default: frozen sizes)")
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--panel-concurrency", type=int, default=96)
    ap.add_argument("--work-dir", default=None)
    ap.add_argument("--sealed-dir", default=None)
    ap.add_argument("--registration", default=None)
    ap.add_argument("--replacements", default=None)
    ap.add_argument("--n-perm", type=int, default=10000)
    ap.add_argument("--n-boot", type=int, default=10000)
    ap.add_argument("--analysis-timeout", type=float, default=4 * 3600,
                    help="seconds per analysis implementation at finish (BUILD4_REPORT: measured full-size runtimes)")
    ap.add_argument("--analysis-memory-mib", type=int, default=20480,
                    help="RLIMIT_AS per analysis process (0 = none); a runaway analysis then fails with MemoryError instead of the box's "
                         "memory manager terminating it (the factual finish step, 2026-10-25 21:34 UTC)")
    ap.add_argument("--prereg-dir", default=None)
    ap.add_argument("--health-dir", default=None)
    ap.add_argument("--frozen-code", default=None)
    ap.add_argument("--pilot-sessions-dir", default=None, help="pilot sessions used as decoy structure (default run/sessions)")
    ap.add_argument("--live-rescore-wait-s", type=float, default=None,
                    help="register/run: seconds edit_item waits for the live re-score of an edited item (default: until every panel "
                         "call returns); late answers show as pending and are drained before outputs are written. Registered per pool")
    ap.add_argument("--keep-work", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--allow-non-tmpfs", action="store_true")
    ap.add_argument("--allow-partial-precompute", action="store_true")
    ap.add_argument("--substitute", default=None, help="smoke only: key=model_id,... swaps provider model ids for this process")
    ap.add_argument("--skip-providers", default=None, help="precompute only: comma-separated providers whose triples are left for a later invocation")
    ap.add_argument("--only-providers", default=None, help="precompute only: comma-separated providers whose triples are processed in this invocation")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    r = Runner(a)
    if a.cmd == "precompute":
        r.cmd_precompute()
    elif a.cmd == "register":
        r.cmd_register()
    elif a.cmd == "run":
        r.cmd_run()
    elif a.cmd == "all":
        r.cmd_precompute(); r.cmd_register(); r.cmd_run()
    else:
        r.cmd_wipe()


if __name__ == "__main__":
    main()
