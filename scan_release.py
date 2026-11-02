#!/usr/bin/env python3
"""Leak scan for the MetaBench release package.

Scans every file under a directory, including members of .tar.gz / .tgz archives and
.gz files, for credential patterns and infrastructure identifiers. Matching is done on
raw bytes, so binary files are covered too.

Exit status: 0 when every hit is covered by the allowlist, 1 otherwise.

Usage:
    python scan_release.py [ROOT] [--allowlist scan_allowlist.json] [--extra-patterns FILE]

--extra-patterns takes a file with one regular expression per line (lines starting with
'#' are ignored). Use it for organisation-specific names that should not themselves be
published in this script.

Credential-like matches are printed masked (first 4 characters and length only).
"""

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import sys
import tarfile
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

SECRET_PATTERNS = {
    "openai_or_anthropic_key": rb"(?<![A-Za-z0-9])sk-(?:proj-|ant-|svcacct-)?[A-Za-z0-9_\-]{20,}",
    "xai_key": rb"xai-[A-Za-z0-9]{20,}",
    "google_api_key": rb"AIza[0-9A-Za-z_\-]{30,}",
    "aws_access_key": rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "github_token": rb"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}",
    "slack_token": rb"xox[abposr]-[A-Za-z0-9-]{10,}",
    "bearer_token": rb"Bearer\s+[A-Za-z0-9\-._~+/]{16,}=*",
    "private_key_block": rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY|-----BEGIN PGP PRIVATE",
    "aws_secret_assignment": rb"(?i)aws_secret_access_key\s*[=:]\s*\S{20,}",
}

INFRA_PATTERNS = {
    "home_path": rb"/home/[A-Za-z0-9_.\-]+",
    "macos_user_path": rb"/Users/[A-Za-z0-9_.\-]+",
    "root_home_path": rb"(?<![A-Za-z0-9_.])/root/",
    "dev_shm_path": rb"/dev/shm",
    "project_path": rb"(?<![A-Za-z0-9_.\-])/project/",
    "tmp_path": rb"(?<![A-Za-z0-9_.\-])/tmp/[A-Za-z0-9_.\-]+",
    "aws_arn": rb"arn:aws",
    "s3_uri": rb"s3://",
    "s3_bucket_host": rb"[A-Za-z0-9.\-]+\.s3[.\-][A-Za-z0-9.\-]*amazonaws\.com",
    "aws_account_id": rb"(?i)(?:account[^\n]{0,40}(?<!\d)\d{12}(?!\d)|(?<!\d)\d{12}(?!\d)[^\n]{0,40}account|(?<!\d)\d{12}\.dkr\.ecr)",
    "email": rb"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}",
    "gcp_project_id": rb"\b[a-z]{3,}-[a-z]{3,}-\d{6}\b|projects/[a-z][a-z0-9\-]{4,28}[a-z0-9]/locations",
    "ipv4": rb"(?<![\d.])(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}(?![\d.])",
}

CONTEXT = 50
SECRET_TEXT = [re.compile(rx.decode()) for rx in SECRET_PATTERNS.values()]


def mask_secrets(text):
    """Context snippets never show a credential-shaped string, even next to another hit."""
    for rx in SECRET_TEXT:
        text = rx.sub("<masked>", text)
    return text


def compile_patterns(extra_file):
    pats = {}
    for name, rx in {**SECRET_PATTERNS, **INFRA_PATTERNS}.items():
        pats[name] = re.compile(rx)
    if extra_file:
        for i, line in enumerate(Path(extra_file).read_text().splitlines()):
            line = line.strip()
            if line and not line.startswith("#"):
                pats[f"extra_{i}"] = re.compile(line.encode(), re.IGNORECASE)
    return pats


PREFILTER = {  # cheap literal test before running a pattern's regex (None: always run)
    "openai_or_anthropic_key": [b"sk-"], "xai_key": [b"xai-"], "google_api_key": [b"AIza"],
    "aws_access_key": [b"AKIA", b"ASIA"], "github_token": [b"gh", b"github_pat_"], "slack_token": [b"xox"],
    "bearer_token": [b"earer"], "private_key_block": [b"-----BEGIN"], "aws_secret_assignment": [b"ws_secret", b"WS_SECRET"],
    "home_path": [b"/home/"], "macos_user_path": [b"/Users/"], "root_home_path": [b"/root/"],
    "dev_shm_path": [b"/dev/shm"], "project_path": [b"/project/"], "tmp_path": [b"/tmp/"], "aws_arn": [b"arn:aws"],
    "s3_uri": [b"s3://"], "s3_bucket_host": [b"amazonaws"], "email": [b"@"],
}


