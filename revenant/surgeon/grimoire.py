"""The grimoire: known cures for known causes of death.

Each cure reads the real files and proposes exact edits; nothing here is a template
pasted blindly. A cure returns None when the file doesn't look the way it expects.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..diagnose import Symptom
from ..harvest.gitlog import git, pickaxe
from .edits import Edit, Fix

LOOP_HELPER = '''

def _get_event_loop():
    """Return the running loop, else this thread's loop, creating one if needed.

    asyncio.get_event_loop() stopped creating loops implicitly in modern Python.
    """
    import warnings
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        pass
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            loop = asyncio.get_event_loop()
        if not loop.is_closed():
            return loop
    except RuntimeError:
        pass
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop

'''


def _project_py(root: Path) -> list[Path]:
    skip = {"tests", "test", "docs", "build", "dist", ".git", "venv", ".venv"}
    out = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root).parts
        if rel[0] in skip or p.name.startswith("test_") or p.name in ("setup.py", "conftest.py"):
            continue
        out.append(p)
    return out


def _requirements_edit(root: Path, add: str) -> Edit | None:
    """Add a requirement to setup.py's install_requires list (literal or named)."""
    setup = root / "setup.py"
    if not setup.exists():
        return None
    text = setup.read_text()
    if add in text:
        return None
    m = re.search(r"(REQUIRED|install_requires)\s*=\s*\[(?P<body>[^\]]*)\]", text)
    if not m:
        return None
    body = m.group("body")
    quote = "'" if "'" in body else '"'
    new_body = body.rstrip() + f", {quote}{add}{quote}" + ("\n" if body.endswith("\n") else "")
    if body.rstrip().endswith(","):
        new_body = body.rstrip() + f" {quote}{add}{quote}," + ("\n" if body.endswith("\n") else "")
    return Edit("setup.py", m.group(0), m.group(0).replace(body, new_body, 1))


def cure_lxml_html_clean(root: Path, s: Symptom) -> Fix | None:
    e = _requirements_edit(root, "lxml_html_clean")
    if not e:
        return None
    return Fix("lxml-html-clean", "Depend on lxml_html_clean", [e],
               "lxml>=5.2 only re-exports lxml.html.clean when the separate lxml_html_clean package "
               "is installed, so declaring it restores the import without pinning an old lxml.",
               reinstall=True)


def cure_asyncio_loop(root: Path, s: Symptom) -> Fix | None:
    edits = []
    for p in _project_py(root):
        text = p.read_text()
        n = text.count("asyncio.get_event_loop()")
        if not n or "def _get_event_loop" in text:
            continue
        rel = p.relative_to(root).as_posix()
        m = list(re.finditer(r"^(?:import [^\n]+|from [^\n]+ import [^\n]+)\n", text, re.M))
        if not m:
            continue
        last_import = m[-1].group(0)
        if text.count(last_import) != 1:
            continue
        # one edit for the helper, then all call sites in a single pass
        new_text = text.replace("asyncio.get_event_loop()", "_get_event_loop()")
        new_text = new_text.replace(last_import, last_import + LOOP_HELPER, 1)
        edits.append(Edit(rel, text, new_text))
    if not edits:
        return None
    return Fix("asyncio-loop", "Stop relying on asyncio.get_event_loop() to create loops", edits,
               "Replace implicit loop creation with a helper that uses the running loop, else the "
               "thread's loop, else creates and sets a new one.")


def cure_event_loop_fixture(root: Path, s: Symptom) -> Fix | None:
    """Sync fixtures that took `event_loop` just to be created on the test's loop become
    async fixtures (they then run on the test's loop by construction)."""
    edits = []
    for p in sorted(root.rglob("test*.py")) + sorted(root.rglob("conftest.py")):
        text = p.read_text()
        pat = re.compile(r"@pytest\.fixture(\([^)]*\))?\ndef (\w+)\(event_loop\):\n")
        if not pat.search(text):
            continue
        new = pat.sub(lambda m: f"@pytest_asyncio.fixture{m.group(1) or ''}\nasync def {m.group(2)}():\n", text)
        if "import pytest_asyncio" not in new:
            new = re.sub(r"^import pytest\n", "import pytest\nimport pytest_asyncio\n", new, count=1, flags=re.M)
        edits.append(Edit(p.relative_to(root).as_posix(), text, new))
    if not edits:
        return None
    return Fix("pytest-asyncio-event-loop", "Turn event_loop-dependent fixtures into async fixtures", edits,
               "pytest-asyncio 1.0 removed the event_loop fixture. An async fixture is created inside "
               "the running test loop, which is what requesting event_loop used to guarantee.")


