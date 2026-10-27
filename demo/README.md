# demo/

Real outputs from Revenant's runs on `psf/requests-html`, captured on the dev box on 2026-10-27
(UTC; CPU only, Ollama locally, Backboard for the hosted models). Nothing here is edited except
where a NOTE says so, where a `$ command` header line was added above the output, or where
the dev box's absolute checkout path was shortened to a repo-relative one (`.revenant/...`).

| file | what |
|---|---|
| `01_summon.txt` | re-summon (everything already cached and embedded) |
| `02_ghost.txt` | four questions: two answered, one refused by the model, one refused before any model call |
| `03_ghost_json.json` | `ask --json` output |
| `04_autopsy.txt`, `death_certificate.md`, `before_pytest.txt` | the autopsy at upstream HEAD `075ac16` |
| `05_resurrect.txt`, `RESURRECTION_LOG.md`, `fork_commits.txt` | grimoire + surgeon resurrection, matrix, aftercare |
| `06_surgeon_only.txt`, `RESURRECTION_LOG_surgeon_only.md` | Qwen2.5-Coder 7B alone (`--no-grimoire`) |
| `07_browserbase_wayback.txt` | one Wayback fetch through Browserbase, then a disk-cache hit |
| `08_summon_archive.txt` | ingesting the 2019 snapshot of the dead docs site |
| `09_ghost_archive.json` + `.NOTE.md` | the ghost citing the archived docs, with the citation check on, and a sentence it withheld |
| `10_web.txt` | the web UI and JSON API via curl |
| `11_sentry_traces.txt` | trace ids of real traces sent to Sentry |
| `12_revenant_tests.txt` | Revenant's own test suite |
| `13_backboard_probe.txt` | Backboard's providers, model ids and prices from its API, and which models answer on this account |
| `14_head_to_head.md`, `head_to_head/` | grimoire vs. Qwen2.5-Coder 7B (local) vs. Dots3 and Flint (Backboard) |
| `15_span_tree_local.txt` | the Sentry span tree of `ask` and `resurrect`, captured locally (not the Sentry UI) |
| `16_recheck_saved_answers.txt` | the answers saved before the citation check, replayed through it |
| `17_ghost_backboard.txt` | the ghost voiced by Dots3-Note Preview on Backboard |
| `18_render_config.txt` | the Render configuration (bundle, keyword retrieval, Backboard ghost) run locally |
| `before_support_check/` | ghost outputs from before the per-sentence citation check, unedited |
| `before_redesign/` | the web demo from before the UI redesign |
| `investigations/191_vs_192.py` + `.out.txt` | why `test_containing` says 192 and finds 191 |
| `investigations/backboard_probe.py`, `head_to_head.py`, `span_tree.py`, `recheck_saved_answers.py` | the scripts behind 13–16 |
