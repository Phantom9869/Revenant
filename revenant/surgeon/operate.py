"""The LLM surgeon: for failures the grimoire can't cure, ask a local code model for
exact SEARCH/REPLACE edits against the real file text."""
from __future__ import annotations

import re
from pathlib import Path

from ..diagnose import Outcome, locate
from .edits import Edit, EditError, Fix, parse_blocks, relax_trailing_newline

SYSTEM = """You are a careful maintainer reviving an old Python project so its existing test suite passes on a modern Python and modern dependencies.
Make the smallest correct change. Prefer fixing the library over weakening tests. Never delete or skip tests, never change expected values unless the evidence proves the expectation is wrong.
Reply ONLY with one or more edit blocks in exactly this format, nothing else:

FILE: {path}
<<<<<<< SEARCH
exact lines copied from the file shown to you
=======
replacement lines
>>>>>>> REPLACE

The SEARCH text must be copied character-for-character from the file excerpt, including indentation, and must be unique in the file.
You may only edit these files: {files}."""


def window(path: Path, line: int, radius: int = 30) -> str:
    lines = path.read_text(errors="replace").splitlines()
    lo, hi = max(0, line - radius - 1), min(len(lines), line + radius)
    return "\n".join(lines[lo:hi])


def test_source(root: Path, test_id: str) -> tuple[str, str] | None:
    mod, _, name = test_id.partition("::")
    name = name.split("::")[-1].split("[")[0]
    f = root / (mod.replace(".", "/") + ".py")
    if not f.exists() or not name:
        return None
    text = f.read_text()
    m = re.search(rf"^(@[^\n]*\n)*(async )?def {re.escape(name)}\(.*?(?=^\S|\Z)", text, re.S | re.M)
    return (f.relative_to(root).as_posix(), m.group(0).rstrip()) if m else None


def build_prompt(root: Path, failure: Outcome, feedback: str = "") -> tuple[str, set[str]]:
    root = Path(root)
    parts, shown = [], set()
    detail = failure.detail.strip()
    parts.append(f"Failing test: {failure.test}\nError: {failure.message[:300]}\n\nTraceback (tail):\n{detail[-2500:]}")
    ts = test_source(root, failure.test)
    if ts:
        parts.append(f"Test source ({ts[0]}):\n{ts[1]}")
        shown.add(ts[0])
    loc = locate(failure.detail)
    if loc:
        path, _, ln = loc.rpartition(":")
        p = root / path
        if not p.exists():
            p = next(iter(root.rglob(Path(path).name)), None)
        if p and p.exists():
            rel = p.relative_to(root).as_posix()
            parts.append(f"Excerpt of {rel} around line {ln}:\n{window(p, int(ln))}")
            shown.add(rel)
    if re.search(r"ImportError|ModuleNotFoundError|No module named", detail) and (root / "setup.py").exists():
        text = (root / "setup.py").read_text(errors="replace")
        m = re.search(r"^.*(REQUIRED|install_requires).*$", text, re.M)
        if m:
            ln = text[:m.start()].count("\n") + 1
            parts.append(f"Excerpt of setup.py around line {ln} (dependencies):\n{window(root / 'setup.py', ln, 6)}")
            shown.add("setup.py")
    if feedback:
        parts.append(f"Your previous answer could not be applied: {feedback}\nCopy the SEARCH text exactly from the excerpt.")
    return "\n\n".join(parts), shown


def propose(model, root: Path, failure: Outcome, feedback: str = "") -> tuple[Fix | None, str, float]:
    """Returns (fix or None, raw model text, seconds). Edits are checked against the real
    files here; anything that doesn't match exactly is rejected before it touches disk."""
    prompt, shown = build_prompt(root, failure, feedback)
    system = SYSTEM.format(path=sorted(shown)[0] if shown else "module.py", files=", ".join(sorted(shown)) or "none")
    res = model.chat([{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                     temperature=0.1)
    edits = [relax_trailing_newline(root, e) for e in parse_blocks(res.text)]
    good = []
    for e in edits:
        if e.path not in shown:
            raise EditError(f"model tried to edit a file it was not shown: {e.path}")
        n = (Path(root) / e.path).read_text().count(e.search)
        if n != 1:
            raise EditError(f"SEARCH block for {e.path} matched {n} times, need exactly 1")
        if e.search == e.replace:
            continue
        good.append(e)
    if not good:
        return None, res.text, res.seconds
    name = failure.test.split("::")[-1]
    return (Fix(f"surgeon:{name}", f"Surgeon's edit for {name}", good,
                f"Proposed by {model.name} for: {failure.message[:160]}", source=f"surgeon:{model.name}",
                reinstall=any(e.path in ("setup.py", "setup.cfg", "pyproject.toml") for e in good)),
            res.text, res.seconds)
