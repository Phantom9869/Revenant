"""GitHub REST harvesting with an on-disk cache.

Unauthenticated REST allows 60 requests an hour, so every page is cached to disk and
never fetched twice unless asked. Set GITHUB_TOKEN to lift the limit.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterator

API = "https://api.github.com"


class RateLimited(RuntimeError):
    def __init__(self, reset_epoch: int):
        self.reset_epoch = reset_epoch
        when = time.strftime("%H:%M:%S", time.localtime(reset_epoch))
        super().__init__(f"GitHub rate limit reached; resets at {when}")


def _next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        m = re.search(r'<([^>]+)>;\s*rel="next"', part)
        if m:
            return m.group(1)
    return None


class GitHubClient:
    def __init__(self, cache_dir: Path, token: str | None = None, opener=None):
        self.cache_dir = Path(cache_dir) / "github"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        self._open = opener or urllib.request.urlopen
        self.requests_made = 0
        self.cache_hits = 0
        self.remaining: int | None = None

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".json")

    def get(self, url: str, refresh: bool = False) -> tuple[object, str | None]:
        """Return (json_body, next_page_url). Served from cache when possible."""
        if not url.startswith("http"):
            url = API + url
        cp = self._cache_path(url)
        if cp.exists() and not refresh:
            self.cache_hits += 1
            blob = json.loads(cp.read_text())
            return blob["body"], blob.get("next")
        if self.remaining == 0:
            raise RateLimited(int(time.time()) + 3600)
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "Revenant"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with self._open(req, timeout=30) as resp:
                body = json.loads(resp.read().decode())
                hdrs = resp.headers
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and e.headers.get("X-RateLimit-Remaining") == "0":
                raise RateLimited(int(e.headers.get("X-RateLimit-Reset", time.time() + 3600))) from e
            raise
        self.requests_made += 1
        rem = hdrs.get("X-RateLimit-Remaining")
        self.remaining = int(rem) if rem is not None else None
        nxt = _next_link(hdrs.get("Link"))
        cp.write_text(json.dumps({"url": url, "fetched": time.time(), "next": nxt, "body": body}))
        return body, nxt

    def paged(self, path: str, refresh: bool = False) -> Iterator[dict]:
        url: str | None = path
        while url:
            body, url = self.get(url, refresh=refresh)
            if isinstance(body, list):
                yield from body
            else:
                yield body
                return


def harvest(client: GitHubClient, slug: str, out_dir: Path, log=print) -> dict:
    """Fetch issues (incl. PRs), issue comments, PR review comments and PR metadata.

    Writes one JSON file per collection. On a rate limit it keeps what it has and
    reports which collections are partial, so a later run can resume from cache.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = {
        "repo": f"/repos/{slug}",
        "issues": f"/repos/{slug}/issues?state=all&per_page=100&sort=created&direction=asc",
        "issue_comments": f"/repos/{slug}/issues/comments?per_page=100&sort=created&direction=asc",
        "review_comments": f"/repos/{slug}/pulls/comments?per_page=100&sort=created&direction=asc",
        "pulls": f"/repos/{slug}/pulls?state=all&per_page=100&sort=created&direction=asc",
    }
    summary: dict = {"partial": []}
    for name, path in plan.items():
        items: list = []
        try:
            for item in client.paged(path):
                items.append(item)
        except RateLimited as e:
            log(f"  ! {name}: {e} (kept {len(items)} items)")
            summary["partial"].append(name)
        data = items[0] if name == "repo" and items else items
        (out_dir / f"{name}.json").write_text(json.dumps(data))
        summary[name] = 1 if name == "repo" else len(items)
        log(f"  {name:16s} {summary[name]:>5}")
    summary["requests_made"] = client.requests_made
    summary["cache_hits"] = client.cache_hits
    summary["rate_remaining"] = client.remaining
    return summary
