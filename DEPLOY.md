# Deploying the Revenant web UI on Render (free tier)

Status: **deployed.** Live at <https://revenant-zaq3.onrender.com>, created from
`render.yaml` as a Blueprint on Render's free plan, with this public repo as the source.

Checked on the live service: the first deploy took 1m21s; `GET /healthz` returns 200;
`/`, `/p/psf/requests-html`, `/certificate` and `/resurrection` return 200; and a live
`POST /p/psf/requests-html/ask` answered the lxml question with per-sentence citation
verdicts (the checker flagged one sentence as unsupported).

Caveats:

- The free tier sleeps when idle, so the first request after a quiet spell can take
  about 30–60 s while the service wakes up.
- The ghost uses a free preview model on Backboard (see below), which can be
  rate-limited or withdrawn upstream.
- `SENTRY_DSN` is not set on the live service, so it sends no traces.
- Auto-deploy is not configured (the repo is used as a public git source, without the
  Render GitHub app), so after a push a redeploy has to be started by hand in the
  Render dashboard (**Manual Deploy → Deploy latest commit**).

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

2. In Render: **New → Blueprint**, pick the `Phantom9869/Revenant` repo (the live service
   uses the public repo URL as its source). Render reads
   `render.yaml` and creates one free web service named `Revenant`.

3. Set the secret env vars when Render asks (they are `sync: false`, so they never
   live in the repo). On the live service only `BACKBOARD_API_KEY` is set:
   - `BACKBOARD_API_KEY`: the ghost's model calls.
   - `SENTRY_DSN` (optional): traces for each `POST /p/<slug>/ask`.

4. Health check: `GET /healthz` returns `ok`. The server binds to `$PORT`, which Render
   sets, and logs `Revenant web on http://0.0.0.0:<port>` at startup.

`demo/18_render_config.txt` is a local run of this exact configuration: the server on
`PORT=10000` with the committed bundle, no Ollama, and the ghost on Backboard. It shows
the page status codes and two `POST /p/psf/requests-html/ask` answers.

## The ghost's model

`render.yaml` sets `REVENANT_GHOST_MODEL=backboard:openrouter/dots-studio/dots-3-note-preview:free`.
That is the model that worked with this account's credit when this was written. Backboard's
free credit covers Memory & RAG but not paid LLM chat (`status: FAILED`, "Your free credit
is reserved for Memory & RAG..."), and only the `:free` models answer; see
`demo/13_backboard_probe.txt`. Free preview models can be rate-limited or withdrawn
upstream. The client retries 429s with backoff, and the page shows "The séance was
interrupted" with the error if a call still fails. With paid credit, any model from
`GET /api/models` can be used instead, for example `backboard:openrouter/google/gemma-4-31b-it`.
