"""What can this Backboard key actually do? Lists models and prices from the API and
tries one paid and one $0 open-weight model. Prints no key, no thread ids.

    BACKBOARD_API_KEY=... python demo/investigations/backboard_probe.py
"""
import json
import os
import re
import urllib.request

BASE = "https://app.backboard.io/api"
H = {"X-API-Key": os.environ["BACKBOARD_API_KEY"], "Content-Type": "application/json"}


def get(path):
    with urllib.request.urlopen(urllib.request.Request(BASE + path, headers=H), timeout=60) as r:
        return json.loads(r.read())


def chat(model):
    body = json.dumps({"content": "Reply with the single word: ok", "llm_provider": "openrouter",
                       "model_name": model, "stream": False, "memory": "off"}).encode()
    with urllib.request.urlopen(urllib.request.Request(BASE + "/threads/messages", body, H), timeout=300) as r:
        d = json.loads(r.read())
    keep = ("status", "model_provider", "model_name", "input_tokens", "output_tokens", "total_tokens", "cost_usd")
    return {k: d.get(k) for k in keep} | {"content": (d.get("content") or "")[:220]}


providers = get("/models/providers")
print("providers:", ", ".join(p if isinstance(p, str) else p.get("name", str(p)) for p in
                              (providers.get("providers", providers) if isinstance(providers, dict) else providers)))
models, skip = [], 0
while True:
    page = get(f"/models?model_type=llm&provider=openrouter&skip={skip}&limit=500")
    models += page["models"]
    skip += len(page["models"])
    if not page["models"] or skip >= page["total"]:
        break
print(f"openrouter LLMs listed: {len(models)}")
bal = get("/billing/balance")
print("balance:", {k: bal.get(k) for k in ("balance_usd", "free_credit_usd", "paid_credit_usd")})


def row(m):
    return (f"  {m['name']:<44} ctx {m['context_limit'] or '?':>8}  in ${m['input_cost_per_1m_tokens']}/1M"
            f"  out ${m['output_cost_per_1m_tokens']}/1M")


print("\n$0 models (description excerpt):")
for m in models:
    if not (m["input_cost_per_1m_tokens"] or m["output_cost_per_1m_tokens"]):
        print(row(m))
        print("     ", (m.get("description") or "")[:170].replace("\n", " "))
print("\nmodels whose own description says open-weight / open-source, coding-related:")
for m in sorted(models, key=lambda m: m["input_cost_per_1m_tokens"] or 0):
    d = m.get("description") or ""
    if re.search(r"open[- ]weight|open[- ]source", d, re.I) and re.search(r"cod", m["name"] + d[:300], re.I):
        print(row(m))
print("\nlarger open-weight coding models (listed by family; prices from the API):")
for name in ("qwen/qwen3-coder", "qwen/qwen3-coder-30b-a3b-instruct", "qwen/qwen-2.5-coder-32b-instruct",
             "mistralai/devstral-2512", "openai/gpt-oss-120b", "deepseek/deepseek-v3.2", "z-ai/glm-4.7"):
    m = next((m for m in models if m["name"] == name), None)
    print(row(m) if m else f"  {name}: not listed")

for model in ("qwen/qwen3-coder", "dots-studio/dots-3-note-preview:free"):
    print(f"\nPOST /threads/messages  model={model}")
    print(json.dumps(chat(model), indent=2))
