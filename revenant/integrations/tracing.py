"""Optional Sentry tracing. A no-op unless SENTRY_DSN is set and sentry-sdk is installed.

Spans follow Sentry's AI agent conventions (gen_ai.*):

    revenant <command>                 transaction
    └── invoke_agent ghost|surgeon     gen_ai.invoke_agent
        ├── search_memory              gen_ai.memory.client  (hybrid retrieval)
        ├── chat gemma4:e4b            gen_ai.chat           (tokens, latency)
        └── execute_tool run_tests     gen_ai.execute_tool   (sandboxed pytest, apply_fix, fetch_archive)

Prompt and answer text is only attached when REVENANT_TRACE_CONTENT=1.
"""
from __future__ import annotations

import contextlib
import json
import os

_sdk = None


def init() -> bool:
    global _sdk
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        return False
    from .. import __version__
    sentry_sdk.init(dsn=dsn, traces_sample_rate=1.0, send_default_pii=False,
                    environment=os.environ.get("REVENANT_ENV", "local"), release=f"revenant@{__version__}",
                    debug=os.environ.get("REVENANT_SENTRY_DEBUG") == "1")
    _sdk = sentry_sdk
    return True


def enabled() -> bool:
    return _sdk is not None


def content() -> bool:
    return os.environ.get("REVENANT_TRACE_CONTENT") == "1"


def flush() -> None:
    if _sdk is not None:
        _sdk.flush(timeout=10)


def _messages(role: str, text: str) -> str:
    return json.dumps([{"role": role, "parts": [{"type": "text", "content": text}]}])


@contextlib.contextmanager
def span(op: str, name: str, **data):
    if _sdk is None:
        yield None
        return
    with _sdk.start_span(op=op, name=name) as s:
        for k, v in data.items():
            if v is not None:
                s.set_data(k, v)
        try:
            yield s
        except Exception as e:
            s.set_status("internal_error")
            s.set_data("error.type", type(e).__name__)
            raise


@contextlib.contextmanager
def transaction(name: str, op: str = "revenant"):
    if _sdk is None:
        yield None
        return
    with _sdk.start_transaction(op=op, name=name) as t:
        yield t
    import sys
    print(f"[Revenant] trace {t.trace_id} flushed to Sentry", file=sys.stderr)


def set_data(s, **data) -> None:
    if s is not None:
        for k, v in data.items():
            if v is not None:
                s.set_data(k, v)


@contextlib.contextmanager
def agent(name: str, task: str | None = None, pipeline: str = "revenant"):
    with span("gen_ai.invoke_agent", f"invoke_agent {name}", **{
            "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": name,
            "gen_ai.pipeline.name": pipeline,
            "gen_ai.input.messages": _messages("user", task) if task and content() else None}) as s:
        yield s


@contextlib.contextmanager
def tool(name: str, agent_name: str, description: str = "", **arguments):
    with span("gen_ai.execute_tool", f"execute_tool {name}", **{
            "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": name,
            "gen_ai.agent.name": agent_name, "gen_ai.tool.description": description or None,
            "gen_ai.tool.call.arguments": json.dumps(arguments, default=str) if arguments else None}) as s:
        yield s


def tool_result(s, result) -> None:
    set_data(s, **{"gen_ai.tool.call.result": json.dumps(result, default=str)})


@contextlib.contextmanager
def memory_search(store: str, agent_name: str, query: str):
    with span("gen_ai.memory.client", "search_memory", **{
            "gen_ai.operation.name": "search_memory", "gen_ai.memory.store.id": store,
            "gen_ai.agent.name": agent_name,
            "gen_ai.memory.query.text": query if content() else None}) as s:
        yield s


def record_chat(s, result) -> None:
    """Attach the response model, token counts and latency from a models.ChatResult."""
    set_data(s, **{"gen_ai.response.model": result.model,
                   "gen_ai.usage.input_tokens": result.prompt_tokens,
                   "gen_ai.usage.output_tokens": result.completion_tokens,
                   "gen_ai.usage.total_tokens": result.prompt_tokens + result.completion_tokens,
                   "revenant.model_seconds": round(result.seconds, 3)})


class TracedModel:
    """Wrap any chat model so each call becomes a `chat <model>` span."""

    def __init__(self, model, agent: str):
        self.model, self.agent, self.name = model, agent, model.name
        self.provider = "backboard" if type(model).__name__ == "BackboardClient" else "ollama"

    def available(self) -> bool:
        return getattr(self.model, "available", lambda: True)()

    def chat(self, messages, **opts):
        system = next((m["content"] for m in messages if m["role"] == "system"), None)
        rest = [{"role": m["role"], "parts": [{"type": "text", "content": m["content"]}]}
                for m in messages if m["role"] != "system"]
        with span("gen_ai.chat", f"chat {self.name}", **{
                "gen_ai.operation.name": "chat", "gen_ai.provider.name": self.provider,
                "gen_ai.request.model": self.name, "gen_ai.agent.name": self.agent,
                "gen_ai.request.temperature": opts.get("temperature", getattr(self.model, "temperature", None)),
                "gen_ai.system_instructions": system if content() else None,
                "gen_ai.input.messages": json.dumps(rest) if content() else None}) as s:
            r = self.model.chat(messages, **opts)
            record_chat(s, r)
            if content():
                set_data(s, **{"gen_ai.output.messages": _messages("assistant", r.text)})
            return r
