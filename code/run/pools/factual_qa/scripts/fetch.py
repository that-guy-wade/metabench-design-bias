"""Fetch every URL cited in the SimpleQA CSV once, store stripped text under pools/_work/factual_qa/pages/<sha256(url)>.txt
and append one terminal record per URL to pools/_work/factual_qa/fetch_log.jsonl. Re-runnable: URLs already in the log are
never re-fetched. Limits: <= 8 concurrent requests overall, <= 2 per host, 20 s timeout, one retry on transport error/5xx/429.
Usage: python -I fetch.py [--limit N]
"""
from __future__ import annotations
import argparse, asyncio, ast, csv, hashlib, json, re, sys, time
from collections import Counter, OrderedDict, deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
import httpx2 as httpx

WORK = Path(__file__).resolve().parents[2] / "_work" / "factual_qa"
CSV = WORK / "simple_qa_test_set.csv"
PAGES = WORK / "pages"
LOG = WORK / "fetch_log.jsonl"
# Wikimedia's robot policy rejects UAs without a contact in this form (plain descriptive UA returned 403).
UA = "MetaBenchPoolAuthor/1.0 (research; contact: pool-author@metabench.invalid)"
GLOBAL_LIMIT, HOST_LIMIT, TIMEOUT, MAX_TEXT, CIRCUIT_FAILURES = 8, 2, 20.0, 2_000_000, 3
BLOCK_TAGS = {"p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section",
              "article", "header", "footer", "ul", "ol", "dd", "dt", "dl", "blockquote", "pre", "title", "caption"}


class Stripper(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template"):
            self.skip += 1
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template") and self.skip:
            self.skip -= 1
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def strip_html(html: str) -> str:
    p = Stripper()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    text = "".join(p.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def url_sha(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def cited_urls() -> list[str]:
    seen, out = set(), []
    with open(CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for u in ast.literal_eval(row["metadata"])["urls"]:
                u = u.strip()
                if u and u not in seen:
                    seen.add(u)
                    out.append(u)
    return out


def request_url(url: str) -> str:
    """Wikipedia article URLs go through the REST v1 Parsoid HTML endpoint (bot-friendly, keeps tables); all else as-is.
    Scheme-less citations such as 'www.example.org/x' are requested over https."""
    if not re.match(r"[a-z][a-z0-9+.-]*://", url) and re.match(r"[\w.-]+\.[a-z]{2,}(/|$)", url):
        url = "https://" + url
    s = urlsplit(url)
    if s.netloc.lower().endswith(".wikipedia.org") and s.path.startswith("/wiki/") and not s.query:
        title = unquote(s.path[len("/wiki/"):])
        if title:
            return f"{s.scheme}://{s.netloc}/api/rest_v1/page/html/{quote(title, safe='')}"
    return s._replace(fragment="").geturl()


async def fetch_one(client: httpx.AsyncClient, url: str) -> dict:
    target = request_url(url)
    rec = {"url": url, "request_url": target, "host": urlsplit(url).netloc.lower(), "url_sha256": url_sha(url),
           "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": None, "error": None,
           "content_type": None, "text_len": 0, "page_sha256": None, "attempts": 0}
    for attempt in (1, 2):
        rec["attempts"] = attempt
        try:
            r = await client.get(target)
        except Exception as e:  # transport error / timeout
            rec["error"] = f"{type(e).__name__}: {str(e)[:120]}"
            continue
        rec["status"], rec["error"] = r.status_code, None
        rec["content_type"] = (r.headers.get("content-type") or "")[:80]
        if r.status_code == 429 or r.status_code >= 500:
            ra = r.headers.get("retry-after", "")
            await asyncio.sleep(min(30.0, float(ra)) if ra.replace(".", "", 1).isdigit() else 5.0)
            continue
        if r.status_code == 200:
            ct = rec["content_type"].lower()
            body = r.content
            if "pdf" in ct or body[:5] == b"%PDF-":
                rec["error"] = "non_text:pdf"
                break
            try:
                raw = r.text
            except Exception:
                raw = body.decode("utf-8", "replace")
            text = raw if ("text/plain" in ct) else strip_html(raw)
            text = text[:MAX_TEXT]
            (PAGES / f"{rec['url_sha256']}.txt").write_text(text, encoding="utf-8")
            rec["text_len"] = len(text)
            rec["page_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        break
    return rec


async def run(urls: list[str]) -> None:
    by_host: "OrderedDict[str, deque]" = OrderedDict()
    for u in urls:
        by_host.setdefault(urlsplit(u).netloc.lower(), deque()).append(u)
    hosts = list(by_host)
    active: Counter = Counter()
    done = [0]
    t0 = time.time()
    lock = asyncio.Lock()
    failures: Counter = Counter()

    def pick() -> str | None:
        # Largest backlog first among hosts with a free per-host slot, so big hosts (en.wikipedia.org) keep
        # their 2 slots busy while the other slots work through the long tail.
        best = max((h for h in hosts if by_host[h] and active[h] < HOST_LIMIT),
                   key=lambda h: len(by_host[h]), default=None)
        if best is None:
            return None
        active[best] += 1
        return by_host[best].popleft()

    async def worker(client, out):
        while True:
            async with lock:
                remaining = any(by_host.values())
                u = pick()
            if u is None:
                if not remaining:
                    return
                await asyncio.sleep(0.2)
                continue
            host = urlsplit(u).netloc.lower()
            if failures[host] >= CIRCUIT_FAILURES:
                rec = {"url": u, "request_url": None, "host": host, "url_sha256": url_sha(u),
                       "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": None,
                       "error": f"skipped:host_circuit_open after {failures[host]} consecutive transport failures",
                       "content_type": None, "text_len": 0, "page_sha256": None, "attempts": 0}
            else:
                rec = await fetch_one(client, u)
                if rec["status"] is None:
                    failures[host] += 1
                else:
                    failures[host] = 0
            async with lock:
                active[rec["host"]] -= 1
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
                done[0] += 1
                if done[0] % 200 == 0:
                    print(f"[fetch] {done[0]}/{len(urls)} in {time.time() - t0:.0f}s", file=sys.stderr, flush=True)

    limits = httpx.Limits(max_connections=GLOBAL_LIMIT, max_keepalive_connections=GLOBAL_LIMIT)
    with open(LOG, "a", encoding="utf-8") as out:
        async with httpx.AsyncClient(headers={"User-Agent": UA}, timeout=TIMEOUT, follow_redirects=True,
                                     limits=limits) as client:
            await asyncio.gather(*(worker(client, out) for _ in range(GLOBAL_LIMIT)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    PAGES.mkdir(parents=True, exist_ok=True)
    logged = set()
    if LOG.exists():  # the latest record per URL is terminal unless it is a 429 (rate-limited; retried on a later pass)
        last = {}
        with open(LOG, encoding="utf-8") as f:
            for l in f:
                if l.strip():
                    r = json.loads(l)
                    last[r["url"]] = r["status"]
        logged = {u for u, st in last.items() if st != 429}
    urls = [u for u in cited_urls() if u not in logged]
    if a.limit:
        urls = urls[:a.limit]
    print(f"[fetch] {len(logged)} already logged; fetching {len(urls)} URLs", file=sys.stderr, flush=True)
    asyncio.run(run(urls))
    return 0


if __name__ == "__main__":
    sys.exit(main())
