"""Render the PNGs in docs/ with headless Chrome.

  python scripts/screenshots.py url  <url> <out.png> [--height N] [--theme dark|light]   # a page of a running `revenant serve`
  python scripts/screenshots.py compare <dark.png> <light.png> <out.png>   # the two themes side by side
  python scripts/screenshots.py term <capture.txt> <out.png> --title "..." [--lines A:B] [--command "..."]

Terminal images are drawn from real captured output files (demo/*.txt), never retyped.
"""
from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
CHROME = os.environ.get("CHROME") or shutil.which("google-chrome") or shutil.which("chromium") or "chromium"


# The web UI picks its theme from prefers-color-scheme on a first visit (a fresh headless profile
# has no saved choice), so each theme is shot by telling Blink which scheme the "system" prefers.
SCHEME = {"dark": ("0", "0b0c0eff"), "light": ("1", "f4efe4ff")}


def shoot(url: str, out: Path, width: int = 1280, height: int = 900, theme: str = "dark") -> None:
    scheme, background = SCHEME[theme]
    subprocess.run([CHROME, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", f"--window-size={width},{height}",
                    f"--blink-settings=preferredColorScheme={scheme}",
                    f"--default-background-color={background}", f"--screenshot={out}", url],
                   check=True, capture_output=True, timeout=120)
    print(f"wrote {out} ({width}x{height}, {theme})")


def png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def compare(dark: Path, light: Path, out: Path, width: int = 1600) -> None:
    """Two screenshots of the same page, dark on the left and light on the right, with a label on each."""
    w, h = png_size(dark)
    height = round(h * (width / 2) / w)
    doc = ("<!doctype html><meta charset=utf-8><style>body{margin:0;display:flex;height:100vh;font:600 12px/1 sans-serif;"
           "letter-spacing:.2em;text-transform:uppercase}div{flex:1;position:relative;overflow:hidden}"
           "img{width:100%;display:block}span{position:absolute;bottom:16px;padding:7px 11px;border-radius:999px}"
           ".d{background:#0b0c0e}.d span{right:16px;color:#c9a66b;border:1px solid #4a3f2c;background:#111317}"
           ".l{background:#f4efe4;border-left:2px solid #c9a66b}.l span{right:16px;color:#835d1c;border:1px solid #d6bf94;background:#fbf8f1}</style>"
           f"<div class=d><img src='file://{dark.resolve()}'><span>Dark</span></div>"
           f"<div class=l><img src='file://{light.resolve()}'><span>Light</span></div>")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(doc)
    shoot(f"file://{f.name}", out, width, height)
    os.unlink(f.name)


TERM_CSS = """body{margin:0;background:#0b0c0e;padding:28px}
.win{background:#121418;border:1px solid #24272d;border-radius:12px;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.bar{height:38px;display:flex;align-items:center;padding:0 14px;background:#181a1f;border-bottom:1px solid #24272d;position:relative}
.dot{width:12px;height:12px;border-radius:50%;margin-right:8px}
.t{position:absolute;left:0;right:0;text-align:center;font:13px 'IBM Plex Mono',monospace;color:#8f8b82}
pre{margin:0;padding:20px 24px;font:13.5px/1.6 'IBM Plex Mono','DejaVu Sans Mono',monospace;color:#d9d4c7;white-space:pre-wrap}
.cmd{color:#ece6d6;font-weight:600}.cmd b{color:#8db497}.tag{color:#c9a66b}.ok{color:#8db497}.bad{color:#c27f73}
.dim{color:#6f6c66}.h{color:#ece6d6;font-weight:600}"""


def colour(line: str) -> str:
    s = html.escape(line)
    if line.startswith("$ "):
        return f"<span class=cmd><b>$</b> {s[2:]}</span>"
    if line.startswith("#"):
        return f"<span class=h>{s}</span>"
    s = s.replace("[Revenant]", "<span class=tag>[Revenant]</span>").replace("[revenant]", "<span class=tag>[revenant]</span>")
    s = re.sub(r"\b(kept|green|'ok': True|KEPT)\b", r"<span class=ok>\1</span>", s)
    s = re.sub(r"\b(reverted|REVERTED|dead|unappliable|error|failed)\b", r"<span class=bad>\1</span>", s)
    if line.startswith(("  (", "*")):
        s = f"<span class=dim>{s}</span>"
    return s


def term(capture: Path, out: Path, title: str, lines: str | None, command: str | None, width: int) -> None:
    text = capture.read_text().splitlines()
    if lines:
        a, b = (int(x) if x else None for x in lines.split(":"))
        text = text[(a or 1) - 1:b]
    if command:
        text = [f"$ {command}"] + text
    body = "\n".join(colour(l) for l in text)
    doc = (f"<!doctype html><meta charset=utf-8><style>{TERM_CSS}</style><div class=win><div class=bar>"
           "<span class=dot style='background:#c27f73'></span><span class=dot style='background:#c9a66b'></span>"
           f"<span class=dot style='background:#8db497'></span><span class=t>{html.escape(title)}</span></div>"
           f"<pre>{body}</pre></div>")
    per_line = max(40, int((width - 104) / 8.1))   # characters that fit on one line at 13.5px Plex Mono
    height = 38 + 40 + 56 + int(len(text) * 13.5 * 1.6) + sum(len(l) // per_line for l in text) * 22
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(doc)
    shoot(f"file://{f.name}", out, width, height)
    os.unlink(f.name)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("url")
    w.add_argument("url")
    w.add_argument("out")
    w.add_argument("--height", type=int, default=900)
    w.add_argument("--theme", choices=sorted(SCHEME), default="dark")
    c = sub.add_parser("compare")
    c.add_argument("dark", type=Path)
    c.add_argument("light", type=Path)
    c.add_argument("out", type=Path)
    t = sub.add_parser("term")
    t.add_argument("capture", type=Path)
    t.add_argument("out", type=Path)
    t.add_argument("--title", required=True)
    t.add_argument("--lines")
    t.add_argument("--command")
    t.add_argument("--width", type=int, default=1280)
    a = ap.parse_args()
    if a.cmd == "url":
        shoot(a.url, Path(a.out), height=a.height, theme=a.theme)
    elif a.cmd == "compare":
        compare(a.dark, a.light, a.out)
    else:
        term(a.capture, a.out, a.title, a.lines, a.command, a.width)


if __name__ == "__main__":
    main()
