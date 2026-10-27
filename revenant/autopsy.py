"""Autopsy: run the dead project's own tests in a sandbox and write its death certificate."""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from . import diagnose, vitals
from .config import Patient
from .harvest.gitlog import commits_per_year, git, read_commits
from .sandbox import RunResult, Sandbox, TestPlan, detect_test_plan


@dataclass
class Examination:
    plan: TestPlan
    run: RunResult
    outcomes: list[diagnose.Outcome]
    symptoms: list[diagnose.Symptom]
    unexplained: list[diagnose.Outcome]
    install_note: str = ""

    @property
    def tally(self) -> dict[str, int]:
        return diagnose.tally(self.outcomes)


def examine(tree: Path, workdir: Path, python: str = "3.13", plan: TestPlan | None = None,
            extra: list[str] | None = None, reinstall: bool = False, agent: str = "autopsy") -> Examination:
    plan = plan or detect_test_plan(tree)
    box = Sandbox(tree, workdir, python)
    note = box.install(plan, extra=extra, fresh=reinstall)
    from .integrations import tracing
    with tracing.tool("run_tests", agent, "project's own pytest suite in a network-less bwrap sandbox",
                      python=python, args=plan.args) as s:
        run = box.run_tests(plan)
        tracing.set_data(s, **{"revenant.sandboxed": run.sandboxed, "revenant.test_seconds": round(run.seconds, 2)})
        outcomes = diagnose.parse_junit(run.junit)
        tally = {k: sum(o.status == k for o in outcomes) for k in ("passed", "failed", "error", "skipped")}
        tracing.tool_result(s, tally)
    symptoms, unexplained = diagnose.classify(outcomes, run.stdout)
    return Examination(plan, run, outcomes, symptoms, unexplained, note)


def fresh_tree(src: Path, dest: Path, ref: str = "HEAD") -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    subprocess.run(["git", "clone", "-q", str(src), str(dest)], check=True)
    git(dest, "checkout", "-q", ref)
    return dest


def witnesses(memory, symptom: diagnose.Symptom, k: int = 3) -> list:
    if memory is None or not symptom.rule.witnesses:
        return []
    out, seen = [], set()
    for doc_id, _ in memory.keyword(symptom.rule.witnesses + " " + symptom.evidence[:120], 40):
        d = memory.get(doc_id)
        if d and d.kind in ("issue", "pr", "comment") and d.ref not in seen:
            seen.add(d.ref)
            out.append(d)
        if len(out) >= k:
            break
    return out


def bar(n: int, scale: int) -> str:
    return "█" * max(1, round(n / scale)) if n else ""


def _short(title: str, n: int = 70) -> str:
    title = " ".join(title.split())
    return title if len(title) <= n else title[:n].rsplit(" ", 1)[0] + "…"


