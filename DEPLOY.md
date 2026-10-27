# Deploying the Revenant web UI on Render (free tier)

Status: **prepared, not deployed.** `render.yaml` and the bundle below have been checked
locally in the same configuration (keyword retrieval, Backboard ghost, no Ollama); the
service itself has not been created on Render yet.

## What runs where

Render's free web services have no persistent disk, no GPU and 512 MB of RAM, and they
spin down when idle. So the hosted site is a read-only séance room:

| piece | locally | on Render |
|---|---|---|
| patient data | `.revenant/` built by `summon`, `autopsy`, `resurrect` | `deploy/bundle/`, exported with `revenant export` and committed |
| ghost model | Gemma 4 E4B via Ollama | a hosted open-weight model through Backboard (`REVENANT_GHOST_MODEL`) |
| retrieval | hybrid: SQLite FTS5 + EmbeddingGemma vectors | keyword only (`REVENANT_EMBED_MODEL=none`), FTS5 BM25 |
| citation check | on | on (same code) |
| summon / autopsy / resurrect | yes | no (they need git clones, a sandbox and minutes of CPU) |

Keyword-only retrieval is weaker than hybrid. In a local run with this configuration the
ghost answered the lxml question but stayed silent on "who created you, and when was your
last release?", which the hybrid retriever answers from the `tags` record.

## Steps

1. Refresh the bundle after any new run (drops the 12 MB of vectors the server can't use):

   ```bash
   revenant export psf/requests-html --to deploy/bundle --no-vectors
   git add deploy/bundle && git commit -m "Refresh deploy bundle"
   ```

2. In Render: **New → Blueprint**, pick the `Phantom9869/Revenant` repo. Render reads
   `render.yaml` and creates one free web service named `Revenant`.

3. Set the two secret env vars when Render asks (they are `sync: false`, so they never
   live in the repo):
   - `BACKBOARD_API_KEY`: the ghost's model calls.
   - `SENTRY_DSN` (optional): traces for each `POST /p/<slug>/ask`.

4. Health check: `GET /healthz` returns `ok`.

## The ghost's model

`render.yaml` sets `REVENANT_GHOST_MODEL=backboard:openrouter/dots-studio/dots-3-note-preview:free`.
That is the model that worked with this account's credit when this was written. Backboard's
free credit covers Memory & RAG but not paid LLM chat (`status: FAILED`, "Your free credit
is reserved for Memory & RAG..."), and only the `:free` models answer; see
`demo/13_backboard_probe.txt`. Free preview models can be rate-limited or withdrawn
upstream. The client retries 429s with backoff, and the page shows "The séance was
interrupted" with the error if a call still fails. With paid credit, any model from
`GET /api/models` can be used instead, for example `backboard:openrouter/google/gemma-4-31b-it`.
