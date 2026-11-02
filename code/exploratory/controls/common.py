"""Shared loaders and statistics for the controls analysis (EXPLORATORY, post-unblinding 2026-10-30)."""
import json
import os
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path("/path/to/metabench/unblinded")
OUT = Path("/path/to/metabench/analysis/controls")
POOLS = ["factual", "math", "code"]
PLACEBO = "placebo_sonnet55"
DEVELOPER = {
    "fable51": "anthropic", "opus5": "anthropic", "sonnet55": "anthropic", "placebo_sonnet55": "anthropic",
    "gpt61sol": "openai", "gpt6luna": "openai", "gpt55": "openai",
    "gemini4argon": "google", "gemini31pro": "google", "gemini38flash": "google",
    "grok47": "xai", "grok45": "xai", "grok43": "xai",
}
SCORE_ARMS = ["sham", "inverted", "true_named", "true_blinded", "instructed"]


def work(pool):
    return ROOT / f"WORK_{pool}"


def load_rows(pool, valid_only=True):
    rows = [json.loads(l) for l in open(work(pool) / "results/benchmarks.jsonl")]
    for r in rows:
        r["pool"] = pool
    return [r for r in rows if r["valid"]] if valid_only else rows


def sess_dir(pool, sid):
    return work(pool) / "sessions" / sid


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path) if l.strip()]


def load_json(path):
    return json.load(open(path)) if os.path.exists(path) else None


def rank_keys(row, target=None):
    """The 12 displayed designer keys (placebo removed). If the target is the placebo, the placebo replaces its twin
    sonnet55 so that the target is ranked among 12 distinct configurations."""
    keys = [k for k in row["displayed_keys"] if k != PLACEBO]
    if target == PLACEBO:
        keys = [PLACEBO if k == "sonnet55" else k for k in keys]
    return keys


def ranks(scores, keys):
    """1 = best; average ranks for ties (same rule as metabench.analysis.ranks_from_scores)."""
    v = np.array([scores[k] for k in keys], float)
    return dict(zip(keys, stats.rankdata(-v, method="average")))


def cluster_boot(by_designer, n_boot=10000, seed=0):
    """Designer-average of per-designer means, with designer-cluster bootstrap (designers with replacement, then
    benchmarks within designer) 95% percentile CI. Returns (est, lo, hi, n_designers, n_obs)."""
    rng = np.random.default_rng(seed)
    ds = [d for d, v in by_designer.items() if len(v)]
    if not ds:
        return dict(est=None, lo=None, hi=None, n_designers=0, n=0)
    arrs = [np.asarray(by_designer[d], float) for d in ds]
    est = float(np.mean([a.mean() for a in arrs]))
    D = len(ds)
    bs = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.integers(0, D, D)
        bs[b] = np.mean([arrs[i][rng.integers(0, len(arrs[i]), len(arrs[i]))].mean() for i in pick])
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return dict(est=est, lo=float(lo), hi=float(hi), n_designers=D, n=int(sum(len(a) for a in arrs)))


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (float(c - h), float(c + h))


def prop(by_designer, n_boot=10000, seed=0):
    """Proportion summary: pooled k/n with Wilson CI and the designer-averaged proportion with cluster-bootstrap CI."""
    allv = [x for v in by_designer.values() for x in v]
    k, n = int(sum(allv)), len(allv)
    cb = cluster_boot(by_designer, n_boot, seed)
    return dict(k=k, n=n, p=(k / n if n else None), wilson=wilson(k, n), designer_avg=cb["est"],
                designer_ci=[cb["lo"], cb["hi"]], n_designers=cb["n_designers"])


LABEL_RE = re.compile(r"MDL[-_ ]?(\d{1,2})", re.I)


def norm_label(s):
    return re.sub(r"[^a-z0-9.]", "", s.lower()) if s else ""


def labels_in_text(text, label_map):
    """All (position, panel_key) mentions of a panel label (pseudonym MDL-NN or display name) in text, by position.
    Longest display names are matched first so 'GPT-6.1 Sol' is not read as another entry."""
    if not text:
        return []
    inv = {v: k for k, v in label_map.items()}
    hits = []
    for m in LABEL_RE.finditer(text):
        lab = f"MDL-{int(m.group(1)):02d}"
        if lab in inv:
            hits.append((m.start(), inv[lab]))
    taken = [False] * len(text)
    low = text.lower()
    names = sorted([v for v in label_map.values() if not v.startswith("MDL-")], key=len, reverse=True)
    for name in names:
        for m in re.finditer(re.escape(name.lower()), low):
            if not any(taken[m.start():m.end()]):
                hits.append((m.start(), inv[name]))
                for i in range(m.start(), m.end()):
                    taken[i] = True
    return sorted(hits)


def dump(obj, name):
    with open(OUT / name, "w") as f:
        json.dump(obj, f, indent=1, default=float)

DISPLAY = {'fable51': 'Claude Fable 5.1', 'sonnet55': 'Claude Sonnet 5.5', 'opus5': 'Claude Opus 5', 'gpt61sol': 'GPT-6.1 Sol',
           'gpt6luna': 'GPT-6 Luna', 'gpt55': 'GPT-5.5', 'gemini4argon': 'Gemini 4 Argon', 'gemini38flash': 'Gemini 3.8 Flash',
           'gemini31pro': 'Gemini 3.1 Pro', 'grok47': 'Grok 4.7', 'grok45': 'Grok 4.5', 'grok43': 'Grok 4.3'}
