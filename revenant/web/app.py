"""A small, dependency-free web front end for Revenant: patients, death certificates,
resurrection timelines, and the ghost with checked citations. Run with `revenant serve`."""
from __future__ import annotations

import html
import json
import os
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import config
from ..config import Patient

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


# ---------------------------------------------------------------- look and feel

CSS = """
:root{--bg:#0b0c0e;--panel:#111317;--panel2:#15171c;--line:#24272d;--ink:#d9d4c7;--dim:#8f8b82;--faint:#5f5d58;
--candle:#c9a66b;--alive:#8db497;--dead:#c27f73;--serif:"EB Garamond","Iowan Old Style","Palatino Linotype",Palatino,"Book Antiqua",Georgia,serif;
--sans:Inter,-apple-system,"Segoe UI","Helvetica Neue",Arial,sans-serif;--mono:"IBM Plex Mono","JetBrains Mono","SFMono-Regular",Menlo,Consolas,"DejaVu Sans Mono",monospace}
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;color:var(--ink);font:16px/1.6 var(--sans);min-height:100vh;
background:radial-gradient(1200px 520px at 50% -140px,#1b1915 0%,rgba(11,12,14,0) 70%),var(--bg)}
a{color:var(--ink);text-decoration:underline;text-decoration-color:#4a4740;text-underline-offset:3px}
a:hover{text-decoration-color:var(--candle)}
.wrap{max-width:920px;margin:0 auto;padding:0 28px}
header.top{display:flex;align-items:center;justify-content:space-between;padding:22px 0 10px}
.mark{font:600 13px/1 var(--sans);letter-spacing:.32em;text-transform:uppercase;text-decoration:none;color:var(--ink)}
.mark span{color:var(--candle)}
nav.tabs{display:flex;gap:22px;font-size:14px}
nav.tabs a{text-decoration:none;color:var(--dim);padding-bottom:4px;border-bottom:1px solid transparent}
nav.tabs a.on,nav.tabs a:hover{color:var(--ink);border-bottom-color:var(--candle)}
h1,h2,h3{font-family:var(--serif);font-weight:400;color:#ece6d6;letter-spacing:.005em}
h1{font-size:44px;line-height:1.1;margin:.2em 0 .25em}
h2{font-size:26px;margin:1.8em 0 .5em}
h3{font-size:19px;margin:1.4em 0 .3em}
.eyebrow{font-size:12px;letter-spacing:.22em;text-transform:uppercase;color:var(--candle);margin:48px 0 0}
.lede{font:21px/1.55 var(--serif);color:#c9c3b4;max-width:680px}
.dim{color:var(--dim)}.faint{color:var(--faint)}.small{font-size:13px}
code,pre{font-family:var(--mono);font-size:12.5px}
code{background:#181a1f;border:1px solid #22252b;border-radius:4px;padding:.05em .35em}
pre{background:#0e0f12;border:1px solid var(--line);border-radius:8px;padding:14px 16px;overflow:auto;line-height:1.5}
pre code{background:none;border:0;padding:0}
hr{border:0;border-top:1px solid var(--line);margin:40px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;margin:22px 0}
.card{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:12px;padding:18px 20px}
.card h3{margin:0 0 .4em;font-size:18px}
.card .k{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--faint);margin:0 0 6px}
a.card{display:block;text-decoration:none}
a.card:hover{border-color:#3a3730}
.big{font:400 34px/1.1 var(--serif);color:#efe9da}
.big .arrow{color:var(--faint);margin:0 .25em;font-size:26px}
.pill{display:inline-block;font:600 10.5px/1 var(--sans);letter-spacing:.14em;text-transform:uppercase;padding:5px 8px;border-radius:999px;border:1px solid}
.pill.kept,.pill.alive,.pill.supported{color:var(--alive);border-color:#35473b}
.pill.reverted,.pill.dead,.pill.unsupported,.pill.withheld{color:var(--dead);border-color:#4d3430}
.pill.unappliable,.pill.stale,.pill.uncited{color:var(--candle);border-color:#4a3f2c}
.bar{display:flex;height:6px;border-radius:3px;overflow:hidden;background:#1b1d22;margin:8px 0 4px;min-width:120px}
.bar i{display:block}.bar .p{background:var(--alive)}.bar .f{background:var(--dead)}.bar .e{background:var(--candle)}
.tally{font:12px/1.4 var(--mono);color:var(--dim)}
table{border-collapse:collapse;width:100%;font-size:14px;margin:12px 0}
td,th{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
tr:first-child td{color:var(--dim);font-size:12px;letter-spacing:.08em;text-transform:uppercase}
.certificate{border:1px solid #3a352b;border-radius:4px;padding:34px 40px;margin:26px 0;
background:linear-gradient(180deg,#131210,#0f0f0e);box-shadow:inset 0 0 0 6px #0f0f0e,inset 0 0 0 7px #2a2620}
.certificate h1{font-size:32px;text-align:center;margin-top:0}
.certificate h1+p{text-align:center;color:var(--dim)}
.timeline{position:relative;margin:30px 0 10px;padding-left:28px}
.timeline:before{content:"";position:absolute;left:6px;top:6px;bottom:6px;width:1px;background:linear-gradient(var(--line),#3a352b,var(--line))}
.step{position:relative;margin:0 0 26px}
.step:before{content:"";position:absolute;left:-27px;top:7px;width:11px;height:11px;border-radius:50%;background:var(--bg);border:1px solid var(--faint)}
.step.kept:before{border-color:var(--alive);background:#1a2a20}
.step.reverted:before,.step.unappliable:before{border-color:var(--dead)}
.step.start:before{border-color:var(--dead);background:#2a1715}.step.end:before{border-color:var(--alive);background:var(--alive)}
.step h3{margin:0 0 4px;font-size:18px}
.step .meta{font-size:13px;color:var(--dim)}
.step .why{margin:6px 0;color:#c7c1b3;font-size:15px}
.change{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:6px 0}
.change .bar{width:150px}
details summary{cursor:pointer;color:var(--dim);font-size:13px;margin-top:6px}
pre.diff .add{color:#9cc5a6}pre.diff .del{color:#d08f84}pre.diff .hunk{color:var(--faint)}
form.ask{display:flex;gap:10px;margin:18px 0 8px}
form.ask input{flex:1;font:16px var(--sans);padding:13px 16px;border-radius:10px;border:1px solid #2c2f36;background:#0e1013;color:var(--ink);outline:none}
form.ask input:focus{border-color:#57503f}
form.ask button{font:600 14px var(--sans);letter-spacing:.04em;padding:0 20px;border-radius:10px;border:1px solid #4a4130;background:#1b1812;color:#e8d8b6;cursor:pointer}
form.ask button[disabled]{opacity:.5}
.examples a{display:inline-block;margin:4px 8px 4px 0;font-size:13px;color:var(--dim);border:1px solid var(--line);border-radius:999px;padding:4px 11px;text-decoration:none}
.examples a:hover{color:var(--ink);border-color:#3a3730}
.question{font:italic 20px/1.5 var(--serif);color:var(--dim);margin:28px 0 6px}
.answer{font:21px/1.6 var(--serif);color:#e6e0d1;border-left:2px solid var(--candle);padding:4px 0 4px 22px;margin:8px 0 22px}
.answer sup a{font:600 11px var(--sans);color:var(--candle);text-decoration:none;margin-left:1px}
.answer.refused{border-left-color:var(--faint);color:var(--dim)}
.sources li{margin:6px 0;font-size:14px}.sources .ref{font-family:var(--mono);color:var(--candle);margin-right:8px}
.checks li{margin:6px 0;font-size:14px;color:#c7c1b3}.checks .pill{margin-right:8px}
.checks li.withheld{color:var(--dim)}.checks li.withheld q{text-decoration:line-through;text-decoration-color:#6b4b45}
.spirit{display:none;color:var(--dim);font-style:italic;font-family:var(--serif)}
footer{margin:70px 0 40px;color:var(--faint);font-size:12.5px;border-top:1px solid var(--line);padding-top:16px}
"""

