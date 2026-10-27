"""Turn raw test failures into named causes of death."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Outcome:
    test: str
    status: str               # passed | failed | error | skipped
    message: str = ""
    detail: str = ""


@dataclass
class Rule:
    id: str
    title: str
    pattern: str
    layer: str                # what changed in the world
    witnesses: str = ""       # search terms for issues that reported it
    fix: str | None = None    # grimoire fix id


RULES: list[Rule] = [
    Rule("lxml-html-clean", "lxml.html.clean was split out of lxml",
         r"lxml\.html\.clean module is now a separate project|No module named 'lxml\.html\.clean'",
         "lxml 5.2.0 (2024) moved lxml.html.clean into the separate lxml_html_clean package; "
         "importing it from lxml raises ImportError.",
         "lxml clean import", "lxml-html-clean"),
    Rule("no-current-event-loop", "asyncio.get_event_loop() no longer conjures a loop",
         r"There is no current event loop",
         "Code calls asyncio.get_event_loop() outside a running loop and expects one to be created. "
         "That implicit creation was deprecated across Python 3.10-3.12 and removed in 3.14; under a "
         "modern pytest-asyncio there is no current loop, so it raises RuntimeError.",
         "event loop", "asyncio-loop"),
    Rule("event-loop-fixture", "pytest-asyncio removed the event_loop fixture",
         r"fixture 'event_loop' not found",
         "pytest-asyncio 1.0 (2025) removed the long-deprecated event_loop fixture that async tests "
         "requested by name.",
         "event_loop fixture pytest", "pytest-asyncio-event-loop"),
    Rule("asyncio-coroutine", "@asyncio.coroutine is gone",
         r"module 'asyncio' has no attribute 'coroutine'",
         "Generator-based coroutines (@asyncio.coroutine) were removed in Python 3.11.", "asyncio coroutine", None),
    Rule("collections-abc", "ABCs left the collections module",
         r"cannot import name '(\w+)' from 'collections'",
         "Aliases like collections.Mapping were removed in Python 3.10; they live in collections.abc.",
         "collections Mapping", "collections-abc"),
    Rule("imp-removed", "the imp module was removed", r"No module named 'imp'",
         "The imp module was removed in Python 3.12.", "imp module", "imp"),
    Rule("distutils-removed", "distutils was removed", r"No module named 'distutils'",
         "distutils was removed from the standard library in Python 3.12.", "distutils", None),
    Rule("werkzeug-cached-property", "werkzeug stopped re-exporting cached_property",
         r"cannot import name 'cached_property' from 'werkzeug'",
         "werkzeug 1.0 (2020) stopped exposing cached_property at the top level.", "werkzeug cached_property",
         "werkzeug-cached-property"),
    Rule("assertion-drift", "a hard-coded expectation no longer matches",
         r"assert (\d+) == (\d+)",
         "A test pins an exact number. The code, a dependency, or the expectation itself moved.",
         "", "history-assertion"),
]


@dataclass
class Symptom:
    rule: Rule
    tests: list[str] = field(default_factory=list)
    evidence: str = ""
    location: str = ""


def parse_junit(path: Path) -> list[Outcome]:
    path = Path(path)
    if not path.exists():
        return []
    root = ET.parse(path).getroot()
    out = []
    for tc in root.iter("testcase"):
        name = (tc.get("classname", "") + "::" + tc.get("name", "")).strip(":")
        status, msg, detail = "passed", "", ""
        for tag in ("failure", "error", "skipped"):
            el = tc.find(tag)
            if el is not None:
                status = {"failure": "failed"}.get(tag, tag)
                msg, detail = el.get("message", "") or "", el.text or ""
                break
        out.append(Outcome(name, status, msg, detail))
    return out


def tally(outcomes: list[Outcome]) -> dict[str, int]:
    t = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for o in outcomes:
        t[o.status] = t.get(o.status, 0) + 1
    return t


LOC = re.compile(r"^([\w./\-]+\.py):(\d+):", re.M)


def locate(detail: str) -> str:
    """Best guess at the project line where it broke: last non-test frame, else last frame."""
    frames = [f"{m.group(1)}:{m.group(2)}" for m in LOC.finditer(detail)
              if "site-packages" not in m.group(1) and "/lib/python" not in m.group(1)]
    non_test = [f for f in frames if not re.search(r"(^|/)tests?/|test_", f)]
    return (non_test or frames or [""])[-1]


def first_line(text: str, pattern: str) -> str:
    for line in text.splitlines():
        if re.search(pattern, line):
            return line.strip()[:240]
    return ""


def classify(outcomes: list[Outcome], raw_output: str = "", rules: list[Rule] = RULES) -> tuple[list[Symptom], list[Outcome]]:
    """Group failing outcomes by rule. Returns (symptoms, unexplained)."""
    found: dict[str, Symptom] = {}
    unexplained = []
    for o in outcomes:
        if o.status not in ("failed", "error"):
            continue
        blob = o.message + "\n" + o.detail
        for r in rules:
            if re.search(r.pattern, blob):
                s = found.setdefault(r.id, Symptom(r))
                s.tests.append(o.test)
                s.evidence = s.evidence or first_line(blob, r.pattern)
                s.location = s.location or locate(o.detail)
                break
        else:
            unexplained.append(o)
    # A suite that can't even import may produce no testcases at all.
    if not outcomes and raw_output:
        for r in rules:
            if re.search(r.pattern, raw_output):
                found[r.id] = Symptom(r, ["<collection>"], first_line(raw_output, r.pattern), locate(raw_output))
    return list(found.values()), unexplained
