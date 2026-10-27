"""The Internet Archive: find and fetch what a dead docs site used to say."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol

UA = {"User-Agent": "Revenant/0.1 (+https://github.com/Phantom9869/Revenant)"}


@dataclass
class Snapshot:
    url: str          # original URL
    timestamp: str    # YYYYMMDDhhmmss
    archive_url: str

    @property
    def raw_url(self) -> str:
        """The archived bytes without the Wayback toolbar (the `id_` flag)."""
        return f"https://web.archive.org/web/{self.timestamp}id_/{self.url}"

    @classmethod
    def parse(cls, archive_url: str) -> "Snapshot | None":
        """A snapshot from a Wayback URL such as https://web.archive.org/web/20190915235734/http://x.org/."""
        m = re.match(r"https?://web\.archive\.org/web/(\d{14})[a-z_]*/(.+)$", archive_url)
        return cls(m[2], m[1], f"https://web.archive.org/web/{m[1]}/{m[2]}") if m else None

    @property
    def date(self) -> str:
        t = self.timestamp
        return f"{t[:4]}-{t[4:6]}-{t[6:8]}"


def _variants(url: str) -> list[str]:
    """The availability API is picky about form; bare hosts often only match with a scheme and slash."""
    out = [url]
    if "://" not in url:
        out.append(f"https://{url.rstrip('/')}/")
    elif not urllib.parse.urlparse(url).path:
        out.append(url + "/")
    return out


def _get_json(url: str, opener, tries: int = 4) -> dict:
    """archive.org rate-limits bursts with HTTP 429; back off and retry."""
    for i in range(tries):
        try:
            with opener(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == tries - 1:
                raise
            time.sleep(5 * 2 ** i)
    return {}


def closest(url: str, timestamp: str | None = None, opener=urllib.request.urlopen) -> Snapshot | None:
    for variant in _variants(url):
        q = "https://archive.org/wayback/available?url=" + urllib.parse.quote(variant)
        if timestamp:
            q += f"&timestamp={timestamp}"
        data = _get_json(q, opener)
        snap = (data.get("archived_snapshots") or {}).get("closest")
        if snap and snap.get("available"):
            return Snapshot(variant, snap["timestamp"], snap["url"])
    return None


class Fetcher(Protocol):
    name: str

    def fetch(self, url: str) -> str: ...


class DirectFetcher:
    name = "direct"

    def fetch(self, url: str) -> str:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return r.read().decode("utf-8", "replace")


class BrowserbaseFetcher:
    """Fetch through Browserbase's Fetch API (POST /v1/fetch). Needs BROWSERBASE_API_KEY."""
    name = "browserbase"
    endpoint = "https://api.browserbase.com/v1/fetch"

    # web.archive.org drops Browserbase's direct fetches (HTTP 500/503 after ~30 s, seen 2026-10-27);
    # the same request with Browserbase's proxies enabled returns the page in ~2 s.
    PROXY_HOSTS = {"web.archive.org"}

    def __init__(self, api_key: str | None = None, proxies: bool | None = None):
        self.proxies = proxies
        self.key = api_key or os.environ.get("BROWSERBASE_API_KEY")
        if not self.key:
            raise RuntimeError("BROWSERBASE_API_KEY is not set")

    def __call__(self, req, timeout):
        return urllib.request.urlopen(req, timeout=timeout)

    def fetch(self, url: str) -> str:
        proxies = self.proxies if self.proxies is not None else urllib.parse.urlparse(url).hostname in self.PROXY_HOSTS
        body = json.dumps({"url": url, "allowRedirects": True, "proxies": proxies}).encode()
        req = urllib.request.Request(self.endpoint, body, {"Content-Type": "application/json",
                                                           "X-BB-API-Key": self.key, **UA})
        try:
            with self(req, timeout=90) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:  # Browserbase's own errors (quota, size, timeout) come back as JSON
            try:
                msg = json.loads(e.read().decode()).get("message", "")
            except Exception:
                msg = ""
            raise RuntimeError(f"Browserbase fetch failed: HTTP {e.code} {msg}".strip()) from None
        if int(data.get("statusCode", 0)) >= 400:
            raise RuntimeError(f"Browserbase fetch returned HTTP {data.get('statusCode')}")
        return data.get("content") or ""


class CachedFetcher:
    """Wrap a fetcher so each URL is fetched at most once; pages are kept on disk.

    Archived snapshots never change, and remote fetch quotas are small.
    """

    def __init__(self, inner: Fetcher, cache_dir: Path):
        self.inner, self.dir = inner, Path(cache_dir)
        self.name = inner.name
        self.hits = self.misses = 0

    def path(self, url: str) -> Path:
        return self.dir / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".html")

    def fetch(self, url: str) -> str:
        p = self.path(url)
        if p.exists():
            self.hits += 1
            return p.read_text(encoding="utf-8")
        self.misses += 1
        text = self.inner.fetch(url)
        self.dir.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        p.with_suffix(".url").write_text(f"{url}\nfetched via {self.inner.name}\n")
        return text


def default_fetcher(cache_dir: Path | None = None) -> Fetcher:
    inner = BrowserbaseFetcher() if os.environ.get("BROWSERBASE_API_KEY") else DirectFetcher()
    return CachedFetcher(inner, cache_dir) if cache_dir else inner


class _Text(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "head"}

    def __init__(self):
        super().__init__()
        self.out, self.depth = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        elif tag in ("p", "div", "li", "h1", "h2", "h3", "pre", "br", "tr"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth:
            self.out.append(data)


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    text = "".join(p.out)
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def archive_docs(snapshot: Snapshot, fetcher: Fetcher):
    """Memory documents for an archived page, citable as [archive:host@date]."""
    from ..memory.ingest import chunks
    from ..memory.store import Doc
    text = html_to_text(fetcher.fetch(snapshot.raw_url))
    host = urllib.parse.urlparse(snapshot.url if "://" in snapshot.url else "https://" + snapshot.url).hostname
    ref = f"archive:{host}@{snapshot.date}"
    return [Doc(id=f"{ref}:{i}", kind="archive", ref=ref, url=snapshot.archive_url,
                title=f"{host} as archived {snapshot.date}", author="", date=snapshot.date, text=part)
            for i, part in enumerate(chunks(text))]