JS = """document.querySelectorAll('form.ask').forEach(f=>f.addEventListener('submit',()=>{
const b=f.querySelector('button');b.disabled=true;b.textContent='listening';
const s=document.querySelector('.spirit');if(s)s.style.display='block';}));"""

EXAMPLES = ["Why does importing requests_html fail with lxml 5.2?",
            "How do I close an HTMLSession and the browser it started?",
            "Who created you, and when was your last release?",
            "Why did test_containing start expecting 192 elements?"]

e = html.escape


def _json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def page(title: str, body: str, slug: str | None = None, tab: str = "") -> bytes:
    nav = ""
    if slug:
        links = [("", "Overview"), ("certificate", "Certificate"), ("resurrection", "Resurrection"), ("ask", "Ask the ghost")]
        nav = "<nav class=tabs>" + "".join(
            f"<a href='/p/{e(slug)}{'/' + k if k else ''}' class='{'on' if k == tab else ''}'>{v}</a>" for k, v in links) + "</nav>"
    return (f"<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{e(title)}</title><style>{CSS}</style><body><div class=wrap>"
            f"<header class=top><a class=mark href='/'>Revenant</a>{nav}</header>{body}"
            f"<footer>Revenant reads a project's own history, runs its own tests in a network-less sandbox, and keeps only "
            f"changes that make them pass. The ghost speaks only from cited records.</footer></div><script>{JS}</script></body></html>").encode()


