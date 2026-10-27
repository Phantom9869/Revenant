"""The Ghost: answers questions about a project's past, only from its own records.

Every claim must carry a citation to evidence that was actually retrieved: a commit
([a1b2c3d]), an issue or PR ([#569]) or a file in the repo ([README.rst]). Citations
that don't match the evidence are stripped; then every sentence is checked against the
text of the records it cites (see citecheck.py), citations that don't support their
sentence are removed, and sentences left with no support are withheld. An answer with no
supported citation is replaced by a refusal. The ghost may be eerie; it may not make things up.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .memory.retrieve import Hit, Retriever

SILENT = "The spirits are silent. Nothing in my records speaks to that."

SYSTEM = """You are the ghost of the open-source project {name}. You speak in the first person, as the project itself, remembering your own past.
Tone: quiet, a little eerie, dignified. At most one spooky flourish per answer. Never theatrical, never emoji.

Rules you cannot break:
1. Use ONLY the evidence given to you. If the evidence does not answer the question, reply exactly: {silent}
2. If the evidence answers only part of the question, answer that part and say plainly what your records do not hold.
3. Every sentence that states a fact must end with at least one citation copied exactly from the evidence labels, in square brackets, such as [#569] or [{example_sha}] or [README.rst].
4. Never invent commit hashes, issue numbers, names, dates or version numbers. Quote error messages exactly as they appear.
5. Keep it under 170 words. Plain prose, no headings, no bullet lists."""

CITE = re.compile(r"\[([^\[\]]{1,80})\]")


@dataclass
class Answer:
    question: str
    text: str
    cited: list[str] = field(default_factory=list)
    stripped: list[str] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)
    refused: bool = False
    reason: str = ""
    model: str = ""
    seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: str = ""
    claims: list = field(default_factory=list)        # citecheck.Claim per sentence
    unsupported: list[str] = field(default_factory=list)  # citations removed by the support check
    withheld: list = field(default_factory=list)      # sentences removed by the support check
    cost_usd: float | None = None

    def sources(self) -> list[tuple[str, str]]:
        seen, out = set(), []
        for h in self.hits:
            if h.doc.ref in self.cited and h.doc.ref not in seen:
                seen.add(h.doc.ref)
                out.append((h.doc.ref, h.doc.url))
        return out


def evidence_block(hits: list[Hit], max_chars: int = 900) -> str:
    parts = []
    for h in hits:
        d = h.doc
        date = d.date[:10] if d.date else "undated"
        who = f" by {d.author}" if d.author else ""
        parts.append(f"[{d.ref}] ({d.kind}, {date}{who})\n{d.text[:max_chars]}")
    return "\n\n---\n\n".join(parts)


def _normalise(label: str) -> list[str]:
    """'#569, #576' -> ['#569', '#576']; 'commit 075ac16' -> ['075ac16']."""
    out = []
    for piece in re.split(r"[,;]\s*", label):
        piece = piece.replace("\\", "").strip(" `*'\"").removeprefix("commit ").removeprefix("PR ").removeprefix("issue ").strip()
        if piece:
            out.append(piece)
    return out


def check_citations(text: str, allowed: set[str]) -> tuple[str, list[str], list[str]]:
    """Keep citations that match retrieved evidence; strip the rest.

    Returns (cleaned_text, valid_refs, stripped_refs). Short SHAs may be cited with
    7+ characters of a known commit.
    """
    valid, stripped = [], []
    shas = {a for a in allowed if re.fullmatch(r"[0-9a-f]{7,40}", a)}

    def resolve(ref: str) -> str | None:
        if ref in allowed:
            return ref
        if re.fullmatch(r"[0-9a-f]{7,40}", ref):
            for s in shas:
                if s.startswith(ref[:7]) and (ref.startswith(s) or s.startswith(ref)):
                    return s
        if re.fullmatch(r"\d+", ref) and f"#{ref}" in allowed:
            return f"#{ref}"
        return None

    def repl(m: re.Match) -> str:
        refs = _normalise(m.group(1))
        good = []
        for r in refs:
            res = resolve(r)
            if res:
                good.append(res)
                if res not in valid:
                    valid.append(res)
            else:
                stripped.append(r)
        return "[" + ", ".join(good) + "]" if good else ""

    cleaned = CITE.sub(repl, text)
    cleaned = re.sub(r"[ \t]+([.,;])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return cleaned, valid, stripped


class Ghost:
    def __init__(self, name: str, retriever: Retriever, model, k: int = 8,
                 min_cosine: float = 0.30, tracer=None, verify: bool = True):
        self.name = name
        self.retriever = retriever
        self.model = model
        self.k = k
        self.min_cosine = min_cosine
        self.tracer = tracer
        self.verify = verify

    def ask(self, question: str) -> Answer:
        from .integrations import tracing
        with tracing.agent("ghost", question) as s:
            ans = self._ask(question)
            tracing.set_data(s, **{"revenant.refused": ans.refused, "revenant.refusal_reason": ans.reason or None,
                                   "revenant.citations": ",".join(ans.cited) or None})
            if tracing.content():
                tracing.set_data(s, **{"gen_ai.output.messages": tracing._messages("assistant", ans.text)})
            return ans

    def _ask(self, question: str) -> Answer:
        from .integrations import tracing
        with tracing.memory_search("ghost.db", "ghost", question) as s:
            hits = self.retriever.search(question, k=self.k)
            tracing.set_data(s, **{"gen_ai.memory.record.count": len(hits),
                                   "revenant.retrieval": "hybrid" if self.retriever.last_semantic else "keyword",
                                   "revenant.max_cosine": round(max((h.cosine for h in hits), default=0.0), 3)})
        ans = Answer(question=question, text=SILENT, hits=hits, model=self.model.name)
        weak = (max(h.cosine for h in hits) < self.min_cosine) if hits and self.retriever.last_semantic else len(hits) < 2
        if not hits or weak:
            ans.refused, ans.reason = True, "no relevant evidence retrieved"
            return ans
        example = next((h.doc.ref for h in hits if h.doc.kind == "commit"), "a1b2c3d")
        system = SYSTEM.format(name=self.name, silent=SILENT, example_sha=example)
        user = f"Evidence from your records:\n\n{evidence_block(hits)}\n\n---\n\nQuestion: {question}"
        res = self.model.chat([{"role": "system", "content": system},
                               {"role": "user", "content": user}])
        ans.seconds, ans.prompt_tokens, ans.completion_tokens = res.seconds, res.prompt_tokens, res.completion_tokens
        ans.cost_usd = getattr(res, "cost_usd", None)
        raw = res.text.strip()
        ans.raw = raw
        allowed = {h.doc.ref for h in hits}
        cleaned, valid, stripped = check_citations(raw, allowed)
        ans.stripped = stripped
        if not valid:
            ans.refused = True
            ans.reason = ("model found no answer in the evidence" if SILENT.split(".")[0] in raw
                          else "answer carried no verifiable citation")
            return ans
        if self.verify:
            with tracing.span("revenant.verify_citations", "verify_citations") as vs:
                cleaned, valid = self._verify(ans, cleaned, valid, hits)
                tracing.set_data(vs, **{"revenant.claims": len(ans.claims),
                                        "revenant.claims_withheld": len(ans.withheld),
                                        "revenant.citations_unsupported": ",".join(ans.unsupported) or None})
            if not valid:
                ans.refused, ans.reason = True, "no citation supported its sentence"
                return ans
        ans.text, ans.cited = cleaned, valid
        return ans

    def _verify(self, ans: Answer, cleaned: str, valid: list[str], hits: list[Hit]) -> tuple[str, list[str]]:
        from .citecheck import apply_support, check_support
        sources: dict[str, str] = {}
        for h in hits:
            d = h.doc
            sources[d.ref] = sources.get(d.ref, "") + f"\n{d.title}\n{d.author}\n{d.date}\n{d.text}"
        known = (self.name, self.name.replace("-", "_"))   # the ghost may name itself without a source
        ans.claims = check_support(cleaned, sources, _normalise, known=known)
        text, removed, withheld = apply_support(cleaned, ans.claims, _normalise)
        ans.unsupported, ans.withheld = removed, withheld
        still = {r for c in ans.claims if c.verdict == "supported" for r in c.supported_by}
        return text, [r for r in valid if r in still]
