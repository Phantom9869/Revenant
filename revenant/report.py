"""Write the resurrection log."""
from __future__ import annotations

from datetime import date


def tally_row(label: str, t: dict | None) -> str:
    if not t:
        return f"| {label} | - | - | - |"
    return f"| {label} | {t['passed']} | {t['failed']} | {t['error']} |"


def resurrection_log(res, notes: list[str] | None = None, title_extra: str = "", usage: dict | None = None) -> str:
    p = res.patient
    L = [f"# Resurrection log: {p.slug}{title_extra}", "",
         f"*{date.today().isoformat()}, branch `revenant/resurrection` of a local clone. "
         f"Every change below was applied as an exact text edit, followed by a full re-run of the "
         f"project's own offline test suite in a network-less sandbox. Changes that did not help, "
         f"or broke a passing test, were reverted.*", "",
         "| stage | passed | failed | errors |", "|---|---|---|---|",
         tally_row("before (Python 3.13, today's dependencies)", res.initial.tally),
         tally_row("after", res.final.tally if res.final else None), "", "## Operations", ""]
    for i, a in enumerate(res.attempts, 1):
        L.append(f"### {i}. {a.fix.title} ({a.verdict.upper()})")
        L.append("")
        L.append(f"- **Source:** {a.fix.source}" + (f" (model time {a.model_seconds:.1f}s)" if a.model_seconds else ""))
        L.append(f"- **Why:** {a.fix.why}")
        if a.fix.citations:
            L.append("- **History cited:** " + ", ".join(f"[`{c}`]({p.url}/commit/{c})" for c in a.fix.citations))
        L.append(f"- **Verdict:** {a.reason}" + (f", committed as `{a.commit}`" if a.commit else ""))
        if a.diff:
            L += ["", "```diff", a.diff.strip()[:4000], "```"]
        L.append("")
    if getattr(res, "matrix", None):
        L += ["## Python matrix (after)", "", "| python | passed | failed | errors | verdict |", "|---|---|---|---|---|"]
        for py, t in res.matrix.items():
            if "error" in t and isinstance(t.get("error"), str):
                L.append(f"| {py} | - | - | - | install failed: {t['error'][:120]} |")
            else:
                L.append(f"| {py} | {t['passed']} | {t['failed']} | {t['error']} | {'green' if t['ok'] else 'red'} |")
        L.append("")
    if notes:
        L += ["## Aftercare", ""] + [f"- {n}" for n in notes] + [""]
    if res.final:
        left = [o for o in res.final.outcomes if o.status in ("failed", "error")]
        if left:
            L += ["## Still dead", ""] + [f"- `{o.test}`: {o.message[:200]}" for o in left] + [""]
    if usage:
        cost = "not reported" if usage.get("cost_usd") is None else f"${usage['cost_usd']:.6f}"
        L += ["## Surgeon usage (as reported by the model server)", "",
              "| model | calls | input tokens | output tokens | model time | cost |", "|---|---|---|---|---|---|",
              f"| `{usage['model']}` | {usage['calls']} | {usage['prompt_tokens']} | {usage['completion_tokens']} "
              f"| {usage['model_seconds']}s | {cost} |", ""]
        if usage.get("errors"):
            L += ["Model call errors:", ""] + [f"- {e}" for e in usage["errors"]] + [""]
    return "\n".join(L)
