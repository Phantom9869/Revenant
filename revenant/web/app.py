"""A small, dependency-free web front end: patients, death certificates, resurrection
logs, and a form to ask the ghost. Run with `revenant serve`."""
from __future__ import annotations

import html
import json
import os
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import config
from ..config import Patient

CSS = """body{background:#0d0f12;color:#d7d3c8;font:16px/1.55 Georgia,serif;max-width:860px;margin:2rem auto;padding:0 1rem}
a{color:#9fc4a8}h1,h2,h3{font-weight:normal;color:#e9e4d6}code,pre{font:13px/1.45 ui-monospace,monospace;background:#16191e}
pre{padding:.8rem;overflow:auto}table{border-collapse:collapse;font-size:14px}td,th{border:1px solid #2a2f36;padding:.25rem .5rem}
input[type=text]{width:75%;padding:.5rem;background:#16191e;color:#eee;border:1px solid #333}button{padding:.5rem 1rem}
.ans{border-left:3px solid #6b8f71;padding:.5rem 1rem;margin:1rem 0}.muted{color:#888;font-size:14px}"""


def md_to_html(md: str) -> str:
    """Just enough Markdown for our own reports: headings, lists, tables, code, links."""
    out, in_code, in_table, in_list = [], False, False, False

    def inline(t: str) -> str:
        t = html.escape(t)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", t)
        return re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', t)

    for line in md.splitlines():
        if line.startswith("```"):
            out.append("</pre>" if in_code else "<pre>")
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(re.fullmatch(r"-+", c) for c in cells):
                continue
            if not in_table:
                out.append("<table>")
                in_table = True
            out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        m = re.match(r"(#{1,4}) (.*)", line)
        if m:
            n = len(m.group(1))
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    if in_table:
        out.append("</table>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def patients() -> list[Patient]:
    root = config.home()
    if not root.exists():
        return []
    return [Patient(d.name.replace("__", "/", 1)) for d in sorted(root.iterdir()) if (d / "ghost.db").exists()]


def page(title: str, body: str) -> bytes:
    return (f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>"
            f"<style>{CSS}</style><p class=muted><a href='/'>revenant</a></p>{body}").encode()


class Handler(BaseHTTPRequestHandler):
    ghosts: dict = {}

    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _patient(self, slug: str) -> Patient | None:
        return next((p for p in patients() if p.slug == slug), None)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/healthz":
            return self._send(200, b"ok", "text/plain")
        if u.path == "/":
            items = "".join(f"<li><a href='/p/{p.slug}'>{p.slug}</a></li>" for p in patients())
            return self._send(200, page("revenant", "<h1>The séance room</h1><p>Summoned projects:</p>"
                                        f"<ul>{items or '<li>none yet: run <code>revenant summon owner/repo</code></li>'}</ul>"))
        m = re.fullmatch(r"/p/([^/]+/[^/]+)(?:/(certificate|resurrection))?", u.path)
        if m and (p := self._patient(m.group(1))):
            which = m.group(2)
            if which:
                f = p.reports / ("death_certificate.md" if which == "certificate" else "RESURRECTION_LOG.md")
                body = md_to_html(f.read_text()) if f.exists() else "<p>Not performed yet.</p>"
                return self._send(200, page(p.slug, body))
            body = (f"<h1>{html.escape(p.slug)}</h1><p><a href='/p/{p.slug}/certificate'>death certificate</a> · "
                    f"<a href='/p/{p.slug}/resurrection'>resurrection log</a></p>"
                    f"<form method=post action='/p/{p.slug}/ask'><input type=text name=q placeholder='Ask the ghost…'>"
                    f" <button>ask</button></form>")
            return self._send(200, page(p.slug, body))
        self._send(404, page("not found", "<p>Nothing haunts this address.</p>"))

    def do_POST(self):
        m = re.fullmatch(r"/p/([^/]+/[^/]+)/ask", urllib.parse.urlparse(self.path).path)
        p = m and self._patient(m.group(1))
        if not p:
            return self._send(404, b"not found", "text/plain")
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(min(n, 10_000)).decode()
        wants_json = "json" in (self.headers.get("Content-Type") or "")
        q = ((lambda d: d.get("q") or d.get("question") or "")(json.loads(raw)) if wants_json else urllib.parse.parse_qs(raw).get("q", [""])[0]).strip()[:500]
        if not q:
            return self._send(400, b"empty question", "text/plain")
        from ..cli import build_ghost
        ghost = self.ghosts.setdefault(p.slug, build_ghost(p))
        from ..integrations import tracing
        with tracing.transaction("POST /p/<slug>/ask", op="http.server"):
            ans = ghost.ask(q)
        if wants_json:
            return self._send(200, json.dumps({"answer": ans.text, "refused": ans.refused,
                                               "sources": ans.sources()}).encode(), "application/json")
        srcs = "".join(f"<li><a href='{html.escape(u)}'>[{html.escape(r)}]</a></li>" for r, u in ans.sources())
        body = (f"<h1>{html.escape(p.slug)}</h1><p class=muted>{html.escape(q)}</p>"
                f"<div class=ans>{html.escape(ans.text)}</div><ul>{srcs}</ul><p><a href='/p/{p.slug}'>ask another</a></p>")
        self._send(200, page(p.slug, body))

    def log_message(self, fmt, *a):
        pass


def serve(host: str = "127.0.0.1", port: int | None = None):
    port = int(port or os.environ.get("PORT", 8000))
    print(f"revenant web on http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
