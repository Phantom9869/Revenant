"""The web UI: its two themes (head script, toggle, variables, contrast) and the ask endpoint."""
import re
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from revenant.web import app

BUNDLE = Path(__file__).resolve().parent.parent / "deploy" / "bundle"


def _lum(hexcolour: str) -> float:
    c = [int(hexcolour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_contrast_helper_matches_wcag():
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)


@pytest.mark.parametrize("theme", [app.DARK, app.LIGHT], ids=["dark", "light"])
def test_text_colours_meet_wcag_aa(theme):
    text = ["ink", "head", "big", "lede", "why", "answer", "dim", "faint", "candle", "alive", "dead"]
    surfaces = ["bg", "panel", "panel2", "cert-a", "cert-b", "pre-bg", "input-bg", "code-bg"]
    for fg in text:
        for bg in surfaces:
            assert contrast(theme[fg], theme[bg]) >= 4.5, (fg, bg)
    assert contrast(theme["add"], theme["pre-bg"]) >= 4.5
    assert contrast(theme["del"], theme["pre-bg"]) >= 4.5
    assert contrast(theme["btn-ink"], theme["btn-bg"]) >= 4.5


def test_both_themes_define_every_variable_the_css_uses():
    assert app.DARK.keys() == app.LIGHT.keys()
    used = set(re.findall(r"var\(--([a-z0-9-]+)\)", app.CSS))
    assert used <= set(app.DARK) | {"serif", "sans", "mono"}
    assert ":root[data-theme=light]{" in app.CSS
    assert "prefers-color-scheme: light" in app.CSS   # no-JavaScript fallback


def test_page_sets_theme_in_head_before_styles_and_has_toggle():
    html = app.page("Revenant", "<p>hi</p>").decode()
    head_script, style, body = html.index(app.THEME_HEAD), html.index("<style>"), html.index("<body>")
    assert head_script < style < body           # attribute is set before anything paints
    assert "localStorage.getItem('revenant-theme')" in app.THEME_HEAD
    assert "prefers-color-scheme: light" in app.THEME_HEAD
    assert "'dark'" in app.THEME_HEAD           # dark stays the default
    button = re.search(r"<button class=theme[^>]*>", html).group(0)
    assert "aria-label='Switch to light theme'" in button and "type=button" in button
    assert "localStorage.setItem('revenant-theme'" in html
    assert ">Revenant</a>" in html


def test_page_has_no_external_assets():
    html = app.page("Revenant", "").decode()
    assert not re.search(r"(src|href)=['\"]?(https?:)?//", html)
    assert "@import" not in html and "url(" not in app.CSS


@pytest.mark.skipif(not (BUNDLE / "psf__requests-html").exists(), reason="deploy bundle not present")
def test_served_pages_carry_the_toggle(monkeypatch):
    monkeypatch.setenv("REVENANT_HOME", str(BUNDLE))
    server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        for path in ("/", "/p/psf/requests-html", "/p/psf/requests-html/certificate", "/p/psf/requests-html/resurrection"):
            body = urllib.request.urlopen(base + path, timeout=10).read().decode()
            assert "id=theme-toggle" in body and app.THEME_HEAD in body, path
    finally:
        server.shutdown()


@pytest.fixture
def live(monkeypatch):
    """The real server on the committed bundle, with the ghost's model replaced by a stub."""
    if not (BUNDLE / "psf__requests-html").exists():
        pytest.skip("deploy bundle not present")
    from revenant.ghost import Ghost
    from revenant.memory.retrieve import Retriever
    from revenant.memory.store import Memory
    from revenant.models import ChatResult

    class Stub:
        name = "stub"

        def chat(self, messages, **opts):
            return ChatResult(text="I am silent.", model="stub")

    monkeypatch.setenv("REVENANT_HOME", str(BUNDLE))
    db = BUNDLE / "psf__requests-html" / "ghost.db"
    monkeypatch.setattr(app.Handler, "ghosts", {"psf/requests-html": Ghost("requests-html", Retriever(Memory(db)), Stub())})
    server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _post(url, body: bytes, ctype: str, headers: dict | None = None):
    req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as err:
        return err.code, err.read(), err.headers


def test_ask_api_answers_json_and_sends_safe_headers(live):
    import json
    status, body, headers = _post(live + "/p/psf/requests-html/ask", b'{"q": "lxml import error"}', "application/json")
    assert status == 200 and json.loads(body)["model"] == "stub"
    assert headers["X-Content-Type-Options"] == "nosniff"



def test_concurrent_first_questions_build_the_ghost_once(live, monkeypatch):
    import json
    import time

    from revenant import cli
    ghost = app.Handler.ghosts["psf/requests-html"]
    builds = []

    def slow_build(p):
        builds.append(p.slug)
        time.sleep(0.3)   # wide window: without the lock every request would build its own
        return ghost

    monkeypatch.setattr(app.Handler, "ghosts", {})
    monkeypatch.setattr(cli, "build_ghost", slow_build)
    results = []

    def ask():
        results.append(_post(live + "/p/psf/requests-html/ask", b'{"q": "lxml"}', "application/json"))

    threads = [threading.Thread(target=ask) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)
    assert [r[0] for r in results] == [200] * 4
    assert all(json.loads(r[1])["model"] == "stub" for r in results)
    assert builds == ["psf/requests-html"]

@pytest.mark.parametrize("body,ctype", [
    (b"\xff\xfe", "application/x-www-form-urlencoded"),   # not UTF-8
    (b"[1, 2]", "application/json"),                       # JSON, but not an object
    (b'{"q": 5}', "application/json"),                     # q is not a string
    (b"{nope", "application/json"),                        # not JSON
    (b"q=++", "application/x-www-form-urlencoded"),        # empty question
], ids=["bad-utf8", "json-list", "json-number", "bad-json", "empty"])
def test_ask_rejects_malformed_bodies_with_400(live, body, ctype):
    status, _, _ = _post(live + "/p/psf/requests-html/ask", body, ctype)
    assert status == 400


def test_ask_rejects_oversized_bodies(live):
    status, _, _ = _post(live + "/p/psf/requests-html/ask", b"q=" + b"a" * (app.MAX_BODY + 1),
                         "application/x-www-form-urlencoded")
    assert status == 413


def test_unknown_patient_is_404(live):
    status, _, _ = _post(live + "/p/nobody/nothing/ask", b'{"q": "hi"}', "application/json")
    assert status == 404
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(live + "/p/../../etc/passwd", timeout=10)
    assert err.value.code == 404


def test_pages_have_landmarks_labels_and_current_tab():
    from revenant.config import Patient
    html = app.page("x", app.ask_body(Patient("psf/requests-html")), "psf/requests-html", "ask").decode()
    assert "<main>" in html and "</main>" in html
    assert re.search(r"<a href='/p/psf/requests-html/ask' class=on aria-current=page>", html)
    assert html.count("aria-current") == 1
    field = re.search(r"<input name=q[^>]*>", html).group(0)
    assert "aria-label=" in field and "required" in field
