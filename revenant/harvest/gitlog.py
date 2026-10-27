"""Read a repository's own memory: its git history."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

SEP, END = "\x1f", "\x1e"


@dataclass
class Commit:
    sha: str
    author: str
    date: str  # ISO 8601
    subject: str
    body: str
    files: list[str] = field(default_factory=list)
    parents: int = 1

    @property
    def short(self) -> str:
        return self.sha[:7]

    @property
    def is_merge(self) -> bool:
        return self.parents > 1


def git(repo: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=check,
                          capture_output=True, text=True).stdout


def clone(url: str, dest: Path) -> Path:
    dest = Path(dest)
    if (dest / ".git").exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--quiet", url, str(dest)], check=True)
    return dest


def parse_log(raw: str) -> list[Commit]:
    commits: list[Commit] = []
    for rec in raw.split(END):
        rec = rec.strip("\n")
        parts = rec.split(SEP)
        if len(parts) < 6:
            continue
        sha, parents, author, date, subject = parts[:5]
        body = SEP.join(parts[5:])
        commits.append(Commit(sha=sha.strip(), author=author, date=date, subject=subject,
                              body=body.strip(), parents=max(1, len(parents.split()))))
    return commits


def read_commits(repo: Path) -> list[Commit]:
    fmt = SEP.join(["%H", "%P", "%an", "%aI", "%s", "%b"]) + END
    raw = git(repo, "log", "--reverse", f"--format={fmt}")
    commits = parse_log(raw)
    names = git(repo, "log", "--reverse", "--format=%H", "--name-only")
    files_by_sha: dict[str, list[str]] = {}
    cur = None
    for line in names.splitlines():
        line = line.strip()
        if len(line) == 40 and all(c in "0123456789abcdef" for c in line):
            cur = line
            files_by_sha[cur] = []
        elif line and cur:
            files_by_sha[cur].append(line)
    for c in commits:
        c.files = files_by_sha.get(c.sha, [])
    return commits


def commits_per_year(commits: list[Commit]) -> dict[int, int]:
    out: dict[int, int] = {}
    for c in commits:
        y = int(c.date[:4])
        out[y] = out.get(y, 0) + 1
    return dict(sorted(out.items()))


def pickaxe(repo: Path, needle: str, path: str | None = None) -> list[Commit]:
    """Commits that added or removed `needle` (git log -S), oldest first."""
    fmt = SEP.join(["%H", "%P", "%an", "%aI", "%s", "%b"]) + END
    args = ["log", "--reverse", f"-S{needle}", f"--format={fmt}"]
    if path:
        args += ["--", path]
    return parse_log(git(repo, *args))