def cure_collections_abc(root: Path, s: Symptom) -> Fix | None:
    m = re.search(r"cannot import name '(\w+)' from 'collections'", s.evidence)
    if not m:
        return None
    name = m.group(1)
    edits = []
    for p in _project_py(root):
        text = p.read_text()
        old = f"from collections import {name}\n"
        if text.count(old) == 1:
            edits.append(Edit(p.relative_to(root).as_posix(), old, f"from collections.abc import {name}\n"))
    return Fix("collections-abc", f"Import {name} from collections.abc", edits,
               "The collections ABC aliases were removed in Python 3.10.") if edits else None


def cure_werkzeug_cached_property(root: Path, s: Symptom) -> Fix | None:
    edits = []
    for p in _project_py(root):
        text = p.read_text()
        old = "from werkzeug import cached_property\n"
        if text.count(old) == 1:
            edits.append(Edit(p.relative_to(root).as_posix(), old, "from werkzeug.utils import cached_property\n"))
    return Fix("werkzeug-cached-property", "Import cached_property from werkzeug.utils", edits,
               "werkzeug 1.0 stopped re-exporting cached_property at the package top level.") if edits else None


def cure_history_assertion(root: Path, s: Symptom, clone: Path | None = None) -> list[Fix]:
    """For `assert got == expected` failures: if the project's own history once asserted
    the value we now observe, restore it and cite the commits. Never invent a number."""
    fixes = []
    m = re.search(r"assert (\d+) == (\d+)", s.evidence)
    if not m:
        return fixes
    got, expected = m.group(1), m.group(2)
    history = clone or root
    for test in s.tests:
        test_file = None
        mod = test.split("::")[0]
        cand = root / (mod.replace(".", "/") + ".py")
        if cand.exists():
            test_file = cand
        if not test_file:
            continue
        rel = test_file.relative_to(root).as_posix()
        text = test_file.read_text()
        lines = [l for l in text.splitlines() if re.search(rf"==\s*{expected}\b", l)]
        if len(lines) != 1:
            continue
        line = lines[0]
        changed = pickaxe(history, f"== {expected}", rel)
        if not changed:
            continue
        intro = changed[0]  # oldest commit that touched "== expected"
        prev = git(history, "show", f"{intro.sha}^:{rel}", check=False)
        old_line = line.replace(f"== {expected}", f"== {got}")
        if old_line not in prev:
            continue
        origin = [c for c in pickaxe(history, f"== {got}", rel) if c.sha != intro.sha]
        origin = origin[:1]  # oldest commit that wrote "== got"
        cites = ([origin[0].short] if origin else []) + [intro.short]
        fixes.append(Fix(
            f"history-assertion:{test.split('::')[-1]}",
            f"Restore the original expectation in {test.split('::')[-1]} ({expected} -> {got})",
            [Edit(rel, line + "\n", old_line + "\n")],
            f"The test now observes {got}. The project's own history asserted {got} first"
            + (f" (commit {origin[0].short}, {origin[0].date[:10]}, {origin[0].author}, \"{origin[0].subject}\")" if origin else "")
            + f"; commit {intro.short} ({intro.date[:10]}, {intro.author}, \"{intro.subject}\") changed it to {expected}.",
            source="history", citations=cites))
    return fixes


CURES = {
    "lxml-html-clean": cure_lxml_html_clean,
    "asyncio-loop": cure_asyncio_loop,
    "pytest-asyncio-event-loop": cure_event_loop_fixture,
    "collections-abc": cure_collections_abc,
    "werkzeug-cached-property": cure_werkzeug_cached_property,
}


def prescribe(root: Path, symptoms: list[Symptom], clone: Path | None = None) -> list[Fix]:
    out = []
    for s in symptoms:
        if s.rule.fix == "history-assertion":
            out.extend(cure_history_assertion(root, s, clone))
        elif s.rule.fix in CURES:
            f = CURES[s.rule.fix](Path(root), s)
            if f:
                out.append(f)
    return out
