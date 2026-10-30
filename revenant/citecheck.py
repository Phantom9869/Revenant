"""Does the cited record actually say what the sentence claims?

After the ghost answers, every citation has already been checked to be evidence that was
retrieved. That is not enough: a model can attach a real source to a claim the source never
makes. This module checks each sentence against the text of the records it cites:

* hard details (version numbers, dates, hashes, issue numbers, code identifiers, quoted
  strings) must each appear in at least one cited record;
* enough of the sentence's content words must appear there too.

It is a lexical check, not an entailment model: it catches citations that point at
unrelated records and details that appear nowhere in the sources, and it can be fooled by
a sentence that reuses a source's words to say something the source doesn't. The verdict
for each sentence is kept on the answer so the reader can see what was and wasn't checked.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CITE = re.compile(r"\[([^\[\]]{1,80})\]")

STOP = set("""
a about above after again against all also although am an and any are aren as at be because been before
being below between both but by can cannot could did didn do does doesn doing don down during each either
even ever every few for from further had has have having he her here hers herself him himself his how however
i if in into is isn it its itself just later let like made make many may me might more most much must my
myself never no nor not now of off often on once one only or other our ours ourselves out over own per
perhaps rather really same says said see seems she should since so some still such than that the their
theirs them themselves then there these they this those though through thus to too under until up upon us
used using very via was wasn way we were weren what when where whether which while who whom whose why will
with within without would yet you your yours
remember records record recall speaks spoke spirits silent ghost memory memories told tell tells mentioned
mention mentions noted notes note says stated states explains explained explicitly according shows show
user users someone somebody commenter comment comments suggests suggested suggest reported reports report
""".split())

VERSION = re.compile(r"(?<![\w.])v?(\d+(?:\.\d+)+)(?![\w.]*\w)")
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
YEAR = re.compile(r"(?<![\d\-.])(?:19|20)\d{2}(?![\d\-.]\d?)")
SHA = re.compile(r"\b[0-9a-f]{7,40}\b")
ISSUE = re.compile(r"(?<![\w\[])#\d+\b")
CODE = re.compile(r"`([^`]{2,80})`")
QUOTE = re.compile(r"[\"\u201c]([^\"\u201d]{6,200})[\"\u201d]")
IDENT = re.compile(r"\b[A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)+\b|\b[a-z]+_[a-z_\d]+\b|\b[a-z]+[A-Z]\w+\b"
                   r"|\b[A-Z][a-z]+[A-Z]\w*\b|\b[A-Z]{2,}[a-z]\w*\b")
WORD = re.compile(r"[a-z][a-z0-9]+")


def _squash(s: str) -> str:
    return re.sub(r"[\s\-_]+", " ", s.lower()).strip()


def _stem(w: str) -> str:
    for suf in ("ations", "ation", "ingly", "ings", "ing", "edly", "ies", "ied", "ed", "es", "s", "ly"):
        if len(w) - len(suf) >= 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def content_words(s: str) -> set[str]:
    return {_stem(w) for w in WORD.findall(s.lower()) if len(w) >= 3 and w not in STOP}


def hard_details(s: str) -> list[str]:
    """Things that are either in the source or invented: versions, dates, hashes, ids, quotes."""
    out: list[str] = []
    for rx in (QUOTE, CODE):
        out += [m.strip().rstrip(".") for m in rx.findall(s)]
    stripped = CODE.sub(" ", QUOTE.sub(" ", s))
    for rx in (DATE, VERSION, SHA, ISSUE, IDENT):
        out += rx.findall(stripped)
    out += YEAR.findall(DATE.sub(" ", stripped))
    out = [d for d in out if not (IDENT.fullmatch(d) and len(d) < 5)]   # "e.g", "i.e"
    seen, uniq = set(), []
    for d in out:
        if d and d.lower() not in seen:
            seen.add(d.lower())
            uniq.append(d)
    return uniq


def _in_source(detail: str, source: str, source_squashed: str) -> bool:
    d = detail.lower()
    if re.fullmatch(r"\d+(?:\.\d+)+", d):
        # "5.2" is supported by "5.2.0"; not by "15.2", "0.5.2" or "5.21"
        return re.search(rf"(?<![\d.]){re.escape(d)}(?:\.0)*(?![\d]|\.\d)", source) is not None
    if d in source:
        return True
    if re.fullmatch(r"[0-9a-f]{7,40}", d):
        return d[:7] in source
    return _squash(d) in source_squashed


@dataclass
class Claim:
    sentence: str               # the sentence as the ghost wrote it, citations removed
    refs: list[str]             # citations attached to it
    supported_by: list[str] = field(default_factory=list)
    unsupported_refs: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)    # hard details found in no cited source
    overlap: float = 0.0        # share of content words found in the best cited source
    verdict: str = ""           # supported | unsupported | uncited

    def as_dict(self) -> dict:
        return {"sentence": self.sentence, "refs": self.refs, "verdict": self.verdict,
                "supported_by": self.supported_by, "unsupported_refs": self.unsupported_refs,
                "missing_details": self.missing, "overlap": round(self.overlap, 2)}


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences, keeping trailing citations with the sentence they follow."""
    text = text.replace("\r", "")
    pieces: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        if not para:
            continue
        # protect abbreviations / dotted identifiers / versions from splitting
        parts = re.split(r"(?<!\be\.g\.)(?<!\bi\.e\.)(?<!\bvs\.)(?<=[.!?])\s+(?=[\w\"\u201c`\[])"
                         r"|(?<=\])\s+(?=[A-Z\"\u201c`])", para)
        buf = ""
        for part in parts:
            if re.fullmatch(r"(\[[^\[\]]+\]\s*[.,;]?\s*)+", part) and pieces_or(buf, pieces):
                buf = (buf + " " + part).strip()
                continue
            if buf:
                pieces.append(buf)
            buf = part
        if buf:
            pieces.append(buf)
    return pieces


