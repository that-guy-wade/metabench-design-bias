"""MetaBench Tier 3: parameterised agentic task templates with programmatic verifiers.

Everything here is pure Python, deterministic given a seed, and needs no network, filesystem or LLM:
three simulated environments (file-system data cleaning, REST-API workflow, constraint scheduling),
ground-truth generators, verifiers with exposed strictness knobs, scripted agents (oracle + three
"style" agents) and the designer-facing `T3Interface`.

The designer never writes verifier code.  It only sets template parameters, the template mix, the
exposed strictness knobs and the budget.  `request_panel_scores` takes an injectable
`run_agent_fn(env, task_text, budget) -> Trajectory`, so the same interface runs real LLM agents (main
study) or scripted agents (tests, designer-free null arm).
"""
from __future__ import annotations

import copy
import fnmatch
import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from random import Random
from typing import Any, Callable, Optional

# =====================================================================================================
# Shared types
# =====================================================================================================

@dataclass
class Budget:
    max_steps: int = 40          # soft cap used by verifiers with require_within_steps
    max_tool_calls: int = 80     # hard cap: calls beyond this return an exhaustion error


@dataclass
class Trajectory:
    steps: list[dict] = field(default_factory=list)   # {"tool", "args", "obs"}
    n_calls: int = 0
    n_transient_errors: int = 0
    final: Any = None

    def add(self, tool: str, args: dict, obs: str):
        self.steps.append({"tool": tool, "args": args, "obs": obs})
        self.n_calls += 1
        if obs.startswith("ERROR 429") or obs.startswith("ERROR: transient"):
            self.n_transient_errors += 1


@dataclass
class VerifyResult:
    passed: bool
    soft: float               # fraction-style partial credit in [0, 1]
    reasons: list[str] = field(default_factory=list)


EXHAUSTED = "ERROR: tool-call budget exhausted"
TRANSIENT = "ERROR: transient tool failure (retry the call)"
RATE_LIMIT = "ERROR 429 rate limited (retry the call)"


class ParamError(ValueError):
    pass


def _check_params(schema: dict, params: dict) -> dict:
    """Validate params against schema; returns the completed params (defaults filled)."""
    out = {}
    for name, spec in schema.items():
        val = params.get(name, spec["default"])
        t = spec["type"]
        if t == "int":
            if not isinstance(val, int) or isinstance(val, bool):
                raise ParamError(f"{name}: expected int, got {val!r}")
            if not (spec["min"] <= val <= spec["max"]):
                raise ParamError(f"{name}={val} outside [{spec['min']}, {spec['max']}]")
        elif t == "float":
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise ParamError(f"{name}: expected number, got {val!r}")
            if not (spec["min"] <= val <= spec["max"]):
                raise ParamError(f"{name}={val} outside [{spec['min']}, {spec['max']}]")
            val = float(val)
        elif t == "bool":
            if not isinstance(val, bool):
                raise ParamError(f"{name}: expected bool, got {val!r}")
        elif t == "subset":
            if not isinstance(val, list) or any(v not in spec["choices"] for v in val):
                raise ParamError(f"{name}: expected subset of {spec['choices']}, got {val!r}")
            val = sorted(set(val))
        out[name] = val
    extra = set(params) - set(schema)
    if extra:
        raise ParamError(f"unknown parameters: {sorted(extra)}")
    return out


class BaseEnv:
    """Common step/budget/transient-error machinery.  Subclasses implement _generate, _tools, _apply."""
    name = "base"
    PARAM_SCHEMA: dict = {}
    TASK_INTRO = ""

    def __init__(self, params: dict, seed: int, budget: Optional[Budget] = None):
        self.params = _check_params(self.PARAM_SCHEMA, params)
        self.seed = seed
        self.budget = budget or Budget()
        self.reset(seed)

    def reset(self, seed: int) -> str:
        self.seed = seed
        self.rng = Random(f"{self.name}:{seed}:gen")
        self.err_rng = Random(f"{self.name}:{seed}:err")
        self.traj = Trajectory()
        self.exhausted = False
        self.task_text = self._generate()
        return self.task_text

    # -- to implement --------------------------------------------------------------------------------
    def _generate(self) -> str: raise NotImplementedError
    def tools(self) -> list[dict]: raise NotImplementedError
    def _apply(self, tool: str, args: dict) -> str: raise NotImplementedError
    def final_state(self) -> dict: raise NotImplementedError
    def expected_state(self) -> dict: raise NotImplementedError
    def verify(self, strictness) -> VerifyResult: raise NotImplementedError
    def preview(self) -> str: raise NotImplementedError

    def _transient_rate(self) -> float:
        return 0.0

    def _is_terminal_tool(self, tool: str) -> bool:
        return False

    def step(self, tool: str, args: dict) -> str:
        if self.exhausted:
            return EXHAUSTED
        if self.traj.n_calls >= self.budget.max_tool_calls:
            self.exhausted = True
            self.traj.add(tool, args, EXHAUSTED)
            return EXHAUSTED
        if not self._is_terminal_tool(tool) and self.err_rng.random() < self._transient_rate():
            obs = self._transient_message()
            self.traj.add(tool, args, obs)
            return obs
        try:
            obs = self._apply(tool, args)
        except Exception as e:  # tool misuse is an observation, not a crash
            obs = f"ERROR: {type(e).__name__}: {e}"
        self.traj.add(tool, args, obs)
        return obs

    def _transient_message(self) -> str:
        return TRANSIENT


# =====================================================================================================
# Family A: mock file-system data cleaning
# =====================================================================================================

US_VARIANTS = ["USA", "U.S.A.", "U.S.", "United States", "United States of America", "America"]
OTHER_COUNTRIES = ["Canada", "Mexico", "United Kingdom", "Germany", "France", "Japan", "Brazil", "India"]
FIRST = ["Alice", "Bob", "Carla", "Dev", "Erin", "Farid", "Gina", "Hugo", "Ines", "Jun", "Kai", "Lena", "Mo", "Nia", "Omar", "Pia"]
LAST = ["Ng", "Patel", "Rossi", "Sato", "Khan", "Diaz", "Weber", "Olsen", "Mbeki", "Costa", "Ivanov", "Baker"]
FS_COLUMNS = ["id", "name", "email", "country", "amount", "signup_date"]


def _normalise_country(v: str) -> str:
    return re.sub(r"[\s\. ]", "", v).lower()


def is_us_variant(value: str) -> bool:
    """Answer-aware detector used by the generator and the oracle (edit distance <= 1 to a variant)."""
    n = _normalise_country(value)
    if n == "us":
        return value.strip() != "US"  # 'US.' or ' us ' still need canonicalising; exact 'US' does not
    targets = [_normalise_country(v) for v in US_VARIANTS]
    for t in targets:
        if n == t or _edit1(n, t):
            return True
    return False


