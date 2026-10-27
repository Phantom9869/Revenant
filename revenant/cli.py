"""Revenant: summon the ghost of an abandoned repository, find out what killed it, bring it back."""
from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__, config
from .config import Patient, parse_slug


def _patient(args) -> Patient:
    return Patient(parse_slug(args.repo)).ensure()


def cmd_summon(args):
    from .harvest.github import GitHubClient, harvest
    from .harvest.gitlog import clone
    from .memory import ingest
    from .models import OllamaEmbedder
    p = _patient(args)
    print(f"Summoning {p.slug} into {p.root}")
    clone(p.url, p.clone)
    if not args.no_github:
        summary = harvest(GitHubClient(p.cache), p.slug, p.cache / "raw")
        if summary["partial"]:
            print(f"  rate-limited; partial: {', '.join(summary['partial'])}. Re-run later to resume from cache.")
    emb = None if args.no_embed else OllamaEmbedder()
    out = ingest.build(p, emb)
    if args.archive:
        from .integrations import wayback
        from .memory.store import Memory
        snap = wayback.Snapshot.parse(args.archive)
        if not snap:
            try:
                snap = wayback.closest(args.archive, args.archive_at)
            except OSError as e:
                raise SystemExit(f"  Wayback lookup failed ({e}); pass a full web.archive.org/web/<timestamp>/<url> instead")
        if snap:
            fetcher = wayback.default_fetcher(p.cache / "archive")
            from .integrations import tracing
            with tracing.tool("fetch_archive", "summoner", "Wayback snapshot via Browserbase Fetch, cached on disk",
                              url=snap.raw_url) as s:
                docs = wayback.archive_docs(snap, fetcher)
                tracing.tool_result(s, {"chunks": len(docs), "fetcher": fetcher.name, "cache_hit": bool(fetcher.hits)})
            m = Memory(p.db)
            m.add(docs)
            if emb:
                m.put_vectors(emb.name, list(zip([d.id for d in docs], emb.embed_docs([(d.title, d.text) for d in docs]))))
            src = "disk cache" if fetcher.hits else fetcher.name
            print(f"  archived {args.archive} as of {snap.date} via {src}: {len(docs)} chunks, cited as [{docs[0].ref if docs else '-'}]")
        else:
            print(f"  no Wayback snapshot for {args.archive}")
    print(json.dumps(out, indent=2))


def build_ghost(p: Patient, model_spec: str | None = None):
    from .ghost import Ghost
    from .integrations import tracing
    from .memory.retrieve import Retriever
    from .memory.store import Memory
    from .models import OllamaEmbedder, get_chat_model
    model = get_chat_model(model_spec or config.GHOST_MODEL)
    if tracing.enabled():
        model = tracing.TracedModel(model, "ghost")
    return Ghost(p.slug.split("/")[1], Retriever(Memory(p.db), OllamaEmbedder()), model)


def cmd_ask(args):
    p = _patient(args)
    if not p.db.exists():
        sys.exit(f"No memory for {p.slug}. Run: revenant summon {p.slug}")
    ghost = build_ghost(p, args.model)
    ans = ghost.ask(args.question)
    if args.json:
        print(json.dumps({"question": ans.question, "answer": ans.text, "refused": ans.refused,
                          "reason": ans.reason, "sources": ans.sources(), "stripped": ans.stripped,
                          "model": ans.model, "seconds": round(ans.seconds, 1),
                          "retrieved": [h.doc.ref for h in ans.hits]}, indent=2))
        return
    print(ans.text)
    if ans.sources():
        print()
        for ref, url in ans.sources():
            print(f"  [{ref}] {url}")
    if ans.stripped:
        print(f"\n  (removed {len(ans.stripped)} citation(s) not found in the evidence: {', '.join(ans.stripped)})")
    if ans.refused and args.verbose:
        print(f"\n  ({ans.reason})")
    if args.verbose:
        if ans.prompt_tokens:
            print(f"\n  {ans.model}: {ans.seconds:.1f}s, {ans.prompt_tokens} prompt / {ans.completion_tokens} output tokens")
        else:
            print(f"\n  {ans.model}: not called")


