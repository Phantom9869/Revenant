"""Model clients. Everything speaks one tiny interface: chat() and embed().

OllamaClient is the default and runs fully offline. BackboardClient routes the same
calls to hosted open-weight models through Backboard (needs BACKBOARD_API_KEY).
"""
from __future__ import annotations

import json
import os
import time
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


class BackboardClient:
    """Hosted open-weight models through Backboard's single API key.

    Implements the documented POST /api/threads/messages call. Not yet exercised
    against a live account; requires BACKBOARD_API_KEY.
    """

    URL = "https://app.backboard.io/api/threads/messages"

    def __init__(self, model: str, provider: str = "openrouter", api_key: str | None = None):
        self.name = f"backboard:{provider}/{model}"
        self.model, self.provider = model, provider
        self.key = api_key or os.environ.get("BACKBOARD_API_KEY")
        if not self.key:
            raise RuntimeError("BACKBOARD_API_KEY is not set")

    def chat(self, messages: list[dict], **opts) -> ChatResult:
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        convo = "\n\n".join(m["content"] for m in messages if m["role"] != "system")
        payload = {"content": convo, "system_prompt": system or None,
                   "llm_provider": self.provider, "model_name": self.model,
                   "stream": False, "memory": "off"}
        t = time.time()
        r = _post(self.URL, payload, {"X-API-Key": self.key}, timeout=600)
        text = r.get("content") or r.get("message", {}).get("content", "")
        usage = r.get("usage") or {}
        return ChatResult(text=text, model=self.name,
                          prompt_tokens=usage.get("prompt_tokens", 0),
                          completion_tokens=usage.get("completion_tokens", 0),
                          seconds=time.time() - t, raw=r)


def get_chat_model(spec: str) -> ChatModel:
    """'gemma4:e4b' -> local Ollama; 'backboard:openrouter/<model>' -> Backboard."""
    if spec.startswith("backboard:"):
        rest = spec.split(":", 1)[1]
        provider, _, model = rest.partition("/")
        return BackboardClient(model=model, provider=provider)
    return OllamaClient(spec)