def _edit1(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    s, l = (a, b) if len(a) < len(b) else (b, a)
    for i in range(len(l)):
        if l[:i] + l[i + 1:] == s:
            return True
    return False


def _csv_dump(header: list[str], rows: list[list[str]]) -> str:
    return "\n".join([",".join(header)] + [",".join(r) for r in rows]) + "\n"


def _csv_parse(text: str) -> tuple[list[str], list[list[str]]]:
    lines = [l for l in text.replace("﻿", "").split("\n") if l != ""]
    if not lines:
        return [], []
    header = lines[0].split(",")
    rows = [l.split(",") for l in lines[1:]]
    return header, rows


@dataclass
class FSStrictness:
    tolerate_whitespace: bool = False
    tolerate_column_order: bool = False
    require_no_collateral_edits: bool = True
    require_within_steps: bool = True
    pass_threshold: float = 1.0      # fraction of target records that must be fixed


class FileSystemEnv(BaseEnv):
    name = "fs_clean"
    PARAM_SCHEMA = {
        "n_files":            {"type": "int", "min": 1, "max": 12, "default": 4, "desc": "customer export files under data/"},
        "n_distractor_files": {"type": "int", "min": 0, "max": 8, "default": 2, "desc": "look-alike files that must not be edited"},
        "n_target_records":   {"type": "int", "min": 1, "max": 30, "default": 6, "desc": "records that need the fix"},
        "records_per_file":   {"type": "int", "min": 5, "max": 60, "default": 15, "desc": "rows per file"},
        "noise_types":        {"type": "subset", "choices": ["typo", "format", "encoding"], "default": ["format", "typo"], "desc": "how target values are corrupted"},
        "max_steps":          {"type": "int", "min": 5, "max": 200, "default": 40, "desc": "template-level step cap (min with global budget)"},
        "tool_error_rate":    {"type": "float", "min": 0.0, "max": 0.5, "default": 0.1, "desc": "probability a tool call fails transiently"},
        "hint_level":         {"type": "int", "min": 0, "max": 2, "default": 1, "desc": "0 no location hint, 1 directory named, 2 files listed"},
    }
    STRICTNESS = FSStrictness

    def _transient_rate(self) -> float:
        return self.params["tool_error_rate"]

    def _noise(self, value: str) -> str:
        rng, nt, v = self.rng, self.params["noise_types"], value
        if "format" in nt:
            v = rng.choice([v.lower(), v.upper(), f" {v}", f"{v}  ", v.title(), v])
        if "typo" in nt and rng.random() < 0.6 and len(v.strip()) > 3:
            core = v.strip()
            i = rng.randrange(1, len(core) - 1)
            v = v.replace(core, core[:i] + core[i + 1:], 1)
        if "encoding" in nt and rng.random() < 0.6:
            v = v + " "
        return v

    def _generate(self) -> str:
        p, rng = self.params, self.rng
        self.files: dict[str, str] = {}
        self.target_files = [f"data/customers_{k+1}.csv" for k in range(p["n_files"])]
        self.targets: list[tuple[str, str]] = []  # (path, record id)
        slots = [(f, i) for f in self.target_files for i in range(p["records_per_file"])]
        rng.shuffle(slots)
        chosen = set(slots[: p["n_target_records"]])
        rid = 1000
        for path in self.target_files:
            rows = []
            for i in range(p["records_per_file"]):
                rid += 1
                name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
                email = f"{name.split()[0].lower()}{rid}@example.com"
                if (path, i) in chosen:
                    country = self._noise(rng.choice(US_VARIANTS))
                    self.targets.append((path, str(rid)))
                else:
                    country = rng.choice(OTHER_COUNTRIES + ["US"])
                rows.append([str(rid), name, email, country, f"{rng.randint(10, 999)}.{rng.randint(0, 99):02d}",
                             f"2026-{rng.randint(1, 9):02d}-{rng.randint(1, 28):02d}"])
            self.files[path] = _csv_dump(FS_COLUMNS, rows)
        # distractors: archived copies with US variants (out of scope) and supplier files with a country column
        for k in range(p["n_distractor_files"]):
            if k % 2 == 0:
                src = self.target_files[k % len(self.target_files)]
                h, rows = _csv_parse(self.files[src])
                rows = [r[:] for r in rows]
                for r in rows[: 3]:
                    r[3] = rng.choice(US_VARIANTS)
                self.files[f"archive/customers_{k+1}_old.csv"] = _csv_dump(h, rows)
            else:
                rows = [[str(500 + j), f"Supplier {j}", rng.choice(US_VARIANTS + OTHER_COUNTRIES)] for j in range(6)]
                self.files[f"data/suppliers_{k+1}.csv"] = _csv_dump(["id", "supplier", "country"], rows)
        self.original = dict(self.files)
        self.edited: set[str] = set()
        # expected state
        self.expected = dict(self.original)
        for path in self.target_files:
            h, rows = _csv_parse(self.original[path])
            tgt = {rid for (pp, rid) in self.targets if pp == path}
            for r in rows:
                if r[0] in tgt:
                    r[3] = "US"
            self.expected[path] = _csv_dump(h, rows)
        hint = {0: "the customer export CSV files",
                1: "the customer export files (customers_*.csv) under data/",
                2: "these files: " + ", ".join(self.target_files)}[p["hint_level"]]
        return ("You are a data-cleaning assistant with file tools. In " + hint + ", some records refer to the United "
                "States with inconsistent spellings in the `country` column. Set `country` to the canonical code `US` for every "
                "record that refers to the United States. Do not modify any other field, record or file (archived copies are out "
                "of scope). Tool calls may fail transiently; retry when they do.")

    def tools(self) -> list[dict]:
        return [
            {"name": "ls", "description": "List entries of a directory ('' is the root). Directories end with '/'.",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}},
            {"name": "read", "description": "Read a file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}},
            {"name": "write", "description": "Overwrite (or create) a file with content.",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"], "additionalProperties": False}},
            {"name": "grep", "description": "Regex search over files matching a glob; returns path:line:text.",
             "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}, "glob": {"type": "string"}}, "required": ["pattern", "glob"], "additionalProperties": False}},
            {"name": "run_python", "description": "Run a short Python snippet with an `fs` object (fs.ls, fs.read, fs.write); set `result` to return a value. No imports.",
             "input_schema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"], "additionalProperties": False}},
        ]

    def _apply(self, tool: str, args: dict) -> str:
        if tool == "ls":
            path = args["path"].rstrip("/")
            prefix = path + "/" if path else ""
            entries = set()
            for f in self.files:
                if f.startswith(prefix):
                    rest = f[len(prefix):]
                    entries.add(rest.split("/")[0] + "/" if "/" in rest else rest)
            if not entries:
                return f"ERROR: no such directory: {args['path']}"
            return "\n".join(sorted(entries))
        if tool == "read":
            if args["path"] not in self.files:
                return f"ERROR: no such file: {args['path']}"
            return self.files[args["path"]]
        if tool == "write":
            self.files[args["path"]] = args["content"]
            self.edited.add(args["path"])
            return f"wrote {len(args['content'])} chars to {args['path']}"
        if tool == "grep":
            rx = re.compile(args["pattern"])
            out = []
            for f in sorted(self.files):
                if fnmatch.fnmatch(f, args["glob"]):
                    for i, line in enumerate(self.files[f].split("\n"), 1):
                        if rx.search(line):
                            out.append(f"{f}:{i}:{line}")
            return "\n".join(out) if out else "(no matches)"
        if tool == "run_python":
            env = self
            class FS:
                def ls(self, p): return env._apply("ls", {"path": p})
                def read(self, p): return env._apply("read", {"path": p})
                def write(self, p, c): return env._apply("write", {"path": p, "content": c})
            ns = {"fs": FS(), "__builtins__": {"len": len, "range": range, "str": str, "int": int, "float": float, "list": list,
                                               "dict": dict, "sorted": sorted, "enumerate": enumerate, "zip": zip, "min": min,
                                               "max": max, "sum": sum, "set": set, "tuple": tuple, "any": any, "all": all}}
            exec(args["code"], ns)  # restricted namespace; a real deployment uses a sandbox (see spec)
            return str(ns.get("result", "ok"))[:4000]
        return f"ERROR: unknown tool {tool}"

    def final_state(self) -> dict:
        return {"files": dict(self.files), "edited": sorted(self.edited), "n_calls": self.traj.n_calls}

    def expected_state(self) -> dict:
        return {"files": dict(self.expected), "targets": list(self.targets)}

    def _norm(self, text: str, s: FSStrictness) -> Any:
        h, rows = _csv_parse(text)
        if s.tolerate_whitespace:
            h = [c.strip() for c in h]
            rows = [[c.strip() for c in r] for r in rows]
        if s.tolerate_column_order and h:
            order = sorted(range(len(h)), key=lambda i: h[i])
            h = [h[i] for i in order]
            rows = [[r[i] if i < len(r) else "" for i in order] for r in rows]
        return (h, rows)

    def verify(self, s: FSStrictness) -> VerifyResult:
        reasons = []
        fixed = 0
        for path, rid in self.targets:
            h, rows = _csv_parse(self.files.get(path, ""))
            hs = [c.strip() for c in h]
            ci = hs.index("country") if "country" in hs else 3
            ii = hs.index("id") if "id" in hs else 0
            for r in rows:
                if len(r) > max(ci, ii) and r[ii].strip() == rid and r[ci].strip() == "US":
                    fixed += 1
                    break
        soft = fixed / max(1, len(self.targets))
        passed = True
        if soft < s.pass_threshold - 1e-9:
            passed = False
            reasons.append(f"only {fixed}/{len(self.targets)} target records fixed")
        if s.require_no_collateral_edits:
            for path, exp in self.expected.items():
                if path not in self.files:
                    passed = False; reasons.append(f"missing file {path}"); continue
                if self._norm(self.files[path], s) != self._norm(exp, s):
                    passed = False; reasons.append(f"collateral or incomplete edit in {path}")
            new = set(self.files) - set(self.expected)
            if new:
                passed = False; reasons.append(f"created files {sorted(new)}")
        max_steps = min(self.params["max_steps"], self.budget.max_steps)
        if s.require_within_steps and self.traj.n_calls > max_steps:
            passed = False; reasons.append(f"{self.traj.n_calls} calls > max_steps {max_steps}")
        return VerifyResult(passed, soft, reasons)

    def preview(self) -> str:
        lines = [self.task_text, "", f"files: {sorted(self.files)}", "expected edits (file, record id -> US):"]
        for path, rid in self.targets:
            h, rows = _csv_parse(self.original[path])
            old = next(r[3] for r in rows if r[0] == rid)
            lines.append(f"  {path} #{rid}: {old!r} -> 'US'")
        return "\n".join(lines)


# =====================================================================================================
# Family B: mock REST-API workflow (customers / orders / refunds)
# =====================================================================================================

CITIES = ["Austin", "Boston", "Denver", "Lisbon", "Osaka", "Perth", "Quito", "Riga"]


@dataclass
class APIStrictness:
    exact_set: bool = True            # refunded set must equal expected (False: superset allowed)
    require_confirmed: bool = True    # refunds must be confirmed
    idempotency_check: bool = True    # at most one refund per order
    forbid_forbidden_calls: bool = True  # cancel_order or refunding a shipped order fails the instance
    require_within_steps: bool = True
    pass_threshold: float = 1.0


class APIEnv(BaseEnv):
    name = "api_workflow"
    PARAM_SCHEMA = {
        "n_customers":        {"type": "int", "min": 2, "max": 50, "default": 10, "desc": "customers in the system"},
        "orders_per_customer":{"type": "int", "min": 1, "max": 20, "default": 6, "desc": "orders per customer"},
        "chain_depth":        {"type": "int", "min": 1, "max": 3, "default": 2, "desc": "1 id given; 2 name given; 3 ambiguous name, disambiguate by city"},
        "page_size":          {"type": "int", "min": 2, "max": 50, "default": 5, "desc": "list endpoints paginate at this size"},
        "rate_limit_rate":    {"type": "float", "min": 0.0, "max": 0.5, "default": 0.1, "desc": "probability a call returns 429"},
        "distractor_rate":    {"type": "float", "min": 0.0, "max": 1.0, "default": 0.3, "desc": "fraction of orders whose updated_at contradicts order_date"},
        "require_confirmation": {"type": "bool", "default": True, "desc": "refunds start pending and need confirm_refund"},
        "max_steps":          {"type": "int", "min": 5, "max": 200, "default": 40, "desc": "template-level step cap"},
    }
    STRICTNESS = APIStrictness

    def _transient_rate(self) -> float:
        return self.params["rate_limit_rate"]

    def _transient_message(self) -> str:
        return RATE_LIMIT

    @staticmethod
    def _date(rng: Random) -> str:
        return f"2026-{rng.randint(1, 6):02d}-{rng.randint(1, 28):02d}"

    def _generate(self) -> str:
        p, rng = self.params, self.rng
        self.customers, self.orders, self.refunds, self.cancelled, self.forbidden_calls = {}, {}, {}, set(), 0
        names = [f"{a} {b}" for a in FIRST for b in LAST]
        rng.shuffle(names)
        for i in range(p["n_customers"]):
            cid = f"c{i+1:03d}"
            self.customers[cid] = {"id": cid, "name": names[i], "city": rng.choice(CITIES), "email": f"user{i+1}@example.com"}
        self.target_cid = rng.choice(sorted(self.customers))
        tgt = self.customers[self.target_cid]
        if p["chain_depth"] == 3:  # duplicate the name on another customer in a different city
            other = rng.choice([c for c in sorted(self.customers) if c != self.target_cid])
            self.customers[other]["name"] = tgt["name"]
            self.customers[other]["city"] = rng.choice([c for c in CITIES if c != tgt["city"]])
        self.cutoff = f"2026-{rng.randint(2, 5):02d}-15"
        oid = 0
        for cid in sorted(self.customers):
            for _ in range(p["orders_per_customer"]):
                oid += 1
                od = self._date(rng)
                upd = od
                if rng.random() < p["distractor_rate"]:   # updated_at contradicts order_date relative to cutoff
                    upd = (f"2026-06-{rng.randint(1, 28):02d}" if od <= self.cutoff else f"2026-01-{rng.randint(1, 28):02d}")
                self.orders[f"o{oid:04d}"] = {"id": f"o{oid:04d}", "customer_id": cid, "order_date": od, "updated_at": upd,
                                              "status": rng.choice(["shipped", "pending", "processing", "shipped"]),
                                              "amount": f"{rng.randint(5, 500)}.00"}
        self.expected_orders = sorted(o["id"] for o in self.orders.values()
                                      if o["customer_id"] == self.target_cid and o["order_date"] > self.cutoff and o["status"] != "shipped")
        if not self.expected_orders:  # guarantee at least one actionable order so the task is non-vacuous
            o = next(o for o in self.orders.values() if o["customer_id"] == self.target_cid)
            o["order_date"] = "2026-06-20"; o["status"] = "pending"
            self.expected_orders = [o["id"]]
        who = {1: f"customer id {self.target_cid}", 2: f"customer {tgt['name']}", 3: f"customer {tgt['name']} ({tgt['city']})"}[p["chain_depth"]]
        return (f"Using the order-management API, refund in full every order of {who} that was PLACED after {self.cutoff} "
                "(use the order's order_date, not updated_at) and has not shipped (status is not 'shipped'). "
                + ("Refunds must be confirmed with confirm_refund. " if p["require_confirmation"] else "")
                + "Never cancel orders. List endpoints are paginated. The API may return 429; retry when it does.")

    def tools(self) -> list[dict]:
        o = lambda props, req: {"type": "object", "properties": props, "required": req, "additionalProperties": False}
        S = {"type": "string"}; I = {"type": "integer"}
        return [
            {"name": "search_customers", "description": "Find customers by exact name.", "input_schema": o({"name": S}, ["name"])},
            {"name": "get_customer", "description": "Get one customer.", "input_schema": o({"customer_id": S}, ["customer_id"])},
            {"name": "list_orders", "description": "List a customer's orders (paginated, 1-based page).", "input_schema": o({"customer_id": S, "page": I}, ["customer_id", "page"])},
            {"name": "get_order", "description": "Get one order.", "input_schema": o({"order_id": S}, ["order_id"])},
            {"name": "create_refund", "description": "Create a full refund for an order.", "input_schema": o({"order_id": S}, ["order_id"])},
            {"name": "confirm_refund", "description": "Confirm a pending refund.", "input_schema": o({"refund_id": S}, ["refund_id"])},
            {"name": "list_refunds", "description": "List refunds (paginated).", "input_schema": o({"page": I}, ["page"])},
            {"name": "cancel_order", "description": "Cancel an order.", "input_schema": o({"order_id": S}, ["order_id"])},
        ]

    def _page(self, items: list, page: int) -> str:
        ps = self.params["page_size"]
        total = max(1, -(-len(items) // ps))
        if page < 1 or page > total:
            return json.dumps({"items": [], "page": page, "total_pages": total})
        return json.dumps({"items": items[(page - 1) * ps: page * ps], "page": page, "total_pages": total})

    def _apply(self, tool: str, args: dict) -> str:
        if tool == "search_customers":
            return json.dumps([c for c in self.customers.values() if c["name"] == args["name"]])
        if tool == "get_customer":
            return json.dumps(self.customers.get(args["customer_id"]) or {"error": "not found"})
        if tool == "list_orders":
            items = [o for o in self.orders.values() if o["customer_id"] == args["customer_id"]]
            return self._page(items, int(args["page"]))
        if tool == "get_order":
            return json.dumps(self.orders.get(args["order_id"]) or {"error": "not found"})
        if tool == "create_refund":
            o = self.orders.get(args["order_id"])
            if not o:
                return json.dumps({"error": "order not found"})
            if o["status"] == "shipped":
                self.forbidden_calls += 1
                return json.dumps({"error": "cannot refund a shipped order"})
            rid = f"r{len(self.refunds)+1:04d}"
            self.refunds[rid] = {"id": rid, "order_id": o["id"], "amount": o["amount"],
                                 "status": "pending" if self.params["require_confirmation"] else "confirmed"}
            return json.dumps(self.refunds[rid])
        if tool == "confirm_refund":
            r = self.refunds.get(args["refund_id"])
            if not r:
                return json.dumps({"error": "refund not found"})
            r["status"] = "confirmed"
            return json.dumps(r)
        if tool == "list_refunds":
            return self._page(list(self.refunds.values()), int(args["page"]))
        if tool == "cancel_order":
            self.forbidden_calls += 1
            if args["order_id"] in self.orders:
                self.cancelled.add(args["order_id"]); self.orders[args["order_id"]]["status"] = "cancelled"
            return json.dumps({"ok": True})
        return f"ERROR: unknown tool {tool}"

    def final_state(self) -> dict:
        return {"refunds": copy.deepcopy(self.refunds), "cancelled": sorted(self.cancelled), "forbidden_calls": self.forbidden_calls, "n_calls": self.traj.n_calls}

    def expected_state(self) -> dict:
        return {"refunded_orders": list(self.expected_orders), "target_customer": self.target_cid, "cutoff": self.cutoff}

    def verify(self, s: APIStrictness) -> VerifyResult:
        reasons = []
        by_order: dict[str, list[dict]] = {}
        for r in self.refunds.values():
            by_order.setdefault(r["order_id"], []).append(r)
        ok = lambda oid: oid in by_order and (not s.require_confirmed or any(r["status"] == "confirmed" for r in by_order[oid]))
        done = sum(ok(o) for o in self.expected_orders)
        soft = done / len(self.expected_orders)
        passed = True
        if soft < s.pass_threshold - 1e-9:
            passed = False; reasons.append(f"{done}/{len(self.expected_orders)} expected orders refunded")
        extra = sorted(set(by_order) - set(self.expected_orders))
        if s.exact_set and extra:
            passed = False; reasons.append(f"refunded non-target orders {extra}")
        if s.idempotency_check and any(len(v) > 1 for v in by_order.values()):
            passed = False; reasons.append("duplicate refunds")
        if s.forbid_forbidden_calls and (self.forbidden_calls or self.cancelled):
            passed = False; reasons.append("forbidden call (cancel / refund of shipped order)")
        max_steps = min(self.params["max_steps"], self.budget.max_steps)
        if s.require_within_steps and self.traj.n_calls > max_steps:
            passed = False; reasons.append(f"{self.traj.n_calls} calls > max_steps {max_steps}")
        return VerifyResult(passed, soft, reasons)

    def preview(self) -> str:
        return self.task_text + f"\n\nexpected: confirmed refunds for exactly {self.expected_orders} (customer {self.target_cid}); no cancellations."


# =====================================================================================================
# Family C: constraint scheduling with a solver tool and hidden constraints
# =====================================================================================================

N_SLOTS, SLOTS_PER_DAY = 40, 8


@dataclass
class SchedStrictness:
    all_hard: bool = True             # hidden constraints count (False: only public calendars)
    soft_weighted: bool = True        # proposal must reach soft_threshold x optimum soft score
    soft_threshold: float = 0.8
    must_detect_infeasible: bool = True
    require_within_steps: bool = True


class SchedulingEnv(BaseEnv):
    name = "scheduling"
    PARAM_SCHEMA = {
        "n_people":        {"type": "int", "min": 2, "max": 12, "default": 4, "desc": "attendees"},
        "n_constraints":   {"type": "int", "min": 0, "max": 10, "default": 3, "desc": "public soft preferences"},
        "n_hidden":        {"type": "int", "min": 0, "max": 6, "default": 2, "desc": "hidden busy blocks only visible via query_availability"},
        "infeasible_rate": {"type": "float", "min": 0.0, "max": 1.0, "default": 0.2, "desc": "fraction of instances with no feasible slot"},
        "duration":        {"type": "int", "min": 1, "max": 3, "default": 1, "desc": "meeting length in slots"},
        "busy_density":    {"type": "float", "min": 0.1, "max": 0.8, "default": 0.4, "desc": "public busy probability per slot"},
        "max_steps":       {"type": "int", "min": 5, "max": 200, "default": 40, "desc": "template-level step cap"},
    }
    STRICTNESS = SchedStrictness

    def _feasible_starts(self, busy: dict[str, set[int]]) -> list[int]:
        d = self.params["duration"]
        out = []
        for s in range(N_SLOTS):
            if s % SLOTS_PER_DAY + d > SLOTS_PER_DAY:
                continue
            if all(all((s + k) not in busy[p] for k in range(d)) for p in busy):
                out.append(s)
        return out

    def _soft(self, start: int) -> float:
        if not self.prefs:
            return 1.0
        tot = sum(w for _, _, _, w in self.prefs)
        got = 0
        hour, day = start % SLOTS_PER_DAY, start // SLOTS_PER_DAY
        for _, kind, val, w in self.prefs:
            if (kind == "morning" and hour < 4) or (kind == "afternoon" and hour >= 4) or (kind == "day" and day == val) or (kind == "not_day" and day != val):
                got += w
        return got / tot

    def _generate(self) -> str:
        p, rng = self.params, self.rng
        self.people = [f"{FIRST[i]}" for i in range(p["n_people"])]
        self.public = {q: {s for s in range(N_SLOTS) if rng.random() < p["busy_density"]} for q in self.people}
        self.hidden = {q: set() for q in self.people}
        self.prefs = []
        for _ in range(p["n_constraints"]):
            kind = rng.choice(["morning", "afternoon", "day", "not_day"])
            self.prefs.append((rng.choice(self.people), kind, rng.randrange(5) if "day" in kind else None, rng.randint(1, 3)))
        full = lambda: {q: self.public[q] | self.hidden[q] for q in self.people}
        feas = self._feasible_starts(full())
        self.infeasible = rng.random() < p["infeasible_rate"]
        if self.infeasible:
            # hide busy blocks until nothing is feasible (may exceed n_hidden; documented)
            while feas:
                s = rng.choice(feas); q = rng.choice(self.people)
                self.hidden[q].update(range(s, s + p["duration"]))
                feas = self._feasible_starts(full())
        else:
            for _ in range(p["n_hidden"]):
                if len(feas) <= 1:
                    break
                s = rng.choice(feas); q = rng.choice(self.people)
                self.hidden[q].update(range(s, s + p["duration"]))
                feas = self._feasible_starts(full())
        self.full_feasible = feas
        self.optimum = max((self._soft(s) for s in feas), default=0.0)
        self.proposal: Any = None
        pref_txt = "; ".join(f"{q} prefers {kind}{'' if val is None else ' ' + str(val)} (weight {w})" for q, kind, val, w in self.prefs) or "none"
        return (f"Schedule a {p['duration']}-slot meeting for {', '.join(self.people)} within one working day (5 days x 8 slots, "
                f"slot ids 0-39, day = slot // 8). The shared calendar (get_calendars) may be incomplete: each person's full "
                f"availability is only returned by query_availability. Soft preferences: {pref_txt}. Use solve to find the best "
                f"start slot given the constraints you have gathered, then call propose(start) or declare_infeasible().")

    def tools(self) -> list[dict]:
        o = lambda props, req: {"type": "object", "properties": props, "required": req, "additionalProperties": False}
        return [
            {"name": "get_calendars", "description": "Public busy slots per person.", "input_schema": o({}, [])},
            {"name": "query_availability", "description": "Full (public + private) busy slots for one person.", "input_schema": o({"person": {"type": "string"}}, ["person"])},
            {"name": "solve", "description": "Given busy slots per person (JSON object of lists), return the best feasible start slot under the task's preferences, or 'none'.",
             "input_schema": o({"busy_json": {"type": "string"}}, ["busy_json"])},
            {"name": "propose", "description": "Final answer: start slot.", "input_schema": o({"start": {"type": "integer"}}, ["start"])},
            {"name": "declare_infeasible", "description": "Final answer: no feasible slot exists.", "input_schema": o({}, [])},
        ]

    def _is_terminal_tool(self, tool: str) -> bool:
        return tool in ("propose", "declare_infeasible")

    def _apply(self, tool: str, args: dict) -> str:
        if tool == "get_calendars":
            return json.dumps({q: sorted(v) for q, v in self.public.items()})
        if tool == "query_availability":
            q = args["person"]
            if q not in self.public:
                return json.dumps({"error": "unknown person"})
            return json.dumps({q: sorted(self.public[q] | self.hidden[q])})
        if tool == "solve":
            busy = {q: set(v) for q, v in json.loads(args["busy_json"]).items()}
            feas = self._feasible_starts(busy)
            if not feas:
                return "none"
            best = max(feas, key=lambda s: (self._soft(s), -s))
            return str(best)
        if tool == "propose":
            self.proposal = int(args["start"])
            return "recorded"
        if tool == "declare_infeasible":
            self.proposal = "infeasible"
            return "recorded"
        return f"ERROR: unknown tool {tool}"

    def final_state(self) -> dict:
        return {"proposal": self.proposal, "n_calls": self.traj.n_calls}

    def expected_state(self) -> dict:
        return {"infeasible": self.infeasible, "feasible_starts": list(self.full_feasible), "optimum_soft": self.optimum}

    def verify(self, s: SchedStrictness) -> VerifyResult:
        reasons = []
        busy = {q: (self.public[q] | self.hidden[q]) if s.all_hard else set(self.public[q]) for q in self.people}
        feas = set(self._feasible_starts(busy))
        max_steps = min(self.params["max_steps"], self.budget.max_steps)
        over = s.require_within_steps and self.traj.n_calls > max_steps
        if self.infeasible:
            if self.proposal == "infeasible":
                passed, soft = True, 1.0
            elif s.must_detect_infeasible:
                passed, soft = False, 0.0; reasons.append("did not detect infeasibility")
            else:
                passed = isinstance(self.proposal, int) and self.proposal in feas
                soft = 1.0 if passed else 0.0
                if not passed: reasons.append("proposal violates hard constraints")
        else:
            if not isinstance(self.proposal, int):
                return VerifyResult(False, 0.0, ["no valid proposal"])
            if self.proposal not in feas:
                return VerifyResult(False, 0.0, ["proposal violates hard constraints"])
            soft = self._soft(self.proposal) / self.optimum if self.optimum > 0 else 1.0
            passed = True
            if s.soft_weighted and soft < s.soft_threshold - 1e-9:
                passed = False; reasons.append(f"soft score {soft:.2f} < threshold")
        if over:
            passed = False; reasons.append(f"{self.traj.n_calls} calls > max_steps {max_steps}")
        return VerifyResult(passed, soft, reasons)

    def preview(self) -> str:
        return self.task_text + f"\n\nexpected: {'INFEASIBLE' if self.infeasible else 'feasible starts ' + str(self.full_feasible) + f', optimum soft {self.optimum:.2f}'}"


TEMPLATES: dict[str, type[BaseEnv]] = {"fs_clean": FileSystemEnv, "api_workflow": APIEnv, "scheduling": SchedulingEnv}


# =====================================================================================================
# Scripted agents: oracle and three style agents.  Signature: fn(env, task_text, budget) -> Trajectory
# =====================================================================================================

class BudgetExhausted(Exception):
    """Raised inside scripted agents when the hard tool-call cap is hit; run_instance absorbs it."""


def _retry(env: BaseEnv, tool: str, args: dict, tries: int = 6) -> str:
    for _ in range(tries):
        obs = env.step(tool, args)
        if obs == EXHAUSTED:
            raise BudgetExhausted()
        if not (obs.startswith("ERROR 429") or obs.startswith("ERROR: transient")):
            return obs
    return obs


def _fs_fix_content(text: str, detector: Callable[[str], bool], sep: str = ",", sort_cols: bool = False) -> str:
    h, rows = _csv_parse(text)
    ci = h.index("country")
    for r in rows:
        if detector(r[ci]):
            r[ci] = "US"
    if sort_cols:
        order = sorted(range(len(h)), key=lambda i: h[i])
        h = [h[i] for i in order]; rows = [[r[i] for i in order] for r in rows]
    return "\n".join([sep.join(h)] + [sep.join(r) for r in rows]) + "\n"


def _fs_target_paths(env: FileSystemEnv, call) -> list[str]:
    root = call("ls", {"path": ""})
    paths = []
    for d in root.split("\n"):
        if d.endswith("/") and d != "archive/":
            for f in call("ls", {"path": d}).split("\n"):
                if f.startswith("customers_") and f.endswith(".csv"):
                    paths.append(d + f)
    return paths


def agent_oracle(env: BaseEnv, task: str, budget: Budget) -> Trajectory:
    if isinstance(env, FileSystemEnv):
        call = lambda t, a: _retry(env, t, a)
        for path in _fs_target_paths(env, call):
            txt = call("read", {"path": path})
            call("write", {"path": path, "content": _fs_fix_content(txt, is_us_variant)})
    elif isinstance(env, APIEnv):
        call = lambda t, a: _retry(env, t, a)
        cid = _api_resolve_customer(env, call)
        orders = _api_all_orders(env, call, cid)
        for o in orders:
            if o["order_date"] > env.cutoff and o["status"] != "shipped":
                r = json.loads(call("create_refund", {"order_id": o["id"]}))
                if r.get("status") == "pending":
                    call("confirm_refund", {"refund_id": r["id"]})
    elif isinstance(env, SchedulingEnv):
        call = lambda t, a: _retry(env, t, a)
        call("get_calendars", {})
        busy = {}
        for q in env.people:
            busy.update(json.loads(call("query_availability", {"person": q})))
        best = call("solve", {"busy_json": json.dumps(busy)})
        if best == "none":
            call("declare_infeasible", {})
        else:
            call("propose", {"start": int(best)})
    return env.traj


def agent_careful_retrier(env: BaseEnv, task: str, budget: Budget) -> Trajectory:
    """Correct like the oracle but verifies every write / every refund / every person twice: ~2x steps."""
    if isinstance(env, FileSystemEnv):
        call = lambda t, a: _retry(env, t, a, tries=10)
        for path in _fs_target_paths(env, call):
            txt = call("read", {"path": path})
            new = _fs_fix_content(txt, is_us_variant)
            call("write", {"path": path, "content": new})
            if call("read", {"path": path}) != new:
                call("write", {"path": path, "content": new})
    elif isinstance(env, APIEnv):
        call = lambda t, a: _retry(env, t, a, tries=10)
        cid = _api_resolve_customer(env, call)
        call("get_customer", {"customer_id": cid})
        for o in _api_all_orders(env, call, cid):
            o2 = json.loads(call("get_order", {"order_id": o["id"]}))
            if o2.get("order_date", "") > env.cutoff and o2.get("status") != "shipped":
                r = json.loads(call("create_refund", {"order_id": o["id"]}))
                if r.get("status") == "pending":
                    call("confirm_refund", {"refund_id": r["id"]})
        call("list_refunds", {"page": 1})
    elif isinstance(env, SchedulingEnv):
        call = lambda t, a: _retry(env, t, a, tries=10)
        call("get_calendars", {})
        busy = {}
        for q in env.people:
            busy.update(json.loads(call("query_availability", {"person": q})))
            call("query_availability", {"person": q})  # re-check
        best = call("solve", {"busy_json": json.dumps(busy)})
        call("solve", {"busy_json": json.dumps(busy)})
        call("declare_infeasible", {}) if best == "none" else call("propose", {"start": int(best)})
    return env.traj


def agent_fast_sloppy(env: BaseEnv, task: str, budget: Budget) -> Trajectory:
    """No retries, first page only, exact-match detection, ambiguous field, no confirmation, reformats files."""
    simple = lambda v: v.strip().lower() in {x.lower() for x in US_VARIANTS}  # misses typos and encoding noise
    if isinstance(env, FileSystemEnv):
        root = env.step("ls", {"path": ""})
        for d in [x for x in root.split("\n") if x.endswith("/") and x != "archive/"]:
            listing = env.step("ls", {"path": d})
            for f in [x for x in listing.split("\n") if x.startswith("customers_")]:
                txt = env.step("read", {"path": d + f})
                if txt.startswith("ERROR"):
                    continue
                env.step("write", {"path": d + f, "content": _fs_fix_content(txt, simple, sep=", ")})
    elif isinstance(env, APIEnv):
        cid = _api_resolve_customer(env, env.step, sloppy=True)
        if cid:
            page = env.step("list_orders", {"customer_id": cid, "page": 1})
            if not page.startswith("ERROR"):
                for o in json.loads(page)["items"]:
                    if o["updated_at"] > env.cutoff and o["status"] != "shipped":   # wrong field
                        env.step("create_refund", {"order_id": o["id"]})           # never confirms
    elif isinstance(env, SchedulingEnv):
        cal = env.step("get_calendars", {})
        best = env.step("solve", {"busy_json": cal if not cal.startswith("ERROR") else "{}"})
        if best == "none" or best.startswith("ERROR"):
            env.step("declare_infeasible", {})
        else:
            env.step("propose", {"start": int(best)})
    return env.traj


def agent_over_verifier(env: BaseEnv, task: str, budget: Budget) -> Trajectory:
    """Reads everything twice, normalises column order on write, double-submits refunds, solves per day."""
    if isinstance(env, FileSystemEnv):
        call = lambda t, a: _retry(env, t, a)
        root = call("ls", {"path": ""})
        for d in [x for x in root.split("\n") if x.endswith("/")]:
            for f in call("ls", {"path": d}).split("\n"):
                call("read", {"path": d + f}); call("read", {"path": d + f})
        for path in _fs_target_paths(env, call):
            txt = call("read", {"path": path})
            call("write", {"path": path, "content": _fs_fix_content(txt, is_us_variant, sort_cols=True)})
    elif isinstance(env, APIEnv):
        call = lambda t, a: _retry(env, t, a)
        cid = _api_resolve_customer(env, call)
        for o in _api_all_orders(env, call, cid):
            if o["order_date"] > env.cutoff and o["status"] != "shipped":
                for _ in range(2):  # "to be sure"
                    r = json.loads(call("create_refund", {"order_id": o["id"]}))
                    if r.get("status") == "pending":
                        call("confirm_refund", {"refund_id": r["id"]})
        for pg in range(1, 4):
            call("list_refunds", {"page": pg})
    elif isinstance(env, SchedulingEnv):
        call = lambda t, a: _retry(env, t, a)
        call("get_calendars", {})
        busy = {}
        for q in env.people:
            busy.update(json.loads(call("query_availability", {"person": q})))
        cands = []
        for day in range(5):
            b = {q: sorted(set(v) | {s for s in range(N_SLOTS) if s // SLOTS_PER_DAY != day}) for q, v in busy.items()}
            r = call("solve", {"busy_json": json.dumps(b)})
            if r != "none":
                cands.append(int(r))
        if not cands:
            call("declare_infeasible", {})
        else:
            call("propose", {"start": max(cands, key=lambda s: (env._soft(s), -s))})
    return env.traj


def _api_resolve_customer(env: APIEnv, call, sloppy: bool = False) -> Optional[str]:
    if env.params["chain_depth"] == 1:
        return env.target_cid
    name = env.customers[env.target_cid]["name"]
    res = call("search_customers", {"name": name})
    if res.startswith("ERROR"):
        return None
    cands = json.loads(res)
    if sloppy or len(cands) == 1:
        return cands[0]["id"] if cands else None
    city = env.customers[env.target_cid]["city"]
    return next((c["id"] for c in cands if c["city"] == city), cands[0]["id"])


def _api_all_orders(env: APIEnv, call, cid: str) -> list[dict]:
    out, page, total = [], 1, 1
    while page <= total:
        r = json.loads(call("list_orders", {"customer_id": cid, "page": page}))
        out += r["items"]; total = r["total_pages"]; page += 1
    return out


SCRIPTED_AGENTS: dict[str, Callable] = {
    "oracle": agent_oracle, "careful_retrier": agent_careful_retrier,
    "fast_sloppy": agent_fast_sloppy, "over_verifier": agent_over_verifier,
}


# =====================================================================================================
# Designer interface
# =====================================================================================================

SEED_BASE = 7_310_000
N_BENCH = 60
FROZEN_SEED_SET = {t: [SEED_BASE + 1000 * i + j for j in range(N_BENCH)] for i, t in enumerate(TEMPLATES)}


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def make_env(template: str, params: dict, seed: int, budget: Budget) -> BaseEnv:
    return TEMPLATES[template](params, seed, budget)


def run_instance(template: str, params: dict, strictness, seed: int, budget: Budget, run_agent_fn: Callable) -> VerifyResult:
    env = make_env(template, params, seed, budget)
    try:
        run_agent_fn(env, env.task_text, budget)
    except BudgetExhausted:
        pass  # trajectory so far is already recorded on env.traj
    return env.verify(strictness)


class T3Interface:
    """In-memory design state + action log + scores view hook.  `handle_tool` is the single entry point."""

    def __init__(self, scores_view: Optional[Callable[[dict[str, float]], str]] = None, oracle: Callable = agent_oracle):
        self.config = {"params": {t: _check_params(c.PARAM_SCHEMA, {}) for t, c in TEMPLATES.items()},
                       "strictness": {t: asdict(c.STRICTNESS()) for t, c in TEMPLATES.items()},
                       "mix": {t: round(1 / len(TEMPLATES), 4) for t in TEMPLATES},
                       "budget": asdict(Budget())}
        self.notes: list[str] = []
        self.log: list[dict] = []
        self.round = 1
        self.submitted = False
        self.scores_view = scores_view or (lambda s: "\n".join(f"{m}: {v:.3f}" for m, v in sorted(s.items(), key=lambda kv: -kv[1])))
        self.oracle = oracle
        self._cache: dict[tuple, VerifyResult] = {}
        self.score_requests: list[dict] = []

    # -- helpers ---------------------------------------------------------------------------------------
    def config_hash(self) -> str:
        return _hash(self.config)

    def strictness_obj(self, t: str):
        return TEMPLATES[t].STRICTNESS(**self.config["strictness"][t])

    def budget(self) -> Budget:
        return Budget(**self.config["budget"])

    def instances(self) -> list[tuple[str, int]]:
        """Deterministic allocation of N_BENCH instances to templates by mix (largest-remainder rounding)."""
        mix = self.config["mix"]
        raw = {t: N_BENCH * mix.get(t, 0.0) for t in TEMPLATES}
        counts = {t: int(raw[t]) for t in TEMPLATES}
        for t in sorted(TEMPLATES, key=lambda t: -(raw[t] - counts[t]))[: N_BENCH - sum(counts.values())]:
            counts[t] += 1
        return [(t, FROZEN_SEED_SET[t][i]) for t in TEMPLATES for i in range(counts[t])]

    def validate(self, check_oracle: bool = True) -> list[str]:
        problems = []
        for t in TEMPLATES:
            try:
                _check_params(TEMPLATES[t].PARAM_SCHEMA, self.config["params"][t])
            except ParamError as e:
                problems.append(f"{t}: {e}")
        mix = self.config["mix"]
        if abs(sum(mix.values()) - 1.0) > 1e-6:
            problems.append("mix fractions must sum to 1")
        if sum(1 for v in mix.values() if v > 0) < 2:
            problems.append("at least 2 templates must have a positive mix fraction")
        if check_oracle and not problems:
            res = [self._run_cached("__oracle__", self.oracle, t, s, 0) for t, s in self.instances()]
            rate = sum(r.passed for r in res) / len(res)
            if rate < 0.95:
                problems.append(f"oracle solvability {rate:.2f} < 0.95: configuration is not reachable")
        return problems

    def _run_cached(self, model: str, fn: Callable, t: str, seed: int, sample: int) -> VerifyResult:
        key = (_hash(self.config["params"][t]), _hash(self.config["strictness"][t]), _hash(self.config["budget"]), t, seed, model, sample)
        if key not in self._cache:
            self._cache[key] = run_instance(t, self.config["params"][t], self.strictness_obj(t), seed, self.budget(), fn)
        return self._cache[key]

    def panel_scores(self, panel: dict[str, Callable], k: int = 1) -> dict[str, float]:
        """True mean pass rate per panel entry on the current benchmark (k samples per instance)."""
        out = {}
        for m, fn in panel.items():
            res = [self._run_cached(m, fn, t, s, smp) for t, s in self.instances() for smp in range(k)]
            out[m] = sum(r.passed for r in res) / len(res)
        return out

    # -- designer tools ---------------------------------------------------------------------------------
    def handle_tool(self, name: str, args: dict, panel: Optional[dict[str, Callable]] = None, k: int = 1) -> str:
        out = self._dispatch(name, args, panel, k)
        self.log.append({"round": self.round, "tool": name, "args": args, "result": out[:2000], "config_hash": self.config_hash()})
        return out

    def _dispatch(self, name: str, args: dict, panel, k) -> str:
        if self.submitted:
            return "ERROR: benchmark already submitted"
        if name == "describe_templates":
            lines = []
            for t, cls in TEMPLATES.items():
                lines.append(f"## {t}\nparameters:")
                for pn, spec in cls.PARAM_SCHEMA.items():
                    rng = f"[{spec['min']}, {spec['max']}]" if "min" in spec else (f"subset of {spec['choices']}" if spec["type"] == "subset" else "bool")
                    lines.append(f"  - {pn} ({spec['type']}, {rng}, default {spec['default']}): {spec['desc']}")
                lines.append("verifier strictness knobs: " + ", ".join(f"{f}={v}" for f, v in asdict(cls.STRICTNESS()).items()))
            return "\n".join(lines)
        if name == "preview_instance":
            t = args["template"]
            try:
                env = make_env(t, {**self.config["params"][t], **args.get("params", {})}, int(args.get("seed", FROZEN_SEED_SET[t][0])), self.budget())
            except ParamError as e:
                return f"ERROR: {e}"
            return env.preview()
        if name == "set_params":
            t = args["template"]
            if t not in TEMPLATES:
                return f"ERROR: unknown template {t}"
            try:
                self.config["params"][t] = _check_params(TEMPLATES[t].PARAM_SCHEMA, {**self.config["params"][t], **args["params"]})
            except ParamError as e:
                return f"ERROR: {e}"
            return f"ok: {t} params = {self.config['params'][t]}"
        if name == "set_mix":
            mix = {t: float(args["mix"].get(t, 0.0)) for t in TEMPLATES}
            if any(v < 0 for v in mix.values()) or abs(sum(mix.values()) - 1.0) > 1e-6:
                return "ERROR: mix fractions must be non-negative and sum to 1"
            self.config["mix"] = mix
            return f"ok: mix = {mix}; instances per template = { {t: n for t, n in _count(self.instances()).items()} }"
        if name == "set_verifier":
            t = args["template"]
            known = asdict(TEMPLATES[t].STRICTNESS())
            bad = set(args["strictness"]) - set(known)
            if bad:
                return f"ERROR: unknown strictness knobs {sorted(bad)}; known: {sorted(known)}"
            self.config["strictness"][t].update(args["strictness"])
            return f"ok: {t} strictness = {self.config['strictness'][t]}"
        if name == "set_budget":
            b = Budget(int(args.get("max_steps", self.config["budget"]["max_steps"])), int(args.get("max_tool_calls", self.config["budget"]["max_tool_calls"])))
            if not (5 <= b.max_steps <= 200 and 5 <= b.max_tool_calls <= 400):
                return "ERROR: max_steps in [5,200], max_tool_calls in [5,400]"
            self.config["budget"] = asdict(b)
            return f"ok: budget = {self.config['budget']}"
        if name == "request_panel_scores":
            if panel is None:
                return "Panel results are not available for this project."
            scores = self.panel_scores(panel, k)
            self.score_requests.append({"round": self.round, "config_hash": self.config_hash(), "true_scores": scores})
            return self.scores_view(scores)
        if name == "write_notes":
            self.notes.append(args["text"])
            return "noted"
        if name == "end_round":
            self.round += 1
            return f"round {self.round} begins"
        if name == "submit":
            problems = self.validate()
            if problems:
                return "ERROR: cannot submit: " + "; ".join(problems)
            self.submitted = True
            self.notes.append(args.get("final_notes", ""))
            return f"submitted; config hash {self.config_hash()}"
        return f"ERROR: unknown tool {name}"


def _count(pairs):
    out = {}
    for t, _ in pairs:
        out[t] = out.get(t, 0) + 1
    return out


def _o(props, req):
    return {"type": "object", "properties": props, "required": req, "additionalProperties": False}


T3_TOOLS: list[dict] = [
    {"name": "describe_templates", "description": "List the task templates, their tunable parameters (with ranges and defaults) and the exposed verifier strictness knobs.", "input_schema": _o({}, [])},
    {"name": "preview_instance", "description": "Render one task instance (task statement and expected final state) for a template, optional parameter overrides and a seed.",
     "input_schema": _o({"template": {"type": "string"}, "params": {"type": "object", "additionalProperties": True}, "seed": {"type": "integer"}}, ["template"])},
    {"name": "set_params", "description": "Set parameters for one template (partial updates allowed).",
     "input_schema": _o({"template": {"type": "string"}, "params": {"type": "object", "additionalProperties": True}}, ["template", "params"])},
    {"name": "set_mix", "description": "Set the fraction of the 60-instance benchmark drawn from each template; fractions sum to 1.",
     "input_schema": _o({"mix": {"type": "object", "additionalProperties": {"type": "number"}}}, ["mix"])},
    {"name": "set_verifier", "description": "Set exposed verifier strictness knobs for one template.",
     "input_schema": _o({"template": {"type": "string"}, "strictness": {"type": "object", "additionalProperties": True}}, ["template", "strictness"])},
    {"name": "set_budget", "description": "Set the agent budget: max_steps (verifier cap) and max_tool_calls (hard cap).",
     "input_schema": _o({"max_steps": {"type": "integer"}, "max_tool_calls": {"type": "integer"}}, [])},
    {"name": "request_panel_scores", "description": "Run the current draft benchmark on the standard model panel and return each model's pass rate.", "input_schema": _o({}, [])},
    {"name": "write_notes", "description": "Record design rationale.", "input_schema": _o({"text": {"type": "string"}}, ["text"])},
    {"name": "end_round", "description": "Finish the current design round.", "input_schema": _o({}, [])},
    {"name": "submit", "description": "Submit the final benchmark configuration (validated: ranges, >=2 templates, oracle solvability >= 95%).",
     "input_schema": _o({"final_notes": {"type": "string"}}, [])},
]
