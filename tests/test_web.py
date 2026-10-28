"""The web UI's two themes: the head script, the toggle, the variables and their contrast."""
import re
import threading
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
