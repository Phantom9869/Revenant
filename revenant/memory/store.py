"""The ghost's memory: SQLite documents + FTS5 keyword index + EmbeddingGemma vectors."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
  id TEXT PRIMARY KEY, kind TEXT, ref TEXT, url TEXT, title TEXT,
  author TEXT, date TEXT, text TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(id UNINDEXED, title, text, tokenize='porter');
CREATE TABLE IF NOT EXISTS vectors (id TEXT PRIMARY KEY, model TEXT, dim INTEGER, v BLOB);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


@dataclass
class Doc:
    id: str
    kind: str   # commit | issue | pr | comment | review | doc | record | archive
    ref: str    # citation label: "a1b2c3d", "#569", "docs/source/index.rst"
    url: str
    title: str
    author: str
    date: str
    text: str


class Memory:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.db = sqlite3.connect(self.path)
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # -- writing ---------------------------------------------------------
    def add(self, docs: list[Doc]) -> int:
        n = 0
        for d in docs:
            cur = self.db.execute("INSERT OR IGNORE INTO docs VALUES (?,?,?,?,?,?,?,?)",
                                  (d.id, d.kind, d.ref, d.url, d.title, d.author, d.date, d.text))
            if cur.rowcount:
                self.db.execute("INSERT INTO docs_fts(id,title,text) VALUES (?,?,?)",
                                (d.id, d.title, d.text))
                n += 1
        self.db.commit()
        return n

    def set_meta(self, k: str, v) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, json.dumps(v)))
        self.db.commit()

    def get_meta(self, k: str, default=None):
        row = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return json.loads(row[0]) if row else default

    def missing_vectors(self, model: str) -> list[Doc]:
        rows = self.db.execute(
            "SELECT d.* FROM docs d LEFT JOIN vectors v ON v.id=d.id AND v.model=? WHERE v.id IS NULL",
            (model,)).fetchall()
        return [Doc(*r) for r in rows]

    def put_vectors(self, model: str, items: list[tuple[str, list[float]]]) -> None:
        for i, vec in items:
            a = np.asarray(vec, dtype=np.float32)
            self.db.execute("INSERT OR REPLACE INTO vectors VALUES (?,?,?,?)",
                            (i, model, a.size, a.tobytes()))
        self.db.commit()

    # -- reading ---------------------------------------------------------
    def get(self, doc_id: str) -> Doc | None:
        r = self.db.execute("SELECT * FROM docs WHERE id=?", (doc_id,)).fetchone()
        return Doc(*r) if r else None

    def by_ref(self, ref: str) -> list[Doc]:
        return [Doc(*r) for r in self.db.execute("SELECT * FROM docs WHERE ref=?", (ref,))]

    def count(self) -> dict[str, int]:
        return dict(self.db.execute("SELECT kind, COUNT(*) FROM docs GROUP BY kind").fetchall())

    def keyword(self, query: str, k: int = 30) -> list[tuple[str, float]]:
        terms = [t for t in "".join(c if c.isalnum() or c in "_." else " " for c in query).split()
                 if len(t) > 1]
        if not terms:
            return []
        q = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
        rows = self.db.execute(
            "SELECT id, bm25(docs_fts, 2.0, 1.0) FROM docs_fts WHERE docs_fts MATCH ? "
            "ORDER BY bm25(docs_fts, 2.0, 1.0) LIMIT ?", (q, k)).fetchall()
        return [(i, -s) for i, s in rows]

    def vectors(self, model: str) -> tuple[list[str], np.ndarray]:
        rows = self.db.execute("SELECT id, v FROM vectors WHERE model=?", (model,)).fetchall()
        if not rows:
            return [], np.zeros((0, 0), dtype=np.float32)
        ids = [r[0] for r in rows]
        mat = np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
        return ids, mat
