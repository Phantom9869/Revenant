"""Collect the head-to-head resurrection runs into one table.

Each contender ran `revenant resurrect psf/requests-html --name h2h-<x> --no-aftercare` against
the same clone, sandbox and judge; the code models ran with --no-grimoire. Numbers come from
the reports/summary_h2h-*.json files those runs wrote (tokens and cost as the model server
reported them).
"""
import json
import os
import sys
from pathlib import Path

home = Path(os.environ.get("REVENANT_HOME", ".revenant")) / "psf__requests-html" / "reports"
rows = [("h2h-grimoire", "grimoire only (no model)"),
        ("h2h-qwen7b", "Qwen2.5-Coder 7B, local (Ollama, CPU)"),
        ("h2h-dots3", "Dots3-Note Preview 280B-A16B, hosted (Backboard, $0 tier)"),
        ("h2h-flint", "Flint v1.0 40B-A2.5B, hosted (Backboard, $0 tier)")]
out = ["| contender | passing (of 30) | failed / errors | kept | reverted | unappliable | model calls | tokens in / out | model time | wall time | cost reported |",
       "|---|---|---|---|---|---|---|---|---|---|---|"]
for name, label in rows:
    f = home / f"summary_{name}.json"
    if not f.exists():
        out.append(f"| {label} | not run |" + " |" * 9)
        continue
    d = json.loads(f.read_text())
    s, fin = d.get("surgeon") or {}, d["final"]
    cost = "n/a (local)" if s and s.get("cost_usd") is None else ("–" if not s else f"${s['cost_usd']:.4f}")
    out.append(f"| {label} | **{fin['passed']}** | {fin['failed']} / {fin['error']} | {d['kept']} | {d['reverted']} | "
               f"{d['unappliable']} | {s.get('calls', 0)} | {s.get('prompt_tokens', 0):,} / {s.get('completion_tokens', 0):,} | "
               f"{s.get('model_seconds', 0)} s | {d['wall_seconds']} s | {cost} |")
    if s.get("errors"):
        out.append(f"|  ↳ model call errors: {len(s['errors'])}: " + "; ".join(e[:120] for e in s["errors"][:3]) + " |" + " |" * 10)
print("\n".join(out))
for name, _ in rows:
    f = home / f"summary_{name}.json"
    if f.exists():
        print(f"\n{name}: kept {', '.join(json.loads(f.read_text())['kept_fixes']) or 'nothing'}", file=sys.stdout)