def certificate(patient: Patient, exam: Examination, findings: list[vitals.Finding], memory=None,
                python: str = "3.13") -> str:
    repo = patient.clone
    commits = sorted(read_commits(repo), key=lambda c: c.date, reverse=True)  # newest first
    last = commits[0] if commits else None
    last_human = next((c for c in commits if not c.is_merge), None)
    years = commits_per_year(commits)
    t = exam.tally
    L = [f"# Certificate of Death: {patient.slug}", "",
         f"*Examined {date.today().isoformat()} by Revenant. Python {python} ({platform.machine()}), "
         f"tests run {'inside a network-less bubblewrap sandbox' if exam.run.sandboxed else 'WITHOUT a sandbox (bwrap unavailable)'}.*", ""]
    if last:
        L += ["## The deceased", "",
              f"- **Last commit:** [`{last.short}`]({patient.url}/commit/{last.sha}) on {last.date[:10]} by {last.author}: \"{last.subject}\""]
        if last_human and last_human.sha != last.sha:
            L.append(f"- **Last non-merge commit:** [`{last_human.short}`]({patient.url}/commit/{last_human.sha}) on {last_human.date[:10]}: \"{last_human.subject}\"")
        L.append(f"- **First commit:** `{commits[-1].short}` on {commits[-1].date[:10]} by {commits[-1].author}")
        L.append(f"- **Commits:** {len(commits)} total")
        L += ["", "```"] + [f"{y}  {bar(n, max(1, max(years.values()) // 40)):<41} {n}" for y, n in sorted(years.items())] + ["```", ""]
    L += ["## Post-mortem test run", "",
          f"Command (from {exam.plan.source}): `pytest {' '.join(exam.plan.args)}` with test deps `{', '.join(exam.plan.deps)}`", "",
          "| passed | failed | errors | skipped | seconds |", "|---|---|---|---|---|",
          f"| {t['passed']} | {t['failed']} | {t['error']} | {t['skipped']} | {exam.run.seconds:.1f} |", ""]
    if not exam.outcomes:
        L += ["No test could even be collected. Last lines of output:", "", "```",
              *exam.run.stdout.strip().splitlines()[-12:], "```", ""]
    L += ["## Cause of death", ""]
    if not exam.symptoms:
        L.append("No known cause matched. See unexplained failures below.")
    for i, s in enumerate(exam.symptoms, 1):
        L += [f"### {i}. {s.rule.title}", "", s.rule.layer, "",
              f"- **Evidence:** `{s.evidence}`"]
        if s.location:
            L.append(f"- **Where:** `{s.location}`")
        L.append(f"- **Tests killed ({len(s.tests)}):** " + ", ".join(f"`{x.split('::')[-1]}`" for x in s.tests[:8]))
        w = witnesses(memory, s)
        if w:
            L.append("- **Witnesses in the issue tracker:** " + "; ".join(f"[{d.ref}]({d.url}) {_short(d.title)}" for d in w))
        L.append("")
    if exam.unexplained:
        L += ["### Unexplained", ""] + [f"- `{o.test}`: {o.message[:160]}" for o in exam.unexplained] + [""]
    L += ["## Vital signs outside the code", "", "| sign | status | detail |", "|---|---|---|"]
    for f in findings:
        L.append(f"| {f.name} | **{f.status}** | {f.detail.replace('|', '/')} |")
    L.append("")
    return "\n".join(L)


def run_autopsy(patient: Patient, memory=None, python: str = "3.13", check_web: bool = True) -> tuple[str, Examination, list]:
    patient.ensure()
    tree = fresh_tree(patient.clone, patient.root / "autopsy" / "tree")
    exam = examine(tree, patient.root / "autopsy", python, reinstall=True)
    findings = vitals.check_ci(tree)
    if check_web:
        pypi = vitals.check_pypi(vitals.package_name(tree, patient.slug.split("/")[1]))
        version = pypi.detail.split(" on ")[0].split()[-1] if pypi.source else None
        homepage = None
        meta = patient.cache / "raw" / "repo.json"
        if meta.exists():
            homepage = json.loads(meta.read_text()).get("homepage")
        hosts = vitals.doc_hosts(tree, homepage)
        for h in hosts:
            findings.append(vitals.check_host(h, version))
        if memory is not None:
            token = vitals.package_name(tree, patient.slug.split("/")[1])
            texts = [r[0] for r in memory.db.execute("SELECT text FROM docs WHERE kind IN ('issue','comment')")]
            for h, n in vitals.community_hosts(texts, token):
                if h not in hosts:
                    f = vitals.check_host(h, version)
                    f.name += f" (linked {n}x in the tracker)"
                    findings.append(f)
        findings.append(pypi)
        rel = vitals.sphinx_release(tree)
        for f in findings:
            if f.status == "stale" and f.name.startswith("Docs") and rel:
                f.detail += f". The Sphinx config still says `{rel.split(': ')[1]}` ({rel.split(':')[0]})"
    md = certificate(patient, exam, findings, memory, python)
    patient.reports.mkdir(parents=True, exist_ok=True)
    (patient.reports / "death_certificate.md").write_text(md)
    (patient.reports / "autopsy.json").write_text(json.dumps({
        "tally": exam.tally, "symptoms": [{"id": s.rule.id, "tests": s.tests, "evidence": s.evidence,
                                           "location": s.location} for s in exam.symptoms],
        "unexplained": [asdict(o) for o in exam.unexplained],
        "vitals": [asdict(f) for f in findings], "sandboxed": exam.run.sandboxed,
        "seconds": exam.run.seconds}, indent=2))
    (patient.reports / "autopsy_pytest.txt").write_text(exam.run.stdout)
    return md, exam, findings
