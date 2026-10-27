"""After the tests pass: give the revived project a working CI and honest metadata."""
from __future__ import annotations

import re
from pathlib import Path

from .autopsy import examine
from .sandbox import TestPlan, detect_test_plan

CANDIDATE_PYTHONS = ["3.9", "3.10", "3.11", "3.12", "3.13"]


def verify_matrix(tree: Path, envroot: Path, pythons=CANDIDATE_PYTHONS, log=print) -> dict[str, dict]:
    """Run the suite on each Python; a version only counts if every collected test passes."""
    out = {}
    for py in pythons:
        try:
            exam = examine(tree, envroot / f"py{py}", py, reinstall=True)
            t = exam.tally
            out[py] = dict(t, ok=t["passed"] > 0 and t["failed"] == 0 and t["error"] == 0)
        except RuntimeError as e:
            out[py] = {"ok": False, "error": str(e)[:300]}
        log(f"[Revenant] python {py}: {out[py]}")
    return out


def ci_workflow(plan: TestPlan, pythons: list[str], browser: bool) -> str:
    deps = " ".join(f'"{d}"' if any(c in d for c in "<>=!~") else d for d in plan.deps)
    args = " ".join(f'"{a}"' if " " in a else a for a in plan.args)
    versions = ", ".join(f'"{p}"' for p in pythons)
    steps = [
        "      - uses: actions/checkout@v4",
        "      - uses: actions/setup-python@v5",
        "        with:",
        "          python-version: ${{ matrix.python-version }}",
        f"      - run: python -m pip install -e . {deps}",
    ]
    if browser:
        steps.append("      - run: pyppeteer-install")
    steps.append(f"      - run: python -m pytest {args}".rstrip())
    return "\n".join([
        "name: tests", "", "on:", "  push:", "  pull_request:", "  schedule:",
        "    - cron: \"0 6 * * 1\"   # weekly, so the next death is noticed", "",
        "jobs:", "  test:", "    runs-on: ubuntu-latest", "    strategy:", "      fail-fast: false",
        "      matrix:", f"        python-version: [{versions}]", "    steps:", *steps, ""])


def python_metadata_edits(tree: Path, ok: list[str]) -> list[tuple[str, str, str]]:
    """(path, old, new) replacements for python_requires and version classifiers."""
    setup = tree / "setup.py"
    if not setup.exists() or not ok:
        return []
    text = setup.read_text()
    edits = []
    m = re.search(r"python_requires\s*=\s*['\"]([^'\"]+)['\"]", text)
    if m:
        edits.append(("setup.py", m.group(0), m.group(0).replace(m.group(1), f">={ok[0]}")))
    lines = re.findall(r"^\s*['\"]Programming Language :: Python :: 3\.\d+['\"],?\n", text, re.M)
    if lines:
        indent = re.match(r"^\s*", lines[0]).group(0)
        q = "'" if "'" in lines[0] else '"'
        block = "".join(lines)
        if text.count(block) == 1:
            new = "".join(f"{indent}{q}Programming Language :: Python :: {v}{q},\n" for v in ok)
            edits.append(("setup.py", block, new))
    return edits


def sphinx_release_edit(tree: Path) -> tuple[str, str, str] | None:
    setup = tree / "setup.py"
    if not setup.exists():
        return None
    v = re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]", setup.read_text())
    for conf in tree.glob("docs/**/conf.py"):
        text = conf.read_text()
        m = re.search(r"^release\s*=\s*['\"]([^'\"]*)['\"]", text, re.M)
        if v and m and m.group(1).lstrip("v") != v.group(1):
            return (conf.relative_to(tree).as_posix(), m.group(0), m.group(0).replace(m.group(1), "v" + v.group(1)))
    return None


def dead_badge_edit(tree: Path) -> tuple[str, str, str] | None:
    for name in ("README.rst", "README.md"):
        f = tree / name
        if not f.exists():
            continue
        text = f.read_text()
        m = re.search(r"\.\. image:: https://travis-ci\.(?:org|com)/[^\n]+\n(?:    :target: [^\n]+\n)?\n?", text)
        if m:
            return (name, m.group(0), "")
        m = re.search(r"\[!\[[^\]]*\]\(https://(?:api\.)?travis-ci\.(?:org|com)/[^)]+\)\]\([^)]+\)\n?", text)
        if m:
            return (name, m.group(0), "")
    return None


def run_aftercare(res, pythons=CANDIDATE_PYTHONS, log=print) -> list[str]:
    """Matrix-verify, then commit CI + metadata changes, re-checking the suite after each."""
    from .harvest.gitlog import git
    from .resurrect import commit
    from .surgeon.edits import Edit, Fix, apply_fix

    tree, notes = res.tree, []
    res.matrix = verify_matrix(tree, res.workdir.parent / (res.workdir.name + "-matrix"), pythons, log)
    ok = [p for p in pythons if res.matrix[p].get("ok")]
    plan = detect_test_plan(tree)
    browser = "pyppeteer" in (tree / "setup.py").read_text() if (tree / "setup.py").exists() else False

    def land(title: str, body: str, edits: list[Edit], reinstall: bool = False):
        apply_fix(tree, Fix(title, title, edits, body))
        if reinstall:
            exam = examine(tree, res.workdir, "3.13", reinstall=True)
            if exam.tally["failed"] or exam.tally["error"]:
                from .resurrect import revert
                revert(tree)
                notes.append(f"Skipped: {title} (suite no longer green after it: {exam.tally})")
                return
            res.final = exam
        sha = commit(tree, title, body, paths=sorted({e.path for e in edits}))
        notes.append(f"`{sha}` {title}")
        log(f"[Revenant] aftercare: {title} ({sha})")

    if ok:
        land("Add GitHub Actions CI", f"Runs the offline test suite on Python {', '.join(ok)}, the versions "
             "that passed locally, plus a weekly scheduled run.",
             [Edit(".github/workflows/ci.yml", "", ci_workflow(plan, ok, browser))])
    if (tree / ".travis.yml").exists():
        git(tree, "rm", "-q", ".travis.yml")
        sha = commit(tree, "Remove dead Travis CI config",
                     "travis-ci.org stopped running builds in 2021; CI now lives in GitHub Actions.", paths=[])  # already staged by git rm
        notes.append(f"`{sha}` Remove dead Travis CI config")
    b = dead_badge_edit(tree)
    if b:
        land("Drop the dead Travis badge", "The badge pointed at a CI service that no longer builds this project.",
             [Edit(b[0], b[1], b[2])])
    meta = python_metadata_edits(tree, ok)
    if meta:
        land("Declare the Python versions that actually pass",
             "python_requires and classifiers now match the versions whose test runs passed: " + ", ".join(ok) + ".",
             [Edit(p, o, n) for p, o, n in meta], reinstall=True)
    s = sphinx_release_edit(tree)
    if s:
        land("Label the docs with the package version",
             "The Sphinx release string was still the pre-1.0 value; set it to match setup.py.",
             [Edit(*s)])
    return notes