def tally_bar(t: dict | None) -> str:
    if not t:
        return "<span class=faint>not run</span>"
    p, f, er = t.get("passed", 0), t.get("failed", 0), t.get("error", 0)
    n = max(p + f + er, 1)
    bar = (f"<div class=bar><i class=p style='width:{100 * p / n:.1f}%'></i><i class=f style='width:{100 * f / n:.1f}%'></i>"
           f"<i class=e style='width:{100 * er / n:.1f}%'></i></div>")
    return f"<div>{bar}<div class=tally>{p} passed · {f} failed · {er} errors</div></div>"


def facts(p: Patient) -> dict:
    """Everything the pages show, read from the patient's own reports."""
    autopsy = _json(p.reports / "autopsy.json") or {}
    res = _json(p.reports / "resurrection.json")
    cert = (p.reports / "death_certificate.md")
    cert_md = cert.read_text() if cert.exists() else ""
    m = re.search(r"\*\*Last commit:\*\*.*? on (\d{4}-\d{2}-\d{2})", cert_md)
    first = re.search(r"\*\*First commit:\*\*.*? on (\d{4}-\d{2}-\d{2})", cert_md)
    causes = re.findall(r"^### \d+\. (.+)$", cert_md.split("## Cause of death")[-1], re.M) if "## Cause of death" in cert_md else []
    commits = re.search(r"\*\*Commits:\*\* (\d+)", cert_md)
    return {"autopsy": autopsy, "res": res, "cert_md": cert_md, "last_commit": m and m.group(1),
            "first_commit": first and first.group(1), "causes": causes, "commits": commits and commits.group(1),
            "before": autopsy.get("tally") or (res or {}).get("initial"), "after": (res or {}).get("final")}


def patients() -> list[Patient]:
    root = config.home()
    if not root.exists():
        return []
    return [Patient(d.name.replace("__", "/", 1)) for d in sorted(root.iterdir()) if (d / "ghost.db").exists()]


def _arrow(f: dict) -> str:
    b, a = f["before"], f["after"]
    if not b:
        return "<span class=faint>not examined</span>"
    return (f"<span class=big>{b.get('passed', 0)}<span class=arrow>→</span>{a.get('passed', 0) if a else '?'}</span>"
            f"<div class='small dim'>tests passing, before → after</div>")


def home_body() -> str:
    cards = []
    for p in patients():
        f = facts(p)
        cause = f["causes"][0] if f["causes"] else "cause unknown"
        cards.append(f"<a class=card href='/p/{e(p.slug)}'><p class=k>on the table</p><h3>{e(p.slug)}</h3>"
                     f"<p class='small dim'>last commit {e(f['last_commit'] or '?')} · {e(cause)}</p>{_arrow(f)}</a>")
    empty = "<p class=dim>No one has been summoned yet. Run <code>revenant summon owner/repo</code>.</p>"
    return ("<p class=eyebrow>A séance for abandoned open-source software</p><h1>Revenant</h1>"
            "<p class=lede>Revenant gathers a dead project's memory from its own commits, issues and archived docs, "
            "performs an autopsy to find out why it died, and brings it back one tested, reversible change at a time. "
            "Its ghost answers questions about its past, and every claim it makes is cited and checked against the record.</p>"
            f"<h2>The séance room</h2><div class=grid>{''.join(cards) or empty}</div>")


