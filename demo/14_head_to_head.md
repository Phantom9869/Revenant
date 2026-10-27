# Head-to-head: who can raise requests-html?

Same patient (upstream HEAD `075ac16`, 0 passing, 2 collection errors on Python 3.13), same
network-less sandbox, same judge (the project's own offline test suite, keep an edit only if
tests improve and no passing test regresses). The code models ran with `--no-grimoire`, so
everything they changed came from them. Run on 2026-10-27, one after another on the same CPU-only
box. Commands and full output are in [`head_to_head/`](head_to_head/); the table is printed by
[`investigations/head_to_head.py`](investigations/head_to_head.py) from the `summary_h2h-*.json`
files the runs wrote.

| contender | passing (of 30) | failed / errors | kept | reverted | unappliable | model calls | tokens in / out | model time | wall time | cost reported |
|---|---|---|---|---|---|---|---|---|---|---|
| grimoire only (no model) | **30** | 0 / 0 | 4 | 1 | 0 | 0 | 0 / 0 | 0 s | 24.6 s | – |
| Qwen2.5-Coder 7B, local (Ollama, CPU) | **25** | 2 / 3 | 2 | 2 | 3 | 10 | 8,902 / 852 | 141.6 s | 157.6 s | n/a (local) |
| Dots3-Note Preview 280B-A16B, hosted (Backboard, $0 tier) | **27** | 0 / 3 | 3 | 6 | 0 | 10 | 7,856 / 44,501 | 532.7 s | 576.6 s | $0.0000 |
| Flint v1.0 40B-A2.5B, hosted (Backboard, $0 tier) | **27** | 0 / 3 | 3 | 6 | 0 | 9 | 6,901 / 63,458 | 683.7 s | 718.6 s | $0.0000 |

h2h-grimoire: kept lxml-html-clean, history-assertion:test_containing, asyncio-loop, pytest-asyncio-event-loop

h2h-qwen7b: kept surgeon:tests.test_internet, surgeon:test_containing

h2h-dots3: kept surgeon:tests.test_internet, surgeon:test_containing, surgeon:test_bare_js_eval

h2h-flint: kept surgeon:tests.test_internet, surgeon:test_containing, surgeon:test_bare_js_eval

Tokens, model time and cost are as reported by the model server: Ollama for Qwen, Backboard's
`/threads/messages` response (`input_tokens`, `output_tokens`, `cost_usd`) for the hosted
models. "Open-weight" and the parameter counts are taken from the descriptions in Backboard's
own `/models` listing ([`13_backboard_probe.txt`](13_backboard_probe.txt)).

## What happened

- **Every contender fixed the import** (`lxml_html_clean`, 0 → 24) and **restored 191 in
  test_containing** (→ 25). Only the grimoire cites the history behind 191.
- **The hosted models also fixed the event-loop breakage** in `HTMLSession.browser` (→ 27).
  Qwen 7B's two edits to `requests_html.py` never applied: their SEARCH text was not in the
  file. A third SEARCH block, for the test file, missed as well.
- **Nobody but the grimoire fixed the removed `event_loop` fixture** (pytest-asyncio 1.0), so
  three async tests still error at setup. Every model edit aimed at those tests either regressed
  passing tests or changed nothing, and was reverted.
- **The regression guard did real work.** Flint's first attempt at `test_async_file_get` regressed
  all 24 passing tests, and one Qwen edit regressed all 25. Both were reverted.
- **The hosted models wrote far more.** They returned 44k–63k output tokens over 9–10 calls
  (about 53–76 s a call on the free tier). Qwen spent 852 tokens in 142 s on the CPU.
- **Cost:** the hosted runs were on Backboard's $0 tier and reported $0.0000. Qwen runs locally,
  so there is no cost to report.

## Conditions and caveats

- The free tier is rate-limited upstream. An earlier attempt at both hosted runs died on a dropped
  connection and an upstream 429. Revenant now retries 429s with backoff and records a failed
  model call as an unappliable attempt. The runs above had no model errors.
- One Qwen run was discarded because it overlapped a hosted run on the same CPU. It also ended at
  25 passing (11 calls, 8,862 / 955 tokens). The Qwen row is a clean rerun with nothing else using
  Ollama.
- While the hosted runs were waiting on Backboard, a few short local commands (ghost questions, a
  23 s grimoire run for the span-tree capture) shared the CPU. That affects the sandboxed test
  runs inside their wall time, not the model time.
- The larger paid open-weight coders in Backboard's catalogue (e.g. `qwen/qwen3-coder`) were not
  run. The account's free credit is reserved for memory and RAG, and LLM chat on paid models
  returns `FAILED` ([`13_backboard_probe.txt`](13_backboard_probe.txt)).
- One run per contender. Model output varies between runs.
