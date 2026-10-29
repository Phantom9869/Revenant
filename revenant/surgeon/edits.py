"""Exact, verifiable text edits. An edit that doesn't match the real file is refused."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path


class EditError(ValueError):
    pass


@dataclass
class Edit:
    path: str            # relative to the tree
    search: str          # exact text currently in the file ('' means create a new file)
    replace: str
    count: int = 1       # how many occurrences must exist (all are replaced)


@dataclass
class Fix:
    id: str
    title: str
    edits: list[Edit]
    why: str
    source: str = "grimoire"          # grimoire | history | surgeon:<model>
    citations: list[str] = field(default_factory=list)
    reinstall: bool = False           # packaging metadata changed
    deps: list[str] = field(default_factory=list)   # extra test-only deps


def _inside(root: Path, rel: str) -> Path:
    """The resolved path of `rel` under `root`; EditError if it points outside the tree."""
    root = Path(root).resolve()
    path = (root / rel).resolve()
    if root not in path.parents:
        raise EditError(f"refusing to edit outside the tree: {rel}")
    return path


def apply_edit(root: Path, e: Edit) -> str:
    """Apply one edit in place and return a unified diff. Raises EditError on mismatch."""
    path = _inside(root, e.path)
    if e.search == "":
        if path.exists():
            raise EditError(f"{e.path} already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(e.replace)
        return "".join(difflib.unified_diff([], e.replace.splitlines(True), "/dev/null", f"b/{e.path}"))
    if not path.exists():
        raise EditError(f"no such file: {e.path}")
    before = path.read_text()
    found = before.count(e.search)
    if found != e.count:
        raise EditError(f"search text found {found}x in {e.path}, expected {e.count}x")
    after = before.replace(e.search, e.replace)
    path.write_text(after)
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                        f"a/{e.path}", f"b/{e.path}"))


def apply_fix(root: Path, fix: Fix) -> str:
    """All-or-nothing: if any edit fails, files touched so far are restored."""
    backups: dict[Path, str | None] = {}
    diffs = []
    try:
        for e in fix.edits:
            p = _inside(root, e.path)   # check before backing up, so nothing outside is read or rewritten
            if p not in backups:
                backups[p] = p.read_text() if p.exists() else None
            diffs.append(apply_edit(root, e))
    except EditError:
        for p, text in backups.items():
            if text is None:
                p.unlink(missing_ok=True)
            else:
                p.write_text(text)
        raise
    return "".join(diffs)


BLOCK = re.compile(
    r"^FILE:\s*(?P<path>\S+)\s*\n<<<<<<< SEARCH\n(?P<search>.*?)\n?=======\n(?P<replace>.*?)\n?>>>>>>> REPLACE",
    re.S | re.M)


def parse_blocks(text: str) -> list[Edit]:
    """Parse SEARCH/REPLACE blocks:

    FILE: path/to/file.py
    <<<<<<< SEARCH
    exact old lines
    =======
    new lines
    >>>>>>> REPLACE
    """
    text = re.sub(r"```[a-zA-Z]*\n?", "", text)
    edits = []
    for m in BLOCK.finditer(text):
        search, replace = m.group("search"), m.group("replace")
        if search.strip() == "":
            continue  # no blind file creation from a model
        edits.append(Edit(m.group("path").strip("`"), search + "\n", replace + "\n" if replace else ""))
    return edits


def relax_trailing_newline(root: Path, e: Edit) -> Edit:
    """Models often drop the final newline of a block; match without it if that's unique."""
    try:
        p = _inside(root, e.path)
    except EditError:
        return e   # apply_edit refuses it with the proper message
    if p.is_file():
        text = p.read_text()
        if text.count(e.search) == 0 and e.search.endswith("\n") and text.count(e.search[:-1]) == 1:
            return Edit(e.path, e.search[:-1], e.replace[:-1] if e.replace.endswith("\n") else e.replace)
    return e
