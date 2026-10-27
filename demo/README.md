# demo/

Real outputs from Revenant's runs on `psf/requests-html`, captured on the dev box on 2026-10-27
(CPU only, Ollama). Nothing here is edited except where a NOTE says so.

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
| `09_ghost_archive.txt` | a compound question about the archive the ghost refused |
| `09_ghost_archive.json` + `.NOTE.md` | the ghost citing the archived docs, and a misattribution it made |
| `10_web.txt` | the web UI and JSON API via curl |
| `11_sentry_traces.txt` | trace ids of real traces sent to Sentry |
| `12_revenant_tests.txt` | Revenant's own test suite |
| `investigations/191_vs_192.py` + `.out.txt` | why `test_containing` says 192 and finds 191 |