def overview_body(p: Patient) -> str:
    f = facts(p)
    res = f["res"] or {}
    kept = [a for a in res.get("attempts", []) if a["verdict"] == "kept"]
    matrix = res.get("matrix") or {}
    green = [py for py, t in matrix.items() if isinstance(t, dict) and t.get("ok")]
    causes = "".join(f"<li>{e(c)}</li>" for c in f["causes"]) or "<li class=dim>no autopsy yet</li>"
    ex = "".join(f"<a href='/p/{e(p.slug)}/ask?q={urllib.parse.quote(q)}'>{e(q)}</a>" for q in EXAMPLES)
    return (f"<p class=eyebrow>Patient</p><h1>{e(p.slug)}</h1>"
            f"<p class=dim>Born {e(f['first_commit'] or '?')} · last commit {e(f['last_commit'] or '?')} · "
            f"{e(f['commits'] or '?')} commits · <a href='https://github.com/{e(p.slug)}'>github.com/{e(p.slug)}</a></p>"
            "<div class=grid>"
            f"<a class=card href='/p/{e(p.slug)}/certificate'><p class=k>Death certificate</p><h3>Cause of death</h3><ul class=small>{causes}</ul>"
            f"{tally_bar(f['before'])}</a>"
            f"<a class=card href='/p/{e(p.slug)}/resurrection'><p class=k>Resurrection</p>{_arrow(f)}"
            f"<p class='small dim'>{len(kept)} change(s) kept" + (f" · green on Python {e(', '.join(green))}" if green else "") + "</p></a>"
            "</div>"
            f"<h2>Ask the ghost</h2><form class=ask method=get action='/p/{e(p.slug)}/ask'><input name=q placeholder='Ask about its past…' autocomplete=off>"
            f"<button>Ask</button></form><div class=examples>{ex}</div>")


def diff_html(d: str) -> str:
    out = []
    for line in d.splitlines():
        cls = "hunk" if line.startswith(("@@", "---", "+++")) else "add" if line.startswith("+") else "del" if line.startswith("-") else ""
        out.append(f"<span class='{cls}'>{e(line)}</span>" if cls else e(line))
    return "<pre class=diff>" + "\n".join(out) + "</pre>"


