"""Signs of life (or not) outside the test suite: CI, docs domains, releases, activity."""
from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

UA = {"User-Agent": "Revenant/0.1 (+https://github.com/Phantom9869/Revenant)"}

DEAD_CI = {
    ".travis.yml": "Travis CI's free travis-ci.org service shut down in 2021; this config no longer runs anywhere.",
    "appveyor.yml": "AppVeyor config (may still run if the project is connected).",
    ".circleci/config.yml": "CircleCI config.",
}
SKIP_HOSTS = {"github.com", "pypi.org", "pypi.python.org", "img.shields.io", "travis-ci.org",
              "www.python.org", "python.org", "docs.python.org", "readthedocs.org", "badge.fury.io",
              "saythanks.io", "www.sphinx-doc.org", "sphinx-doc.org", "en.wikipedia.org", "www.w3.org", "httpbin.org", "example.com"}


@dataclass
class Finding:
    name: str
    status: str        # alive | dead | stale | info
    detail: str
    source: str = ""


def _get(url: str, timeout: int = 12) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(200_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # noqa: BLE001 - any network failure is a finding
        return 0, type(e).__name__ + ": " + str(e)[:120]


def check_ci(repo: Path) -> list[Finding]:
    repo = Path(repo)
    out = []
    workflows = list((repo / ".github" / "workflows").glob("*.y*ml")) if (repo / ".github" / "workflows").exists() else []
    for f, note in DEAD_CI.items():
        if (repo / f).exists():
            out.append(Finding(f"CI: {f}", "dead" if f == ".travis.yml" else "info", note, f))
    if workflows:
        out.append(Finding("CI: GitHub Actions", "alive", ", ".join(w.name for w in workflows)))
    elif not out:
        out.append(Finding("CI", "dead", "No CI configuration found."))
    return out


URL_RE = re.compile(r"https?://[^\s'\"<>)\]`]+")


def doc_hosts(repo: Path, homepage: str | None = None) -> list[str]:
    """Hosts the project itself declares: the GitHub homepage field, packaging metadata,
    Sphinx config, and Read the Docs links in the README."""
    repo = Path(repo)
    meta, readme = "", ""
    for name in ("setup.py", "setup.cfg", "pyproject.toml"):
        if (repo / name).exists():
            meta += (repo / name).read_text(errors="replace")
    for f in repo.glob("docs/**/conf.py"):
        meta += f.read_text(errors="replace")
    for name in ("README.rst", "README.md"):
        if (repo / name).exists():
            readme += (repo / name).read_text(errors="replace")
    urls = ([homepage] if homepage else []) + URL_RE.findall(meta)
    urls += [u for u in URL_RE.findall(readme) if "readthedocs" in u]
    hosts = []
    for url in urls:
        h = urllib.parse.urlparse(url).hostname or ""
        if h and h not in SKIP_HOSTS and not h.endswith("githubusercontent.com") and h not in hosts:
            hosts.append(h)
    return hosts[:6]


def community_hosts(texts, token: str, k: int = 2) -> list[tuple[str, int]]:
    """Hosts named after the project that people keep linking to in the tracker."""
    from collections import Counter
    c = Counter()
    for t in texts:
        for u in URL_RE.findall(t or ""):
            h = urllib.parse.urlparse(u).hostname or ""
            if token.lower() in h.lower() and h not in SKIP_HOSTS:
                c[h] += 1
    return c.most_common(k)


def resolve_cname(host: str) -> list[str]:
    """DNS over HTTPS (the local resolver may be a proxy)."""
    code, body = _get(f"https://dns.google/resolve?name={host}&type=A")
    if code != 200:
        return []
    try:
        return [a["data"].rstrip(".") for a in json.loads(body).get("Answer", [])]
    except (ValueError, KeyError):
        return []


def wayback_last(url: str) -> str:
    code, body = _get("https://archive.org/wayback/available?url=" + urllib.parse.quote(url))
    try:
        snap = json.loads(body)["archived_snapshots"]["closest"]
        return f"{snap['timestamp'][:4]}-{snap['timestamp'][4:6]}-{snap['timestamp'][6:8]} {snap['url']}"
    except (ValueError, KeyError, TypeError):
        return ""


def check_host(host: str, current_version: str | None = None) -> Finding:
    code, body = _get(f"https://{host}/")
    dns = resolve_cname(host)
    title = (re.search(r"<title>([^<]{0,160})", body or "") or [None, ""])[1]
    title = html.unescape(re.sub(r"\s+", " ", title)).strip()
    if 200 <= code < 400:
        m = re.search(r"\bv?(\d+\.\d+(?:\.\d+)?)\b", title)
        if current_version and m and m.group(1) != current_version.lstrip("v"):
            return Finding(f"Docs/site: {host}", "stale",
                           f"HTTP {code}, but the page is titled v{m.group(1)} while the latest release is {current_version} (title: {title})")
        return Finding(f"Docs/site: {host}", "alive", f"HTTP {code}" + (f", title: {title}" if title else ""))
    where = f" DNS: {' -> '.join(dns)}." if dns else " DNS: no records."
    snap = wayback_last(host)
    reason = f"HTTP {code}" if code else (body or "unreachable")
    return Finding(f"Docs/site: {host}", "dead", f"{reason}.{where}" + (f" Last archived snapshot: {snap}" if snap else ""))


def check_pypi(name: str) -> Finding:
    code, body = _get(f"https://pypi.org/pypi/{name}/json")
    if code != 200:
        return Finding("PyPI", "info", f"no PyPI project named {name!r} (HTTP {code})")
    data = json.loads(body)
    rel = data["info"]["version"]
    files = data.get("releases", {}).get(rel, [])
    date = min((f["upload_time"][:10] for f in files), default="?")
    rp = data["info"].get("requires_python") or "unspecified"
    return Finding("PyPI", "stale" if date < "2023" else "alive",
                   f"latest release {name} {rel} on {date}; requires_python: {rp}",
                   f"https://pypi.org/project/{name}/")


def package_name(repo: Path, fallback: str) -> str:
    setup = Path(repo) / "setup.py"
    if setup.exists():
        m = re.search(r"""NAME\s*=\s*['"]([^'"]+)|name\s*=\s*['"]([^'"]+)""", setup.read_text())
        if m:
            return m.group(1) or m.group(2)
    return fallback


def sphinx_release(repo: Path) -> str | None:
    for f in Path(repo).glob("docs/**/conf.py"):
        m = re.search(r"""^release\s*=\s*['"]([^'"]*)['"]""", f.read_text(errors="replace"), re.M)
        if m:
            return f"{f.relative_to(repo).as_posix()}: release = '{m.group(1)}'"
    return None
