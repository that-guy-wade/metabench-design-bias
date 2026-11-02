"""Read a runner working directory in the docs/ARTEFACT_SCHEMA.md layout (DECISIONS D1, D2)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

LEADER_ARMS = ("sham", "inverted", "narrative", "instructed", "true_named", "true_blinded")


@dataclass
class Bench:
    session_id: str
    designer: str
    info_arm: str
    identity_arm: str
    valid: bool
    status: str
    displayed_keys: list[str]
    panel_keys: list[str]
    displayed_order: Optional[list[str]]
    displayed_leader: Optional[str]
    target_model: Optional[str]
    produced_scores: dict[str, float]
    reference_scores: dict[str, float]
    named: bool
    n_score_requests: int
    designer_model_id: str
    replacement_of: Optional[str]
    false_identity: Optional[str] = None
    views: list[dict] = field(default_factory=list)

    @property
    def cell(self) -> str:
        return f"{self.info_arm}/{self.identity_arm}"

    @property
    def target(self) -> Optional[str]:
        """Target_{b,m} of PREREGISTRATION section 8: the instructed target, else the displayed leader (D19)."""
        if self.info_arm == "instructed" and self.target_model:
            return self.target_model
        return self.displayed_leader if self.info_arm in LEADER_ARMS else None


@dataclass
class Dataset:
    root: Path
    benches: list[Bench]
    designer_keys: list[str]           # the 12 displayed designer keys (D3)
    panel_keys: list[str]              # all 17 keys with produced scores
    warnings: list[str]

    @property
    def valid(self) -> list[Bench]:
        return [b for b in self.benches if b.valid]

    def item_outcomes(self):
        """Yield (session_id, item_id, model_key, n_correct, n_samples) for every valid session (D18)."""
        valid_ids = {b.session_id for b in self.valid}
        sess_dir = self.root / "sessions"
        if sess_dir.is_dir():
            for sid in sorted(valid_ids):
                p = sess_dir / sid / "item_outcomes.jsonl"
                if p.exists():
                    yield from _iter_outcomes(p, sid)
        else:
            yield from (r for r in _iter_outcomes(self.root / "results" / "item_outcomes.jsonl") if r[0] in valid_ids)

    def reference_outcomes(self):
        for cand in (self.root / "reference_item_outcomes.jsonl", self.root / "results" / "reference_item_outcomes.jsonl"):
            if cand.exists():
                yield from _iter_outcomes(cand)
                return
        raise FileNotFoundError("reference_item_outcomes.jsonl not found")


def _iter_outcomes(path: Path, only_sid: Optional[str] = None):
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if only_sid is not None and r["session_id"] != only_sid:
                continue
            yield r["session_id"], r["item_id"], r["model_key"], int(r["n_correct"]), int(r["n_samples"])


def _read_jsonl(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def _bench_from_json(j: dict) -> Bench:
    return Bench(
        session_id=j["session_id"], designer=j["designer"], info_arm=j["info_arm"], identity_arm=j["identity_arm"],
        valid=bool(j["valid"]), status=j.get("status", ""), displayed_keys=list(j["displayed_keys"]),
        panel_keys=list(j["panel_keys"]), displayed_order=j.get("displayed_order"), displayed_leader=j.get("displayed_leader"),
        target_model=j.get("target_model"), produced_scores={k: float(v) for k, v in j["produced_scores"].items()},
        reference_scores={k: float(v) for k, v in j["reference_scores"].items()}, named=bool(j.get("named", False)),
        n_score_requests=int(j.get("n_score_requests", 0)), designer_model_id=str(j.get("designer_model_id", "")),
        replacement_of=j.get("replacement_of"),
    )


def load(root: str | Path) -> Dataset:
    root = Path(root)
    warnings: list[str] = []
    benches: list[Bench] = []
    sess_dir = root / "sessions"
    if sess_dir.is_dir() and any(sess_dir.iterdir()):
        for d in sorted(sess_dir.iterdir()):
            bj = d / "benchmark.json"
            if not bj.exists():
                warnings.append(f"no benchmark.json in {d.name}")
                continue
            with open(bj) as f:
                b = _bench_from_json(json.load(f))
            sv = d / "scores_views.jsonl"
            if sv.exists():
                b.views = _read_jsonl(sv)
            benches.append(b)
    else:
        warnings.append("sessions/ tree absent; read results/benchmarks.jsonl (no trajectories)")
        benches = [_bench_from_json(j) for j in _read_jsonl(root / "results" / "benchmarks.jsonl")]
    reg = root / "registration_full.json"
    if reg.exists():
        with open(reg) as f:
            registration = json.load(f)
        registration = registration.get("configs", registration)     # runner: {"registration", "configs": {sid: cfg}, ...}
        for b in benches:
            cfg = registration.get(b.session_id)
            if cfg is not None:
                b.false_identity = cfg.get("false_identity")
    else:
        warnings.append("registration_full.json absent; false identities unknown (S2 false-arm told-model gain skipped)")

    designer_keys: Optional[list[str]] = None
    man = root / "run_manifest.json"
    if man.exists():
        with open(man) as f:
            manifest = json.load(f)
        pan = manifest.get("panel", {})
        dk = pan.get("displayed_keys") if isinstance(pan, dict) else None   # the runner wrote a list of keys before BUILD4
        if dk:
            designer_keys = list(dk)
    if designer_keys is None:
        common = None
        for b in benches:
            s = set(b.displayed_keys)
            common = s if common is None else common & s
        designer_keys = sorted(common or [])
        warnings.append("designer keys taken as the intersection of displayed_keys over sessions")
    panel_keys = sorted({k for b in benches for k in b.panel_keys})
    return Dataset(root=root, benches=benches, designer_keys=designer_keys, panel_keys=panel_keys, warnings=warnings)