def pieces_or(buf: str, pieces: list[str]) -> bool:
    return bool(buf or pieces)


def _refs_in(sentence: str, normalise) -> list[str]:
    refs: list[str] = []
    for m in CITE.finditer(sentence):
        for r in normalise(m.group(1)):
            if r not in refs:
                refs.append(r)
    return refs


def check_support(text: str, sources: dict[str, str], normalise, min_overlap: float = 0.5,
                  min_overlap_with_details: float = 1 / 3, known: tuple[str, ...] = ()) -> list[Claim]:
    """Return one Claim per sentence. `sources` maps a citation ref to the record text it names.
    `known` are terms that need no source, such as the project's own name and module."""
    known_sq = {_squash(k) for k in known}
    low = {r: (t or "").lower() for r, t in sources.items()}
    squashed = {r: _squash(t) for r, t in low.items()}
    words = {r: content_words(t) for r, t in low.items()}
    claims = []
    for sent in split_sentences(text):
        refs = _refs_in(sent, normalise)
        bare = re.sub(r"\s+([.,;:!?])", r"\1", " ".join(CITE.sub(" ", sent).split())).strip()
        c = Claim(sentence=bare, refs=refs)
        if not refs:
            c.verdict = "uncited"
            claims.append(c)
            continue
        details = [d for d in hard_details(bare) if _squash(d) not in known_sq]
        cw = content_words(CODE.sub(" ", QUOTE.sub(" ", bare)))
        cited = [r for r in refs if r in low]
        found = {d for d in details if any(_in_source(d, low[r], squashed[r]) for r in cited)}
        c.missing = [d for d in details if d not in found]
        for r in refs:
            if r not in low:
                c.unsupported_refs.append(r)
                continue
            ov = len(cw & words[r]) / len(cw) if cw else 1.0
            own = [d for d in details if _in_source(d, low[r], squashed[r])]
            c.overlap = max(c.overlap, ov)
            # a record supports the sentence if it shares enough of its words, or carries one
            # of its hard details and a fair share of its words (or the sentence is little more
            # than that detail, e.g. "This results in `ImportError: ...`.")
            if ov >= min_overlap or (own and (ov >= min_overlap_with_details or len(cw) <= 2)):
                c.supported_by.append(r)
            else:
                c.unsupported_refs.append(r)
        c.verdict = "supported" if c.supported_by and not c.missing else "unsupported"
        claims.append(c)
    return claims


def apply_support(text: str, claims: list[Claim], normalise) -> tuple[str, list[str], list[Claim]]:
    """Rewrite the answer: drop citations that don't support their sentence, and drop
    sentences whose citations support nothing (or whose hard details appear in no source).

    Returns (new_text, refs_removed, withheld_claims).
    """
    removed, withheld = [], []
    out = []
    sentences = split_sentences(text)
    for sent, c in zip(sentences, claims, strict=True):   # check_support made one claim per sentence
        if c.verdict == "uncited":
            out.append(sent)
            continue
        if c.verdict == "unsupported":
            withheld.append(c)
            removed += [r for r in c.refs if r not in removed]
            continue

        def repl(m: re.Match) -> str:
            keep = [r for r in normalise(m.group(1)) if r in c.supported_by]
            for r in normalise(m.group(1)):
                if r not in keep and r not in removed:
                    removed.append(r)
            return "[" + ", ".join(keep) + "]" if keep else ""

        s = CITE.sub(repl, sent)
        s = re.sub(r"[ \t]+([.,;])", r"\1", s)
        out.append(" ".join(s.split()))
    return " ".join(out).strip(), removed, withheld
