"""The resurrection loop: diagnose, cure one thing, re-run the tests, keep or revert, repeat."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .autopsy import Examination, examine, fresh_tree
from .config import Patient
from .harvest.gitlog import git
from .surgeon import grimoire
from .surgeon.edits import EditError, Fix, apply_fix

BRANCH = "revenant/resurrection"


@dataclass
class Attempt:
    fix: Fix
    verdict: str                 # kept | reverted | unappliable
    before: dict
    after: dict | None
    diff: str = ""
    reason: str = ""
    seconds: float = 0.0
    model_seconds: float = 0.0
    commit: str = ""
    raw: str = ""


@dataclass
class Resurrection:
    patient: Patient
    tree: Path
    workdir: Path
    initial: Examination
    final: Examination | None = None
    attempts: list[Attempt] = field(default_factory=list)


def failing(exam: Examination) -> set[str]:
    return {o.test for o in exam.outcomes if o.status in ("failed", "error")}


def passing(exam: Examination) -> set[str]:
    return {o.test for o in exam.outcomes if o.status == "passed"}


def judge(before: Examination, after: Examination) -> tuple[bool, str]:
    """Keep an edit only if it makes things strictly better and breaks nothing that passed."""
    regressions = passing(before) - passing(after)
    if regressions:
        names = sorted(t.split("::")[-1] for t in regressions)
        more = f" and {len(names) - 3} more" if len(names) > 3 else ""
        return False, f"regressed {len(names)} passing test(s): " + ", ".join(names[:3]) + more
    gained = len(passing(after)) - len(passing(before))
    fewer = len(failing(before)) - len(failing(after))
    change = f"passing {len(passing(before))} -> {len(passing(after))}, failing {len(failing(before))} -> {len(failing(after))}"
    if gained > 0 or (fewer > 0 and gained >= 0):
        return True, change
    return False, "no improvement (" + change + ")"


def commit(tree: Path, title: str, body: str = "", citations: list[str] | None = None,
           paths: list[str] | None = None) -> str:
    """Commit as REVENANT_GIT_NAME / REVENANT_GIT_EMAIL (or the user's git identity)."""
    import os
    msg = title + (f"\n\n{body}" if body else "")
    if citations:
        msg += "\n\nHistory: " + ", ".join(citations)
    if paths is None:
        git(tree, "add", "-A")
    elif paths:
        git(tree, "add", "-A", "--", *paths)
    ident = []
    name, email = os.environ.get("REVENANT_GIT_NAME"), os.environ.get("REVENANT_GIT_EMAIL")
    if not (name and email) and not git(tree, "config", "user.email", check=False).strip():
        name, email = name or "Revenant", email or "revenant@localhost"
    if name:
        ident += ["-c", f"user.name={name}"]
    if email:
        ident += ["-c", f"user.email={email}"]
    git(tree, *ident, "commit", "-q", "-m", msg)
    return git(tree, "rev-parse", "--short", "HEAD").strip()


def revert(tree: Path):
    git(tree, "reset", "-q", "--hard", "HEAD")
    git(tree, "clean", "-qfd", "-e", "*.egg-info")


def start(patient: Patient, name: str = "fork") -> tuple[Path, Path]:
    tree = fresh_tree(patient.clone, patient.root / name)
    git(tree, "checkout", "-q", "-b", BRANCH)
    return tree, patient.root / f"{name}-env"


def _surgeon_fixes(surgeon, tree, exam, tried, tries, res, log):
    from .surgeon import operate
    targets = [o for o in exam.outcomes if o.status in ("failed", "error")
               and f"surgeon:{o.test.split('::')[-1]}" not in tried]
    for o in targets[:1]:
        key = f"surgeon:{o.test.split('::')[-1]}"
        tried.add(key)
        feedback = ""
        for _ in range(tries):
            from .integrations import tracing
            try:
                with tracing.agent("surgeon", f"fix {o.test}") as s:
                    try:
                        fix, raw, secs = operate.propose(surgeon, tree, o, feedback)
                    except EditError as e:
                        tracing.set_data(s, **{"revenant.proposal": "rejected", "revenant.reason": str(e)})
                        raise
                    tracing.set_data(s, **{"revenant.proposal": "edit" if fix else "none"})
            except EditError as e:
                feedback = str(e)
                res.attempts.append(Attempt(Fix(key, f"Surgeon's edit for {key[8:]}", [], str(e),
                                                source=f"surgeon:{surgeon.name}"),
                                            "unappliable", exam.tally, None, reason=str(e)))
                log(f"[revenant] {key}: model edit unappliable ({e})")
                continue
            if fix:
                return [fix], {fix.id: (secs, raw)}
            feedback = "no SEARCH/REPLACE blocks found"
    return [], {}


def resurrect(patient: Patient, *, use_grimoire: bool = True, surgeon=None, python: str = "3.13",
              max_rounds: int = 10, surgeon_tries: int = 2, name: str = "fork", log=print) -> Resurrection:
    from .integrations import tracing
    with tracing.agent("resurrectionist", f"resurrect {patient.slug}") as s:
        res = _resurrect(patient, use_grimoire, surgeon, python, max_rounds, surgeon_tries, name, log)
        tracing.set_data(s, **{"revenant.initial": json.dumps(res.initial.tally),
                               "revenant.final": json.dumps(res.final.tally),
                               "revenant.kept": sum(a.verdict == "kept" for a in res.attempts),
                               "revenant.reverted": sum(a.verdict == "reverted" for a in res.attempts)})
        return res


def _resurrect(patient, use_grimoire, surgeon, python, max_rounds, surgeon_tries, name, log) -> Resurrection:
    from .integrations import tracing
    tree, workdir = start(patient, name)
    exam = examine(tree, workdir, python, reinstall=True, agent="resurrectionist")
    res = Resurrection(patient, tree, workdir, exam)
    log(f"[Revenant] initial: {exam.tally}")
    tried: set[str] = set()
    parked: set[str] = set()   # reverted cures; one more chance after something else is kept
    retried: set[str] = set()
    for rnd in range(1, max_rounds + 1):
        fixes, meta = [], {}
        if use_grimoire:
            fixes = [f for f in grimoire.prescribe(tree, exam.symptoms, patient.clone) if f.id not in tried]
        if not fixes and surgeon is not None:
            fixes, meta = _surgeon_fixes(surgeon, tree, exam, tried, surgeon_tries, res, log)
            if not fixes and any(o.status in ("failed", "error") and f"surgeon:{o.test.split('::')[-1]}" not in tried
                                 for o in exam.outcomes):
                continue  # try the next failing test
        if not fixes:
            log(f"[Revenant] round {rnd}: nothing left to try")
            break
        for fix in fixes:
            tried.add(fix.id)
            t = time.time()
            with tracing.tool("apply_fix", "resurrectionist", "exact SEARCH/REPLACE edits, judged by a full test run",
                              fix=fix.id, source=fix.source, files=sorted({e.path for e in fix.edits})) as ts:
                try:
                    diff = apply_fix(tree, fix)
                except EditError as e:
                    res.attempts.append(Attempt(fix, "unappliable", exam.tally, None, reason=str(e)))
                    log(f"[Revenant] {fix.id}: unappliable ({e})")
                    tracing.tool_result(ts, {"verdict": "unappliable", "reason": str(e)})
                    continue
                new = examine(tree, workdir, python, extra=fix.deps, agent="resurrectionist")
                ok, why = judge(exam, new)
                tracing.tool_result(ts, {"verdict": "kept" if ok else "reverted", "reason": why})
            secs, raw = meta.get(fix.id, (0.0, ""))
            a = Attempt(fix, "kept" if ok else "reverted", exam.tally, new.tally, diff, why,
                        time.time() - t, secs, raw=raw)
            if ok:
                for fid in parked - retried:
                    tried.discard(fid)
                    retried.add(fid)
                parked.clear()
                a.commit = commit(tree, fix.title, fix.why, fix.citations, sorted({e.path for e in fix.edits}))
                exam = new
            else:
                parked.add(fix.id)
                revert(tree)
                if fix.reinstall:
                    examine(tree, workdir, python)  # put the environment back too
            res.attempts.append(a)
            log(f"[Revenant] {fix.id}: {a.verdict} ({why}) -> {new.tally}")
        if not (set(o.test for o in exam.outcomes if o.status in ("failed", "error"))):
            break
    res.final = exam
    return res
