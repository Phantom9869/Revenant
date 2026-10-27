"""Why does requests-html's test_containing expect 192 elements when it finds 191?

Run with a Python environment that has requests-html's dependencies installed
(for example the venv Revenant builds under <patient>/fork-env/venv):

    python demo/investigations/191_vs_192.py <path-to-requests-html-clone> [--lxml 4.9.4 5.1.1 ...]

1. History: which commits wrote each number into the test.
2. The fixture: has tests/python.html ever changed?
3. Today: what every historical version of requests_html.py returns on that fixture.
4. Optional: the same count under different lxml releases (needs `uv`).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

TEST = "tests/test_requests_html.py"
FIXTURE = "tests/python.html"
COUNT = ("import sys; sys.path.insert(0, sys.argv[1]); from requests_html import HTML; "
         "print(len(HTML(html=open(sys.argv[2], 'rb').read()).find(containing='python')))")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--lxml", nargs="*", default=[])
    ap.add_argument("--python", default="3.12", help="Python for the lxml matrix")
    a = ap.parse_args()
    repo = Path(a.repo)

    print("== 1. Who wrote which number ==")
    for n in ("191", "192"):
        out = git(repo, "log", "--reverse", f"-S== {n}", "--format=%h %ad %an: %s", "--date=short", "--", TEST)
        print(f"commits adding/removing '== {n}':")
        print("".join(f"   {l}\n" for l in out.splitlines()) or "   none\n")
    intro = git(repo, "log", "--reverse", "-S== 192", "--format=%H", "--", TEST).split()[0]
    merged = git(repo, "log", "--ancestry-path", "--merges", "--reverse", "--format=%h %ad %s", "--date=short",
                 f"{intro}..HEAD").splitlines()[:1]
    print(f"   '== 192' reached the main line via: {merged[0] if merged else 'unknown'}\n")

    print("== 2. Has the fixture changed? ==")
    print(git(repo, "log", "--format=   %h %ad %s", "--date=short", "--", FIXTURE), end="")
    raw = (repo / FIXTURE).read_bytes()
    print(f"   {FIXTURE}: {len(raw)} bytes, non-ASCII bytes: {sum(b > 127 for b in raw)}\n")

    print("== 3. Every historical requests_html.py, today's dependencies ==")
    shas = git(repo, "log", "--reverse", "--format=%h", "--", "requests_html.py").split()
    first_test = git(repo, "log", "--reverse", "-S== 191", "--format=%h", "--", TEST).split()[0]

    def before_test(sha):
        return subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", sha, first_test]).returncode == 0 \
            and sha != first_test
    results = Counter()
    odd = []
    with tempfile.TemporaryDirectory() as tmp:
        fixture = Path(tmp) / "python.html"
        fixture.write_bytes(raw)
        for sha in shas:
            d = Path(tmp) / sha
            d.mkdir()
            (d / "requests_html.py").write_text(git(repo, "show", f"{sha}:requests_html.py"))
            r = subprocess.run([sys.executable, "-c", COUNT, str(d), str(fixture)], capture_output=True, text=True,
                               timeout=120, env=dict(os.environ, PYTHONWARNINGS="ignore"))
            key = r.stdout.strip() if r.returncode == 0 else "import/run error"
            results[key] += 1
            if key not in ("191", "import/run error"):
                odd.append((sha, key, before_test(sha)))
    import lxml
    from lxml import etree
    print(f"   python {sys.version.split()[0]}, lxml {lxml.__version__}, libxml2 {'.'.join(map(str, etree.LIBXML_VERSION))}")
    print(f"   {len(shas)} versions -> " + ", ".join(f"{k}: {v}" for k, v in results.most_common()))
    for sha, k, early in odd:
        when = git(repo, "log", "-1", "--format=%ad %s", "--date=short", sha).strip()
        note = f" (older than {first_test}, the commit that added test_containing)" if early else ""
        print(f"   {sha} -> {k}: {when}{note}")
    print()

    if a.lxml:
        print(f"== 4. lxml matrix (HEAD code, Python {a.python}) ==")
        head = Path(tempfile.mkdtemp())
        (head / "requests_html.py").write_text(git(repo, "show", "HEAD:requests_html.py"))
        (head / "python.html").write_bytes(raw)
        for v in a.lxml:
            deps = ["--with", f"lxml=={v}", "--with", "requests", "--with", "pyquery", "--with", "fake-useragent",
                    "--with", "parse", "--with", "beautifulsoup4", "--with", "w3lib", "--with", "pyppeteer"]
            if int(v.split(".")[0]) >= 5 and v >= "5.2":
                deps += ["--with", "lxml_html_clean"]
            r = subprocess.run(["uv", "run", "-q", "--no-project", "--python", a.python, *deps, "python", "-c",
                                COUNT, str(head), str(head / "python.html")], capture_output=True, text=True, timeout=600)
            print(f"   lxml {v}: {r.stdout.strip() if r.returncode == 0 else 'failed: ' + r.stderr.strip()[-160:]}")
        print()

    print("== Verdict ==")
    later_odd = [o for o in odd if not o[2]]
    print(f"   Versions that produced 192: {results.get('192', 0)}.")
    if later_odd:
        print(f"   {len(later_odd)} version(s) since the test existed gave something other than 191; see above.")
    else:
        print("   Every version since test_containing existed that still runs today finds 191.")
    print("   The fixture is unchanged since 2018-02-26, so 192 could not be reproduced here;")
    print("   restoring the original 191 is the change the project's own history supports.")


if __name__ == "__main__":
    main()