def resurrection_body(p: Patient) -> str:
    res = _json(p.reports / "resurrection.json")
    if not res:
        log = p.reports / "RESURRECTION_LOG.md"
        return md_to_html(log.read_text()) if log.exists() else "<p class=dim>Not performed yet.</p>"
    steps = [f"<div class='step start'><h3>Pronounced dead</h3><p class=meta>Python 3.13, today's dependencies, "
             f"network-less sandbox</p>{tally_bar(res['initial'])}</div>"]
    for a in res["attempts"]:
        cites = ""
        if a.get("citations"):
            cites = "<p class='small dim'>History cited: " + ", ".join(
                f"<a href='https://github.com/{e(p.slug)}/commit/{e(c)}'><code>{e(c)}</code></a>" for c in a["citations"]) + "</p>"
        commit = f" · committed as <code>{e(a['commit'])}</code>" if a.get("commit") else ""
        steps.append(
            f"<div class='step {e(a['verdict'])}'><h3>{e(a['title'])}</h3>"
            f"<p class=meta><span class='pill {e(a['verdict'])}'>{e(a['verdict'])}</span> &nbsp;source: {e(a['source'])}{commit}</p>"
            f"<p class=why>{e(a['why'])}</p>{cites}"
            f"<div class=change>{tally_bar(a.get('before'))}<span class=faint>→</span>{tally_bar(a.get('after'))}</div>"
            f"<p class='small dim'>{e(a['reason'])}</p>"
            + (f"<details><summary>the change</summary>{diff_html(a['diff'])}</details>" if a.get("diff") else "") + "</div>")
    steps.append(f"<div class='step end'><h3>Alive again</h3><p class=meta>after {len(res['attempts'])} operation(s), "
                 f"{res.get('wall_seconds', '?')} s</p>{tally_bar(res['final'])}</div>")
    matrix = ""
    if res.get("matrix"):
        rows = "".join(
            f"<tr><td>Python {e(py)}</td><td>{t.get('passed', '-')}</td><td>{t.get('failed', '-')}</td><td>{t.get('error', '-')}</td>"
            f"<td><span class='pill {'kept' if t.get('ok') else 'reverted'}'>{'green' if t.get('ok') else 'red'}</span></td></tr>"
            for py, t in res["matrix"].items() if isinstance(t, dict))
        matrix = f"<h2>Python matrix</h2><table><tr><td>python</td><td>passed</td><td>failed</td><td>errors</td><td></td></tr>{rows}</table>"
    after = "".join(f"<li>{e(n)}</li>" for n in res.get("aftercare") or [])
    return (f"<p class=eyebrow>Resurrection · {e(res.get('date', ''))}</p><h1>{e(p.slug)}</h1>"
            f"<p class=lede>Each change was applied as an exact edit to a local fork, then the project's own test suite was "
            f"re-run in a network-less sandbox. Changes that didn't help, or broke a passing test, were reverted.</p>"
            f"<div class=timeline>{''.join(steps)}</div>{matrix}" + (f"<h2>Aftercare</h2><ul>{after}</ul>" if after else ""))


def answer_html(ans, slug: str) -> str:
    urls = dict(ans.sources())

    def cite(m):
        refs = [r.strip() for r in m.group(1).split(",")]
        return "".join(f"<sup><a href='{e(urls[r])}' title='{e(r)}'>[{e(r)}]</a></sup>" if r in urls else "" for r in refs)

    text = re.sub(r"\[([^\[\]]{1,80})\]", cite, e(ans.text))
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    titles = {}
    for h in ans.hits:
        titles.setdefault(h.doc.ref, h.doc)
    srcs = "".join(
        f"<li><span class=ref>[{e(r)}]</span><a href='{e(u)}'>{e((titles[r].title or u)[:110])}</a> "
        f"<span class='faint small'>{e(titles[r].kind)}{', ' + e(titles[r].date[:10]) if titles[r].date else ''}</span></li>"
        for r, u in ans.sources())
    checks = ""
    if ans.claims:
        items = []
        for c in ans.claims:
            if c.verdict == "uncited":
                continue
            if c.verdict == "supported":
                items.append(f"<li><span class='pill supported'>supported</span><q>{e(c.sentence[:180])}</q> "
                             f"<span class='faint small'>by {e(', '.join(c.supported_by))}</span></li>")
            else:
                why = f"not in any cited record: {', '.join(c.missing)}" if c.missing else f"shares {c.overlap:.0%} of its words with {', '.join(c.refs)}"
                items.append(f"<li class=withheld><span class='pill withheld'>withheld</span><q>{e(c.sentence[:180])}</q> "
                             f"<span class='faint small'>{e(why)}</span></li>")
        extra = (f"<p class='small dim'>Citation removed as not supporting its sentence: {e(', '.join(ans.unsupported))}</p>"
                 if ans.unsupported and not ans.withheld else "")
        checks = f"<h3>Citation check</h3><ul class=checks>{''.join(items)}</ul>{extra}"
    meta = f"{e(ans.model)} · {ans.seconds:.1f} s" + (f" · {ans.prompt_tokens} in / {ans.completion_tokens} out tokens" if ans.prompt_tokens else "")
    if ans.cost_usd is not None:
        meta += f" · reported cost ${ans.cost_usd:.6f}"
    return (f"<p class=question>“{e(ans.question)}”</p>"
            f"<div class='answer{' refused' if ans.refused else ''}'>{text}</div>"
            + (f"<p class='small dim'>{e(ans.reason)}</p>" if ans.refused and ans.reason else "")
            + (f"<h3>Sources</h3><ul class=sources>{srcs}</ul>" if srcs else "") + checks
            + f"<p class='faint small'>{meta}</p>")


