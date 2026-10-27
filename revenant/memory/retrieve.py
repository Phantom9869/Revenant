"""Hybrid retrieval: BM25 keywords + EmbeddingGemma cosine, fused with reciprocal rank."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .store import Doc, Memory


@dataclass
class Hit:
    doc: Doc
    score: float      # fused RRF score
    cosine: float     # best semantic similarity (0 if not in vector results)


def rrf(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return scores


class Retriever:
    def __init__(self, memory: Memory, embedder=None, model: str | None = None):
        self.mem = memory
        self.embedder = embedder
        self.model = model or (embedder.name if embedder else None)
        self._ids: list[str] = []
        self._mat = None
        self.last_semantic = False   # did the last search use embeddings?

    def _load(self):
        if self._mat is None and self.model:
            self._ids, mat = self.mem.vectors(self.model)
            if len(self._ids):
                norms = np.linalg.norm(mat, axis=1, keepdims=True)
                self._mat = mat / np.maximum(norms, 1e-9)
            else:
                self._mat = np.zeros((0, 0), dtype=np.float32)

    def semantic(self, query: str, k: int = 30) -> list[tuple[str, float]]:
        if not self.embedder:
            return []
        self._load()
        if not len(self._ids):
            return []
        try:
            q = np.asarray(self.embedder.embed_query(query), dtype=np.float32)
        except OSError:  # embedding server unreachable: degrade to keywords
            return []
        q /= max(np.linalg.norm(q), 1e-9)
        sims = self._mat @ q
        top = np.argsort(-sims)[:k]
        return [(self._ids[i], float(sims[i])) for i in top]

    def search(self, query: str, k: int = 8, per_ref: int = 2) -> list[Hit]:
        kw = self.mem.keyword(query, 30)
        sem = self.semantic(query, 30)
        self.last_semantic = bool(sem)
        cos = dict(sem)
        fused = rrf([[i for i, _ in kw], [i for i, _ in sem]])
        hits, per = [], {}
        for doc_id, s in sorted(fused.items(), key=lambda x: -x[1]):
            d = self.mem.get(doc_id)
            if not d:
                continue
            if per.get(d.ref, 0) >= per_ref:
                continue
            per[d.ref] = per.get(d.ref, 0) + 1
            hits.append(Hit(doc=d, score=s, cosine=cos.get(doc_id, 0.0)))
            if len(hits) >= k:
                break
        return hits
