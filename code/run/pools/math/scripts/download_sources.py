"""Download every HF source used by the math pool into pools/_work/math/raw/<name>.jsonl (+ dataset cards),
plus the Hendrycks MATH test split (original zip -> pools/_work/math/MATH/, EleutherAI mirror -> raw/).

Deterministic and re-runnable. No model is run; no *_outputs dataset is touched.
Usage: HF_HOME=... python -I download_sources.py
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "pools/_work/math/raw"
CARDS = ROOT / "pools/_work/math/cards"

DATASETS = [
    # MathArena contests (problem_idx, problem, answer, [problem_type])
    "MathArena/aime_2026", "MathArena/hmmt_feb_2026", "MathArena/hmmt_nov_2025", "MathArena/aime_2025",
    "MathArena/hmmt_feb_2025", "MathArena/brumo_2025", "MathArena/cmimc_2025", "MathArena/smt_2025",
    "MathArena/apex_2025", "MathArena/hmmt_feb_2024", "MathArena/hmmt_feb_2023",
    "MathArena/aime_2024_I", "MathArena/aime_2024_II", "MathArena/aime_2023_I", "MathArena/aime_2023_II",
    "MathArena/final_answer_comps",  # overlap detection only
    # AIME archive and its suspected copy
    "gneubig/aime-1983-2024", "di-zhang-fdu/AIME_1983_2024",
    # cross-sources for AIME key agreement
    "opencompass/AIME2025", "yentinglin/aime_2025", "AI-MO/aimo-validation-aime",
]


def main() -> int:
    from datasets import load_dataset, get_dataset_config_names
    from huggingface_hub import hf_hub_download
    RAW.mkdir(parents=True, exist_ok=True)
    CARDS.mkdir(parents=True, exist_ok=True)
    status = {}
    for name in DATASETS:
        safe = name.replace("/", "__")
        try:
            p = hf_hub_download(name, "README.md", repo_type="dataset")
            (CARDS / f"{safe}.md").write_text(Path(p).read_text())
        except Exception as e:  # card missing is not fatal
            status[name + ":card"] = f"ERR {type(e).__name__}: {e}"[:200]
        try:
            configs = get_dataset_config_names(name)
        except Exception as e:
            status[name] = f"ERR configs {type(e).__name__}: {e}"[:200]
            continue
        for cfg in configs:
            try:
                dd = load_dataset(name, cfg)
            except Exception as e:
                status[f"{name}/{cfg}"] = f"ERR load {type(e).__name__}: {e}"[:200]
                continue
            for split, ds in dd.items():
                out = RAW / f"{safe}__{cfg}__{split}.jsonl"
                with open(out, "w") as f:
                    for row in ds:
                        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                status[f"{name}/{cfg}/{split}"] = f"{len(ds)} rows; cols={list(ds.column_names)}"
    # Hendrycks MATH: original archive (read the JSON ourselves; never run its loader script) + EleutherAI mirror
    import zipfile
    try:
        z = hf_hub_download("hendrycks/competition_math", "data/MATH.zip", repo_type="dataset")
        dest = ROOT / "pools/_work/math/MATH"
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(z) as zf:
            names = [n for n in zf.namelist() if n.endswith(".json") and "/test/" in n]
            zf.extractall(dest, members=names)
        status["hendrycks/competition_math:data/MATH.zip"] = f"{len(names)} test json files -> {dest}"
    except Exception as e:
        status["hendrycks/competition_math"] = f"ERR {type(e).__name__}: {e}"[:200]
    for cfg in ["algebra", "counting_and_probability", "geometry", "intermediate_algebra", "number_theory",
                "prealgebra", "precalculus"]:
        try:
            ds = load_dataset("EleutherAI/hendrycks_math", cfg, split="test")
            out = RAW / f"EleutherAI__hendrycks_math__{cfg}__test.jsonl"
            with open(out, "w") as f:
                for row in ds:
                    f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            status[f"EleutherAI/hendrycks_math/{cfg}/test"] = f"{len(ds)} rows; cols={list(ds.column_names)}"
        except Exception as e:
            status[f"EleutherAI/hendrycks_math/{cfg}"] = f"ERR {type(e).__name__}: {e}"[:200]
    (RAW / "_download_status.json").write_text(json.dumps(status, indent=1))
    for k, v in status.items():
        print(k, "->", v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