def iter_blobs(path, rel):
    """Yield (display_path, bytes) for a file, or for every member of an archive."""
    name = path.name
    if name.endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(path, "r:*") as tf:
            for m in tf:
                yield f"{rel}::<name>", m.name.encode()  # member names can leak paths too
                if m.isfile():
                    yield f"{rel}::{m.name}", tf.extractfile(m).read()
    elif name.endswith(".gz"):
        with gzip.open(path, "rb") as fh:
            yield f"{rel}::<gunzip>", fh.read()
    else:
        yield rel, path.read_bytes()


_PATS = None


def _init(extra_file):
    global _PATS
    _PATS = compile_patterns(extra_file)


def scan_file(job):
    """Return (n_blobs, n_bytes, [(pattern, path, matched, context)]) for one file."""
    path, rel = job
    out, n, nb = [], 0, 0
    for disp, data in iter_blobs(Path(path), rel):
        n += 1
        nb += len(data)
        for name, rx in _PATS.items():
            lits = PREFILTER.get(name)
            if lits and not any(l in data for l in lits):
                continue
            for m in rx.finditer(data):
                a, b = max(0, m.start() - CONTEXT), min(len(data), m.end() + CONTEXT)
                out.append((name, disp, m.group(0).decode("latin-1"),
                            mask_secrets(data[a:b].decode("utf-8", "replace")).replace("\n", "\\n")))
    return n, nb, out


def load_allowlist(path):
    """Allowlist entries: {"pattern", "sha256" (of the matched text), "path" (regex on the reported path), "why"}.
    Matches are stored hashed so the allowlist itself never contains the strings it excuses."""
    if not path or not Path(path).exists():
        return []
    entries = json.loads(Path(path).read_text())
    for e in entries:
        e["_path"] = re.compile(e.get("path", ".*"))
    return entries


def allowed(entries, pattern, path, matched):
    h = hashlib.sha256(matched.encode("latin-1")).hexdigest()
    for e in entries:
        if e["pattern"] == pattern and e["sha256"] == h and e["_path"].search(path):
            e["used"] = e.get("used", 0) + 1
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=str(Path(__file__).resolve().parent))
    ap.add_argument("--allowlist", default=None)
    ap.add_argument("--extra-patterns", default=None)
    ap.add_argument("--max-print", type=int, default=200)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = ap.parse_args()
    root = Path(args.root).resolve()
    allowlist_path = args.allowlist or (root / "scan_allowlist.json")
    allow = load_allowlist(allowlist_path)
    self_path = Path(__file__).resolve()

    files = [(str(p), str(p.relative_to(root))) for p in sorted(root.rglob("*"))
             if p.is_file() and p.resolve() != self_path]  # this file contains the patterns themselves
    hits, allowed_hits, n_blobs, n_bytes = [], Counter(), 0, 0
    with Pool(args.jobs, initializer=_init, initargs=(args.extra_patterns,)) as pool:
        results = pool.imap(scan_file, sorted(files, key=lambda f: -Path(f[0]).stat().st_size), chunksize=4)
        for n, nb, found in results:
            n_blobs += n
            n_bytes += nb
            for name, path, s, ctx in found:
                if allowed(allow, name, path, s):
                    allowed_hits[name] += 1
                    continue
                if name in SECRET_PATTERNS:
                    s, ctx = f"{s[:4]}...(len {len(s)})", ""
                hits.append((name, path, s, ctx))
    hits.sort()

    by_pat = Counter(h[0] for h in hits)
    print(f"scanned {n_blobs} files/members, {n_bytes / 1e6:.1f} MB")
    print(f"allowlisted hits: {dict(allowed_hits)}")
    print(f"UNRESOLVED hits: {len(hits)} {dict(by_pat)}")
    for h in hits[: args.max_print]:
        print(f"  [{h[0]}] {h[1]} :: {h[2]!r}  ctx={h[3]!r}")
    unused = [f'{e["pattern"]}:{e["sha256"][:12]}' for e in allow if not e.get("used")]
    if unused:
        print(f"allowlist entries never used (consider removing): {unused}")
    sys.exit(1 if hits else 0)


if __name__ == "__main__":
    main()
