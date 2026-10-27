"""Model clients. Everything speaks one tiny interface: chat() and embed().

OllamaClient is the default and runs fully offline. BackboardClient routes the same
calls to hosted open-weight models through Backboard (needs BACKBOARD_API_KEY).
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from . import config


@dataclass
class ChatResult:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    cost_usd: float | None = None   # as reported by the provider; None when it reports nothing
    raw: dict = field(default_factory=dict, repr=False)


class ChatModel(Protocol):
    name: str

    def chat(self, messages: list[dict], **opts) -> ChatResult: ...


def _post(url: str, payload: dict, headers: dict | None = None, timeout: float = 1800) -> dict:
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, json.dumps(payload).encode(), h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


class OllamaClient:
    """Local inference through Ollama's native /api/chat (supports think=false)."""

    def __init__(self, model: str, base_url: str | None = None, num_ctx: int = 8192,
                 temperature: float = 0.2, think: bool | None = False):
        self.name = model
        self.base = (base_url or config.OLLAMA_URL).rstrip("/")
        self.num_ctx = num_ctx
        self.temperature = temperature
        self.think = think

    def chat(self, messages: list[dict], **opts) -> ChatResult:
        payload = {
            "model": self.name, "messages": messages, "stream": False,
            "options": {"num_ctx": opts.get("num_ctx", self.num_ctx),
                        "temperature": opts.get("temperature", self.temperature)},
        }
        if self.think is not None:
            payload["think"] = self.think
        t = time.time()
        r = _post(f"{self.base}/api/chat", payload)
        return ChatResult(text=r["message"]["content"], model=self.name,
                          prompt_tokens=r.get("prompt_eval_count", 0),
                          completion_tokens=r.get("eval_count", 0),
                          seconds=time.time() - t, raw=r)

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base}/api/tags", timeout=3) as r:
                names = {m["name"] for m in json.loads(r.read())["models"]}
            return self.name in names or f"{self.name}:latest" in names
        except Exception:
            return False


class OllamaEmbedder:
    """EmbeddingGemma via Ollama. Uses the model's documented task prompts."""

    QUERY = "task: search result | query: "
    DOC = "title: {title} | text: "

    def __init__(self, model: str | None = None, base_url: str | None = None):
        self.name = model or config.EMBED_MODEL
        self.base = (base_url or config.OLLAMA_URL).rstrip("/")

    def embed(self, texts: list[str]) -> list[list[float]]:
        r = _post(f"{self.base}/api/embed", {"model": self.name, "input": texts, "truncate": True})
        return r["embeddings"]

    def embed_docs(self, docs: list[tuple[str, str]]) -> list[list[float]]:
        return self.embed([self.DOC.format(title=(t or "none")[:80]) + x for t, x in docs])

    def embed_query(self, q: str) -> list[float]:
        return self.embed([self.QUERY + q])[0]


class BackboardError(RuntimeError):
    pass


class BackboardClient:
    """Hosted models through Backboard's single API key (POST /api/threads/messages).

    Each call is stateless: a fresh thread, memory off, so the only context the model
    sees is what Revenant retrieved. Token counts and cost_usd come from the response.
    """

    URL = "https://app.backboard.io/api/threads/messages"

    def __init__(self, model: str, provider: str = "openrouter", api_key: str | None = None, opener=None,
                 retries: int = 3, backoff: float = 15.0, sleep=time.sleep):
        self.retries, self.backoff, self.sleep = retries, backoff, sleep
        self.name = f"backboard:{provider}/{model}"
        self.model, self.provider = model, provider
        self.key = api_key or os.environ.get("BACKBOARD_API_KEY")
        self._post = opener or _post
        if not self.key:
            raise RuntimeError("BACKBOARD_API_KEY is not set")

    def available(self) -> bool:
        return True

    def chat(self, messages: list[dict], **opts) -> ChatResult:
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        convo = "\n\n".join(m["content"] for m in messages if m["role"] != "system")
        payload = {"content": convo, "llm_provider": self.provider, "model_name": self.model,
                   "stream": False, "memory": "off"}
        if system:
            payload["system_prompt"] = system
        t = time.time()
        for attempt in range(self.retries + 1):
            try:
                r = self._post(self.URL, payload, {"X-API-Key": self.key}, timeout=600)
            except urllib.error.HTTPError as e:
                raise BackboardError(f"Backboard HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from None
            limited = r.get("status") != "COMPLETED" and re.search(r"\b429\b|rate.limit", r.get("content") or "", re.I)
            if not limited or attempt == self.retries:
                break
            self.sleep(self.backoff * 2 ** attempt)   # free models are rate-limited upstream; wait and retry
        if r.get("status") != "COMPLETED":
            # Failures (e.g. no credit for this model) come back as a normal message with status FAILED;
            # never let that text pass as a model answer.
            raise BackboardError(f"Backboard run {r.get('status')}: {(r.get('content') or '')[:300]}")
        return ChatResult(text=r.get("content") or "", model=f"backboard:{r.get('model_provider') or self.provider}/"
                                                             f"{r.get('model_name') or self.model}",
                          prompt_tokens=r.get("input_tokens") or 0,
                          completion_tokens=r.get("output_tokens") or 0,
                          seconds=time.time() - t, cost_usd=r.get("cost_usd"), raw=r)


class Metered:
    """Wrap a chat model and add up what it reports: calls, tokens, seconds, cost."""

    def __init__(self, model):
        self.model, self.name = model, model.name
        self.calls = self.prompt_tokens = self.completion_tokens = 0
        self.seconds, self.cost_usd, self.cost_reported = 0.0, 0.0, False
        self.errors: list[str] = []

    def available(self) -> bool:
        return getattr(self.model, "available", lambda: True)()

    def chat(self, messages, **opts) -> ChatResult:
        self.calls += 1
        try:
            r = self.model.chat(messages, **opts)
        except Exception as e:
            self.errors.append(f"{type(e).__name__}: {e}"[:300])
            raise
        self.prompt_tokens += r.prompt_tokens
        self.completion_tokens += r.completion_tokens
        self.seconds += r.seconds
        if r.cost_usd is not None:
            self.cost_usd += r.cost_usd
            self.cost_reported = True
        return r

    def summary(self) -> dict:
        return {"model": self.name, "calls": self.calls, "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens, "model_seconds": round(self.seconds, 1),
                "cost_usd": round(self.cost_usd, 6) if self.cost_reported else None, "errors": self.errors}


def get_chat_model(spec: str) -> ChatModel:
    """'gemma4:e4b' -> local Ollama; 'backboard:openrouter/<model>' -> Backboard."""
    if spec.startswith("backboard:"):
        rest = spec.split(":", 1)[1]
        provider, _, model = rest.partition("/")
        return BackboardClient(model=model, provider=provider)
    return OllamaClient(spec)
