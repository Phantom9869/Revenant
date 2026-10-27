"""Run the per-sentence citation support check over ghost answers saved before it existed.

The answers in demo/before_support_check/ are unedited model output from runs that only
checked that each cited ref had been retrieved. This replays the new check on that exact
text, using the full text of the cited records from the ghost's memory. (The live ghost
checks against the retrieved chunks only; here every chunk with that ref is used, which
can only make the check more lenient.)

    python demo/investigations/recheck_saved_answers.py
"""
import json
import os
from pathlib import Path

from revenant.citecheck import apply_support, check_support
from revenant.ghost import _normalise
from revenant.memory.store import Memory

home = Path(os.environ.get("REVENANT_HOME", ".revenant"))
mem = Memory(home / "psf__requests-html" / "ghost.db")
demo = Path(__file__).resolve().parent.parent / "before_support_check"
for name in ("03_ghost_json.json", "09_ghost_archive.json"):
    saved = json.loads((demo / name).read_text())
    refs = [r for r, _ in saved["sources"]]
    sources = {r: "\n".join(f"{d.title}\n{d.author}\n{d.date}\n{d.text}" for d in mem.by_ref(r)) for r in refs}
    claims = check_support(saved["answer"], sources, _normalise, known=("requests-html", "requests_html"))
    text, removed, withheld = apply_support(saved["answer"], claims, _normalise)
    print(f"== {name}\nQ: {saved['question']}\n\nsaved answer ({saved['model']}):\n{saved['answer']}\n")
    for c in claims:
        why = (f"missing from cited records: {', '.join(c.missing)}; " if c.missing else "") + f"word overlap {c.overlap:.0%}"
        print(f"  [{c.verdict:>11}] {c.sentence[:110]}{'…' if len(c.sentence) > 110 else ''}\n"
              f"                cites {', '.join(c.refs) or '-'}; supported by {', '.join(c.supported_by) or 'none'} ({why})")
    print(f"\nafter the check:\n{text or '(nothing left: the ghost would refuse)'}\n")