def cmd_autopsy(args):
    from .autopsy import run_autopsy
    from .memory.store import Memory
    p = _patient(args)
    mem = Memory(p.db) if p.db.exists() else None
    md, exam, _ = run_autopsy(p, mem, args.python, check_web=not args.offline)
    print(md)
    print(f"\nWritten to {p.reports / 'death_certificate.md'}")


def cmd_resurrect(args):
    from .aftercare import run_aftercare
    from .models import OllamaClient
    from .report import resurrection_log
    from .resurrect import commit, resurrect
    p = _patient(args)
    from .integrations import tracing
    surgeon = None if args.surgeon == "none" else OllamaClient(args.surgeon, temperature=0.1)
    if surgeon is not None and not surgeon.available():
        print(f"  surgeon model {args.surgeon} not available in Ollama; continuing with the grimoire only")
        surgeon = None
    if surgeon is not None and tracing.enabled():
        surgeon = tracing.TracedModel(surgeon, "surgeon")
    t = time.time()
    res = resurrect(p, use_grimoire=not args.no_grimoire, surgeon=surgeon, python=args.python, name=args.name)
    notes = [] if args.no_aftercare or (res.final.tally["failed"] or res.final.tally["error"]) else run_aftercare(res)
    md = resurrection_log(res, notes)
    (res.tree / "RESURRECTION_LOG.md").write_text(md)
    commit(res.tree, "Add resurrection log", paths=["RESURRECTION_LOG.md"])
    (p.reports / f"RESURRECTION_LOG{'' if args.name == 'fork' else '_' + args.name}.md").write_text(md)
    print(md)
    print(f"\nRevived tree: {res.tree} (branch revenant/resurrection), {time.time() - t:.0f}s")


def cmd_serve(args):
    from .web.app import serve
    serve(args.host, args.port)


def main(argv=None):
    from .integrations import tracing
    tracing.init()
    ap = argparse.ArgumentParser(prog="revenant", description=__doc__)
    ap.add_argument("--version", action="version", version=f"Revenant {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("summon", help="clone + harvest history + build the ghost's memory")
    s.add_argument("repo")
    s.add_argument("--no-github", action="store_true", help="skip the GitHub API (git history only)")
    s.add_argument("--no-embed", action="store_true", help="keyword search only, no embeddings")
    s.add_argument("--archive", metavar="URL", help="also ingest a Wayback snapshot of a dead docs site (a URL, or a full web.archive.org/web/<ts>/<url>)")
    s.add_argument("--archive-at", metavar="YYYY[MMDD]", help="snapshot closest to this date instead of the latest")
    s.set_defaults(fn=cmd_summon)

    s = sub.add_parser("ask", help="ask the ghost a question about its past")
    s.add_argument("repo")
    s.add_argument("question")
    s.add_argument("--model", help=f"chat model (default {config.GHOST_MODEL}; 'backboard:provider/model' also works)")
    s.add_argument("--json", action="store_true")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(fn=cmd_ask)

    s = sub.add_parser("autopsy", help="run the tests in a sandbox and write a death certificate")
    s.add_argument("repo")
    s.add_argument("--python", default="3.13")
    s.add_argument("--offline", action="store_true", help="skip web checks (docs, PyPI)")
    s.set_defaults(fn=cmd_autopsy)

    s = sub.add_parser("resurrect", help="fix it, one verified edit at a time")
    s.add_argument("repo")
    s.add_argument("--python", default="3.13")
    s.add_argument("--surgeon", default=config.SURGEON_MODEL, help="Ollama code model, or 'none'")
    s.add_argument("--no-grimoire", action="store_true", help="code-model surgeon only, no grimoire (for comparison)")
    s.add_argument("--no-aftercare", action="store_true")
    s.add_argument("--name", default="fork", help="working tree name under the patient folder")
    s.set_defaults(fn=cmd_resurrect)

    s = sub.add_parser("serve", help="small web UI for summoned patients")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)

    args = ap.parse_args(argv)
    if args.fn is cmd_serve:
        return args.fn(args)
    try:
        with tracing.transaction(f"revenant {args.cmd}" if hasattr(args, "cmd") else "revenant", op="cli"):
            args.fn(args)
    finally:
        tracing.flush()


if __name__ == "__main__":
    main()
