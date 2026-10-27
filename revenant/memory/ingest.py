"""Turn harvested history into citable memory documents."""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..harvest.gitlog import Commit
from .store import Doc

CHUNK = 1500


def chunks(text: str, size: int = CHUNK) -> list[str]:
    text = (text or "").strip()
    if len(text) <= size:
        return [text] if text else []
    out, buf = [], ""
    for para in re.split(r"\n\s*\n", text):
        if len(buf) + len(para) + 2 > size and buf:
            out.append(buf.strip())
            buf = ""
        while len(para) > size:
            out.append(para[:size])
            para = para[size:]
        buf += para + "\n\n"
    if buf.strip():
        out.append(buf.strip())
    return out


def commit_docs(commits: list[Commit], slug: str) -> list[Doc]:
    docs = []
    for c in commits:
        files = ", ".join(c.files[:15]) + (" ..." if len(c.files) > 15 else "")
        text = f"{c.subject}\n\n{c.body}\n\nFiles: {files}".strip()
        docs.append(Doc(id=f"commit:{c.sha}", kind="commit", ref=c.short,
                        url=f"https://github.com/{slug}/commit/{c.sha}", title=c.subject,
                        author=c.author, date=c.date, text=text))
    return docs


def issue_docs(raw_dir: Path) -> list[Doc]:
    raw_dir = Path(raw_dir)
    issues = json.loads((raw_dir / "issues.json").read_text())
    titles = {i["number"]: i["title"] for i in issues}
    kinds = {i["number"]: ("pr" if "pull_request" in i else "issue") for i in issues}
    pulls = {p["number"]: p for p in json.loads((raw_dir / "pulls.json").read_text())}
    docs: list[Doc] = []
    for i in issues:
        n, kind = i["number"], kinds[i["number"]]
        state = i["state"]
        if kind == "pr" and pulls.get(n, {}).get("merged_at"):
            state = "merged " + pulls[n]["merged_at"][:10]
        labels = ", ".join(l["name"] for l in i.get("labels", []))
        head = f"{'PR' if kind == 'pr' else 'Issue'} #{n} [{state}] {i['title']}" + (f" (labels: {labels})" if labels else "")
        for j, part in enumerate(chunks(i.get("body") or "") or [""]):
            docs.append(Doc(id=f"{kind}:{n}:{j}", kind=kind, ref=f"#{n}", url=i["html_url"],
                            title=i["title"], author=(i.get("user") or {}).get("login", ""),
                            date=i["created_at"], text=f"{head}\n\n{part}".strip()))
    for c in json.loads((raw_dir / "issue_comments.json").read_text()):
        n = int(c["issue_url"].rsplit("/", 1)[1])
        for j, part in enumerate(chunks(c.get("body") or "")):
            docs.append(Doc(id=f"comment:{c['id']}:{j}", kind="comment", ref=f"#{n}", url=c["html_url"],
                            title=titles.get(n, ""), author=(c.get("user") or {}).get("login", ""),
                            date=c["created_at"],
                            text=f"Comment on {kinds.get(n, 'issue')} #{n} \"{titles.get(n, '')}\":\n\n{part}"))
    for c in json.loads((raw_dir / "review_comments.json").read_text()):
        n = int(c["pull_request_url"].rsplit("/", 1)[1])
        hunk = "\n".join((c.get("diff_hunk") or "").splitlines()[-8:])
        docs.append(Doc(id=f"review:{c['id']}", kind="review", ref=f"#{n}", url=c["html_url"],
                        title=titles.get(n, ""), author=(c.get("user") or {}).get("login", ""),
                        date=c["created_at"],
                        text=f"Review on PR #{n} at {c.get('path')}:\n{hunk}\n\n{c.get('body') or ''}"))
    return docs