def ask_body(p: Patient, q: str = "", answer: str = "") -> str:
    ex = "".join(f"<a href='/p/{e(p.slug)}/ask?q={urllib.parse.quote(x)}'>{e(x)}</a>" for x in EXAMPLES)
    return (f"<p class=eyebrow>The ghost of {e(p.slug.split('/')[1])}</p><h1>Ask about its past</h1>"
            "<p class=lede>It answers only from its own commits, issues, reviews and docs. Every sentence must cite a record "
            "it was shown, and each citation is checked against that record's text. When the records are silent, so is the ghost.</p>"
            f"<form class=ask method=post action='/p/{e(p.slug)}/ask'><input name=q value='{e(q)}' placeholder='Ask about its past…' autocomplete=off>"
            f"<button>Ask</button></form><div class=examples>{ex}</div>"
            "<p class=spirit>The ghost is going through its records…</p>" + answer)


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
            return self._send(200, page("Revenant", home_body()))
        m = re.fullmatch(r"/p/([^/]+/[^/]+?)(?:/(certificate|resurrection|ask))?/?", u.path)
        if m and (p := self._patient(m.group(1))):
            which = m.group(2) or ""
            if which == "certificate":
                f = p.reports / "death_certificate.md"
                body = (f"<article class=certificate>{md_to_html(f.read_text())}</article>" if f.exists()
                        else "<p class=dim>No autopsy yet.</p>")
            elif which == "resurrection":
                body = resurrection_body(p)
            elif which == "ask":
                q = urllib.parse.parse_qs(u.query).get("q", [""])[0][:500]
                body = ask_body(p, q)
            else:
                body = overview_body(p)
            return self._send(200, page(f"{p.slug} · Revenant", body, p.slug, which))
        self._send(404, page("Revenant", "<h1>Nothing haunts this address.</h1>"))

    def do_POST(self):
        m = re.fullmatch(r"/p/([^/]+/[^/]+)/ask", urllib.parse.urlparse(self.path).path)
        p = m and self._patient(m.group(1))
        if not p:
            return self._send(404, b"not found", "text/plain")
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(min(n, 10_000)).decode()
        wants_json = "json" in (self.headers.get("Content-Type") or "")
        try:
            q = ((lambda d: d.get("q") or d.get("question") or "")(json.loads(raw)) if wants_json
                 else urllib.parse.parse_qs(raw).get("q", [""])[0]).strip()[:500]
        except ValueError:
            return self._send(400, b"bad request", "text/plain")
        if not q:
            return self._send(400, b"empty question", "text/plain")
        from ..cli import build_ghost
        from ..integrations import tracing
        ghost = self.ghosts.get(p.slug) or self.ghosts.setdefault(p.slug, build_ghost(p))
        with tracing.transaction("POST /p/<slug>/ask", op="http.server"):
            try:
                ans = ghost.ask(q)
            except Exception as ex:  # model server down, out of credit, ...
                msg = f"The séance was interrupted: {type(ex).__name__}: {str(ex)[:300]}"
                if wants_json:
                    return self._send(502, json.dumps({"error": msg}).encode(), "application/json")
                return self._send(502, page("Revenant", ask_body(p, q, f"<p class=dim>{e(msg)}</p>"), p.slug, "ask"))
        if wants_json:
            return self._send(200, json.dumps({"answer": ans.text, "refused": ans.refused, "reason": ans.reason,
                                               "sources": ans.sources(), "unsupported": ans.unsupported,
                                               "claims": [c.as_dict() for c in ans.claims], "model": ans.model}).encode(),
                              "application/json")
        self._send(200, page(f"{p.slug} · Revenant", ask_body(p, q, answer_html(ans, p.slug)), p.slug, "ask"))

    def log_message(self, fmt, *a):
        pass


def serve(host: str = "127.0.0.1", port: int | None = None):
    port = int(port or os.environ.get("PORT", 8000))
    print(f"Revenant web on http://{host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
