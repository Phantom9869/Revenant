import subprocess
from pathlib import Path

import pytest


def run(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


class RepoPath(type(Path())):
    """A Path that also knows how to make commits in itself."""


@pytest.fixture
def gitrepo(tmp_path, monkeypatch):
    """A tiny real git repository with a configurable history."""
    for var in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(var, raising=False)  # identities set in the environment would override the test's
    repo = RepoPath(tmp_path / "repo")
    repo.mkdir()
    run(repo, "init", "-q", "-b", "main")
    run(repo, "config", "user.name", "Ada")
    run(repo, "config", "user.email", "ada@example.com")

    def commit(files: dict[str, str], msg: str, author: str = "Ada"):
        for name, text in files.items():
            p = repo / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        run(repo, "add", "-A")
        run(repo, "-c", f"user.name={author}", "commit", "-q", "-m", msg)
        return run(repo, "rev-parse", "HEAD").strip()

    repo.commit = commit
    return repo
