"""Download the canonical SimpleQA CSV into pools/_work/factual_qa/ and print its sha256. Re-runnable: skips if present."""
from __future__ import annotations
import hashlib, sys
from pathlib import Path
import httpx2 as httpx

URL = "https://openaipublic.blob.core.windows.net/simple-evals/simple_qa_test_set.csv"
WORK = Path(__file__).resolve().parents[2] / "_work" / "factual_qa"
DEST = WORK / "simple_qa_test_set.csv"


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    if not DEST.exists():
        r = httpx.get(URL, timeout=60, follow_redirects=True,
                      headers={"User-Agent": "MetaBenchPoolAuthor/1.0 (research; contact: pool-author)"})
        r.raise_for_status()
        DEST.write_bytes(r.content)
    sha = hashlib.sha256(DEST.read_bytes()).hexdigest()
    (WORK / "simple_qa_test_set.csv.sha256").write_text(sha + "\n")
    print(DEST, DEST.stat().st_size, sha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