def file_docs(repo: Path, slug: str, patterns=("README*", "HISTORY*", "CHANGELOG*", "docs/**/*.rst", "docs/**/*.md")) -> list[Doc]:
    repo = Path(repo)
    seen, docs = set(), []
    for pat in patterns:
        for f in sorted(repo.glob(pat)):
            if not f.is_file() or f in seen:
                continue
            seen.add(f)
            rel = f.relative_to(repo).as_posix()
            for j, part in enumerate(chunks(f.read_text(errors="replace"))):
                docs.append(Doc(id=f"doc:{rel}:{j}", kind="doc", ref=rel,
                                url=f"https://github.com/{slug}/blob/HEAD/{rel}", title=rel,
                                author="", date="", text=part))
    return docs


def record_docs(raw_dir: Path, repo: Path, slug: str) -> list[Doc]:
    """Small factual 'records' docs: repository metadata and release tags."""
    from ..harvest.gitlog import git
    docs = []
    meta_path = Path(raw_dir) / "repo.json"
    if meta_path.exists():
        r = json.loads(meta_path.read_text())
        text = (f"Repository {r['full_name']}: {r.get('description') or ''}\n"
                f"Created {r['created_at'][:10]}; last push {r['pushed_at'][:10]}. "
                f"Stars {r.get('stargazers_count')}, forks {r.get('forks_count')}, open issues and PRs {r.get('open_issues_count')}. "
                f"Archived: {r.get('archived')}. Homepage: {r.get('homepage') or 'none'}. "
                f"Owner: {r['owner']['login']}. License: {(r.get('license') or {}).get('spdx_id', 'unknown')}.")
        docs.append(Doc(id="record:repo", kind="record", ref="repo", url=r["html_url"], title="repository record",
                        author="", date=r["pushed_at"], text=text))
    out = git(repo, "for-each-ref", "--sort=creatordate", "--format=%(refname:short)\t%(creatordate:short)\t%(objectname:short=7)", "refs/tags", check=False)
    lines = [l.split("\t") for l in out.splitlines() if l.count("\t") == 2]
    if lines:
        body = "\n".join(f"{t} tagged {d} at commit {s}" for t, d, s in lines)
        first = git(repo, "log", "--reverse", "--format=%h %an %ad %s", "--date=short", check=False).splitlines()[:1]
        docs.append(Doc(id="record:tags", kind="record", ref="tags", url=f"https://github.com/{slug}/tags",
                        title="release tags", author="", date=lines[-1][1],
                        text=f"Latest release tag: {lines[-1][0]}, tagged {lines[-1][1]} at commit {lines[-1][2]}. "
                             f"First commit ever: {first[0] if first else 'unknown'}. "
                             f"{len(lines)} tags in total, oldest first:\n{body}"))
    return docs


def build(patient, embedder=None, batch: int = 32, log=print) -> dict:
    """Load everything harvested for a patient into its memory and embed what's missing."""
    import time
    from ..harvest.gitlog import read_commits
    from .store import Memory
    mem = Memory(patient.db)
    raw = patient.cache / "raw"
    added = mem.add(commit_docs(read_commits(patient.clone), patient.slug))
    if (raw / "issues.json").exists():
        added += mem.add(issue_docs(raw))
    added += mem.add(file_docs(patient.clone, patient.slug))
    added += mem.add(record_docs(raw, patient.clone, patient.slug))
    out = {"added": added, "counts": mem.count(), "embedded": 0, "embed_seconds": 0.0}
    log(f"  memory: +{added} docs, {out['counts']}")
    if embedder is not None:
        todo = mem.missing_vectors(embedder.name)
        t = time.time()
        for i in range(0, len(todo), batch):
            part = todo[i:i + batch]
            mem.put_vectors(embedder.name, list(zip([d.id for d in part],
                                                    embedder.embed_docs([(d.title, d.text) for d in part]))))
            if i and i % (batch * 20) == 0:
                log(f"  embedded {i}/{len(todo)}")
        out["embedded"], out["embed_seconds"] = len(todo), round(time.time() - t, 1)
        log(f"  embedded {len(todo)} docs with {embedder.name} in {out['embed_seconds']}s")
    mem.close()
    return out
