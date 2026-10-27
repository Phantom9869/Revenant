"""Print the span tree Revenant produces for a command, captured locally.

Runs a real CLI command with the Sentry SDK pointed at an in-process transport, so nothing
leaves the machine, then prints each transaction's spans as a tree with their gen_ai.* data.
(gen_ai spans arrive as separate span items; both kinds are joined here.) This is the same structure the real traces in demo/11_sentry_traces.txt were sent with; it is
not a screenshot of Sentry's UI.

    python demo/investigations/span_tree.py ask psf/requests-html "Why does importing requests_html fail with lxml 5.2?"
"""
import os
import sys

os.environ.pop("SENTRY_DSN", None)          # never send from this script
os.environ.pop("REVENANT_TRACE_CONTENT", None)

import sentry_sdk  # noqa: E402
from sentry_sdk.transport import Transport  # noqa: E402

from revenant import cli  # noqa: E402
from revenant.integrations import tracing  # noqa: E402

events = []
streamed = []   # gen_ai spans go out as separate span-v2 envelope items, not inside the transaction


class Capture(Transport):
    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type == "transaction":
                events.append(item.payload.json)
            elif item.type == "span":
                for sp in item.payload.json.get("items", []):
                    a = {k: v.get("value") for k, v in sp.get("attributes", {}).items()}
                    streamed.append({"trace_id": sp["trace_id"], "span_id": sp["span_id"],
                                     "parent_span_id": sp.get("parent_span_id"), "op": a.get("sentry.op"),
                                     "description": sp.get("name"), "start_timestamp": sp["start_timestamp"],
                                     "timestamp": sp["end_timestamp"], "data": a})


def init():
    sentry_sdk.init(dsn="https://public@o0.ingest.invalid/0", transport=Capture, traces_sample_rate=1.0,
                    send_default_pii=False)
    tracing._sdk = sentry_sdk
    return True


tracing.init = init
KEYS = ("gen_ai.request.model", "gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens", "revenant.model_seconds",
        "gen_ai.memory.record.count", "revenant.retrieval", "revenant.max_cosine", "gen_ai.tool.call.result",
        "revenant.claims", "revenant.claims_withheld", "revenant.refused", "revenant.citations",
        "revenant.initial", "revenant.final", "revenant.kept", "revenant.reverted")


def _t(v):
    from datetime import datetime
    return v if isinstance(v, (int, float)) else datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()


def show(ev):
    spans = ev.get("spans", []) + [s for s in streamed if s["trace_id"] == ev["contexts"]["trace"]["trace_id"]]
    # the SDK's default stdlib integration also records every subprocess call (git, uv, bwrap);
    # they are sent too, but hidden here so the agent structure is readable
    hidden = {s["span_id"] for s in spans if str(s.get("op", "")).startswith("subprocess")}
    kids = {}
    for s in spans:
        if s["span_id"] not in hidden:
            kids.setdefault(s.get("parent_span_id"), []).append(s)
    root = ev["contexts"]["trace"]
    dur = lambda s: f"{(_t(s['timestamp']) - _t(s['start_timestamp'])):.2f}s"
    print(f"{ev['transaction']}  [{root.get('op')}]  {dur(ev)}")

    def walk(pid, pre):
        cs = sorted(kids.get(pid, []), key=lambda s: _t(s["start_timestamp"]))
        for i, s in enumerate(cs):
            last = i == len(cs) - 1
            data = s.get("data", {})
            extra = ", ".join(f"{k.split('.')[-1] if k.startswith('gen_ai.usage') else k}={str(data[k])[:60]}"
                              for k in KEYS if k in data)
            print(f"{pre}{'└── ' if last else '├── '}{s.get('description')}  [{s.get('op')}]  {dur(s)}"
                  + (f"  {extra}" if extra else ""))
            walk(s["span_id"], pre + ("    " if last else "│   "))

    walk(root["span_id"], "")
    if hidden:
        print(f"({len(hidden)} subprocess spans from the SDK's stdlib integration not shown)")


try:
    cli.main(sys.argv[1:])
except SystemExit:
    pass
import time  # noqa: E402
for _ in range(3):   # streamed spans are batched in the background; give the batcher time to hand them over
    sentry_sdk.flush(timeout=5)
    time.sleep(1)
sys.stdout.flush()
print("\n--- spans captured locally (in-process transport, nothing sent) ---\n")
for ev in events:
    show(ev)
