# Revenant

*A séance for abandoned open-source software.*

> Project started **Oct 27, 2026**.

Every dead repository still has a voice: thousands of commits, issues, reviews and docs written by
the people who kept it alive. Revenant gathers that voice, lets you **talk to the ghost** of the
project, performs an **autopsy** to find out what actually killed it, and then attempts a
**resurrection**: one small, verified edit at a time, each one judged by the project's own test suite.

The first patient is [`psf/requests-html`](https://github.com/psf/requests-html) (last release
0.10.0, February 2019). On today's Python it does not even import.

| | before | after |
|---|---|---|
| test suite (Python 3.13, today's dependencies) | 0 passed, 2 collection errors | **30 passed, 0 failed** |
| Python 3.9 / 3.10 / 3.11 / 3.12 / 3.13 | – | 30 / 30 / 30 / 30 / 30 passing |
| CI | `.travis.yml` (travis-ci.org shut down in 2021) | GitHub Actions workflow, weekly cron |
| docs site | `html.python-requests.org`: TLS failure; Wayback shows "Domain Suspension" by 2022-10-26 | archived 2019 docs ingested into the ghost's memory |

All numbers in this README come from runs saved under [`demo/`](demo/).

## The three rites

### 1. Summon: build the ghost's memory

```
revenant summon psf/requests-html
```

Clones the repo, harvests issues, PRs, comments and reviews from the GitHub API (cached on disk,
resumable when rate-limited), and stores **2,810 documents** (462 commits, 693 issues, 235 PRs,
1,368 comments, 21 reviews, 29 doc pages, 2 records) in SQLite with an FTS5 index and
**EmbeddingGemma** vectors.

Dead documentation can be raised too:

```
revenant summon psf/requests-html --archive https://web.archive.org/web/20190915235734/http://html.python-requests.org:80/
```

The snapshot is fetched through the **Browserbase** Fetch API when `BROWSERBASE_API_KEY` is set (direct
otherwise), cached on disk so every page is fetched once, and becomes citable as
`[archive:html.python-requests.org@2019-09-15]`.

### 2. Ask the ghost

```
$ revenant ask psf/requests-html -v "Why does importing requests_html fail with lxml 5.2?"
Importing requests-html fails with LXML 5.2.0 because the `lxml.html.clean` module is no longer
bundled, as it has become a separate project named `lxml_html_clean` [#569]. ...

  [#569] https://github.com/psf/requests-html/issues/569#issuecomment-3702652256
  [#576] https://github.com/psf/requests-html/issues/576
```

The ghost is **Gemma 4 E4B** (via Ollama, thinking off), answering in first person from its own
history. It follows strict rules:

- Retrieval is hybrid (BM25 + EmbeddingGemma cosine, fused with reciprocal rank fusion).
- If nothing relevant is retrieved (max cosine < 0.30), it refuses **without calling the model**:
  *"The spirits are silent. Nothing in my records speaks to that."*
- Every citation in the answer is checked against the evidence actually retrieved. Invented refs are
  stripped, and an answer with no verifiable citation left becomes a refusal.

### 3. Autopsy and resurrection

```
revenant autopsy psf/requests-html      # writes a death certificate
revenant resurrect psf/requests-html    # fixes it on a local branch
```

The **autopsy** runs the project's own tests (the command comes from its Pipfile) inside a
**bubblewrap sandbox with no network**. It classifies the failures and finds witnesses in the issue
tracker. It also checks vital signs outside the code: CI config, docs hosts (DNS via DoH, TLS, page
title vs. latest release, last Wayback snapshot) and PyPI metadata. See
[`demo/death_certificate.md`](demo/death_certificate.md).

The **resurrection** loop:

1. Re-run the suite and classify what is failing.
2. Pick a cure. The **grimoire** (known, explainable cures for common causes of death) goes first,
   then the **surgeon**, **Qwen2.5-Coder 7B**, which may only answer with exact SEARCH/REPLACE edits
   to files it was shown.
3. Apply the edit only if every SEARCH block matches exactly once. Re-run the full suite in the sandbox.
4. Keep the edit and commit it if tests improved and **no passing test regressed**. Otherwise `git reset --hard`.
5. When the suite is green: verify across Python 3.9–3.13, then aftercare. Aftercare adds GitHub
   Actions CI, removes the dead Travis config and badge, declares the Python versions that actually
   pass, and fixes the docs release label.

Everything is logged to [`RESURRECTION_LOG.md`](demo/RESURRECTION_LOG.md), with diffs and verdicts,
including what was reverted.

## What killed requests-html

| # | cause | where | cure |
|---|---|---|---|
| 1 | lxml 5.2 (2024) split `lxml.html.clean` into `lxml_html_clean`; the import fails | `requests_html.py:15` | depend on `lxml_html_clean` |
| 2 | `asyncio.get_event_loop()` no longer creates loops implicitly | `HTMLSession.browser`, `AsyncHTMLSession.__init__` | helper: running loop, else this thread's loop, else a new one |
| 3 | pytest-asyncio 1.0 removed the `event_loop` fixture | `tests/test_requests_html.py` | async fixture via `pytest_asyncio.fixture` |
| 4 | `test_containing` expects 192 elements, finds 191 | test | restore 191, citing history (below) |

The grimoire's first try at cure 3 **regressed three render tests**, so it was reverted. Once cure 2
landed, the loop gave it one more chance and it took the suite from 27 to 30 passing. The regression
guard is the point: nothing that breaks a passing test survives.

### The truth about 191 vs 192

[`demo/investigations/191_vs_192.py`](demo/investigations/191_vs_192.py) ([output](demo/investigations/191_vs_192.out.txt)) shows:

- `== 191` was written by Kenneth Reitz in `c7d07a0` (2018-03-03, "containing test").
- `3348215` (2018-09-18, "Fix tests") changed it to 192. It reached master through PR #146.
- The fixture `tests/python.html` has not changed since 2018-02-26 (pure ASCII, 48,883 bytes).
- 237 historical versions of `requests_html.py` were run against it. 82 still run today: 80 find
  **191**, and the only other result, 529, comes from two versions older than the test itself.
- lxml 4.9.4, 5.1.1, 5.3.0 and 6.0.0 all give 191. **No environment tried produced 192.**

The history-based cure therefore restores 191 and cites both commits. The code-model surgeon,
run alone, made the same one-character change, but with no evidence for it. Compare
[`demo/RESURRECTION_LOG.md`](demo/RESURRECTION_LOG.md) with
[`demo/RESURRECTION_LOG_surgeon_only.md`](demo/RESURRECTION_LOG_surgeon_only.md).

## Grimoire vs. surgeon (Qwen2.5-Coder 7B alone)

Same patient, same sandbox, same judge, `--no-grimoire`:

| | grimoire + surgeon | surgeon only |
|---|---|---|
| result | 30 passed, 0 failed | 25 passed, 2 failed, 3 errors |
| kept edits | 4 | 2 (lxml dependency, 192→191) |
| asyncio loop / fixture breakage | fixed | not fixed |
| bad edits caught | 1 reverted (regression), later re-tried and kept | 2 unappliable (SEARCH text not in the file); 2 reverted for regressions, one of which broke the import and all 25 passing tests; 2 reverted for no improvement |

A 7B model on a CPU can fix a well-described ImportError. Here it could not untangle the
event-loop changes. The exact-match edit format and the regression guard kept its bad ideas out of
the tree.

## Install

Requirements: Linux, Python ≥ 3.11, `git`, [`uv`](https://github.com/astral-sh/uv) (builds the
patient's virtualenvs), `bwrap` (bubblewrap) for the sandbox, and [Ollama](https://ollama.com) with:

```
ollama pull gemma4:e4b
ollama pull embeddinggemma
ollama pull qwen2.5-coder:7b
```

```
pip install -e '.[test]'          # add ,sentry for tracing
export GITHUB_TOKEN=...           # optional, raises the API rate limit
revenant summon psf/requests-html
```

Data goes to `$REVENANT_HOME` (default `./.revenant`). Commits in the revived fork use
`REVENANT_GIT_NAME` / `REVENANT_GIT_EMAIL` when set. `revenant serve` starts a small web UI with
the certificate, the resurrection log and an ask box (JSON API: `POST /p/<owner>/<repo>/ask`).

## Partners (optional, all behind environment variables)

| variable | what it enables |
|---|---|
| `BROWSERBASE_API_KEY` | Wayback snapshots fetched through the Browserbase Fetch API (proxied for web.archive.org), cached on disk |
| `SENTRY_DSN` (+ `pip install '.[sentry]'`) | traces for every command, using Sentry's AI agent conventions (below) |
| `BACKBOARD_API_KEY` | `--model backboard:<provider>/<model>` voices the ghost through Backboard instead of Ollama |
| `render.yaml` | Render blueprint for the web UI (health check, persistent disk) |

Sentry span tree (prompt and answer text only with `REVENANT_TRACE_CONTENT=1`):

```
revenant ask | autopsy | resurrect          transaction
└── invoke_agent ghost | resurrectionist | surgeon
    ├── search_memory                        gen_ai.memory.client (records, max cosine)
    ├── chat gemma4:e4b | qwen2.5-coder:7b   gen_ai.chat (input/output/total tokens, latency)
    └── execute_tool run_tests | apply_fix | fetch_archive
```

## Status

**Verified** (run end to end on the dev box; outputs in `demo/`):

- summon: GitHub harvest with cache, git history, SQLite + FTS5 + EmbeddingGemma index
- ghost: cited answers, citation checking, refusals with and without a model call (CLI and web JSON API)
- autopsy in a network-less bwrap sandbox; death certificate with causes, witnesses and vital signs
- resurrection with the grimoire: 0 → 30 passing, with regression-guarded reverts, commits in a local fork
- surgeon-only resurrection with Qwen2.5-Coder 7B (results above)
- Python 3.9–3.13 matrix; aftercare edits (each re-verified by the test suite)
- 191 vs 192 investigation
- Browserbase: one real Wayback fetch through the Fetch API, cached; archived docs ingested and cited by the ghost
- Sentry: real traces sent from `ask`, `autopsy` and `resurrect` (trace ids in `demo/11_sentry_traces.txt`);
  span structure covered by an offline test
- 64 unit tests (`pytest`, output in `demo/12_revenant_tests.txt`)

**Implemented but untested:**

- Backboard as the ghost's voice (no API key yet)
- Render deployment from `render.yaml`
- The generated GitHub Actions workflow (written into the fork, never run; the fork was never pushed)
- Patients other than requests-html

**Planned:**

- Per-sentence support checking for citations. Today the ghost checks that a cited ref was among the
  retrieved evidence, not that it supports the sentence
  (see [`demo/09_ghost_archive.NOTE.md`](demo/09_ghost_archive.NOTE.md)).
- More grimoire cures (`imp` and `distutils` removals are diagnosed but have no cure yet)
- Opening the resurrection as a pull request, with the log as its description
- Surgeon calls with more context (multiple files, retrieval from the ghost's memory)

## Caveats

- All model timings are CPU-only (no GPU): EmbeddingGemma embedded 2,808 docs in about 157 s on the
  first summon, ghost answers take 6–28 s (the slow end includes model load), and surgeon calls
  take 7–25 s each (two surgeon-only runs).
- The sandbox needs `bwrap`. Without it, tests run unsandboxed and the certificate says so.
- Render tests need Chromium. Pyppeteer's Chromium must be downloaded before the sandboxed run,
  because the sandbox has no network.
- `web.archive.org` was unreachable from the dev box directly, and Browserbase's un-proxied fetches of
  it failed. Proxied fetches worked. `archive.org`'s availability API rate-limits bursts (handled with
  backoff), so a full snapshot URL can be passed instead.
- The fork lives on a local branch under `.revenant/`. Nothing is pushed anywhere.

## Layout

```
revenant/
  cli.py              summon | ask | autopsy | resurrect | serve
  config.py           patient paths, model names
  models.py           Ollama chat/embeddings, Backboard client
  harvest/            GitHub API (cached, paged) and git history
  memory/             SQLite store, ingestion, hybrid retrieval
  ghost.py            persona, refusals, citation checking
  sandbox.py          test plan detection, bwrap runner
  diagnose.py         junit parsing, causes of death
  vitals.py           CI, docs hosts, DNS, Wayback, PyPI
  autopsy.py          death certificate
  surgeon/            exact edits, grimoire cures, code-model surgeon
  resurrect.py        the keep-or-revert loop
  aftercare.py        Python matrix, CI, metadata
  report.py           resurrection log
  integrations/       Sentry tracing, Wayback + Browserbase
  web/app.py          small stdlib web UI
tests/                unit tests
demo/                 real outputs from the runs described above
```

## License

MIT © 2026 Phantom9869
