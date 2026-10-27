"""Paths and settings. Everything Revenant learns about a patient lives in one folder."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

GHOST_MODEL = os.environ.get("REVENANT_GHOST_MODEL", "gemma4:e4b")
SURGEON_MODEL = os.environ.get("REVENANT_SURGEON_MODEL", "qwen2.5-coder:7b")
EMBED_MODEL = os.environ.get("REVENANT_EMBED_MODEL", "embeddinggemma")
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
if not OLLAMA_URL.startswith("http"):
    OLLAMA_URL = "http://" + OLLAMA_URL


def home() -> Path:
    return Path(os.environ.get("REVENANT_HOME", Path.cwd() / ".revenant")).resolve()


_SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def parse_slug(repo: str) -> str:
    """Accept 'owner/name' or a github.com URL and return 'owner/name'."""
    repo = repo.strip().rstrip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    m = re.search(r"github\.com[/:]([^/]+/[^/]+)$", repo)
    if m:
        repo = m.group(1)
    if not _SLUG.match(repo):
        raise ValueError(f"not a GitHub repo slug: {repo!r}")
    return repo


@dataclass
class Patient:
    slug: str

    @property
    def root(self) -> Path:
        return home() / self.slug.replace("/", "__")

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def clone(self) -> Path:
        return self.root / "clone"

    @property
    def fork(self) -> Path:
        return self.root / "fork"

    @property
    def db(self) -> Path:
        return self.root / "ghost.db"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def url(self) -> str:
        return f"https://github.com/{self.slug}"

    def ensure(self) -> "Patient":
        for p in (self.root, self.cache, self.reports):
            p.mkdir(parents=True, exist_ok=True)
        return self
