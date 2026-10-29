# Contributing to Revenant

Issues and pull requests are welcome, especially new grimoire cures, new patients, and
cases where the citation check gets a sentence wrong.

## Set up

```
python -m venv .venv && . .venv/bin/activate
pip install -e '.[test]'
pytest -q
```

The unit tests need only Python ≥ 3.11 and `git`. They stub every model and web service, so
they run offline and need no API keys. The sandbox test is skipped when `bwrap` isn't usable,
and the Sentry test when `sentry-sdk` isn't installed.

Running Revenant on a real patient needs more (Ollama, `uv`, `bwrap`); see
[Install](README.md#install).

## Ground rules

- **Numbers come from runs.** Anything the README or a report states should come from an
  output saved under `demo/`. Don't hand-edit those outputs; re-run and save new ones.
- **The ghost doesn't guess.** Changes to `ghost.py` or `citecheck.py` should keep every claim
  cited and checked. Add a test for any sentence the check now accepts or rejects differently.
- **The resurrectionist doesn't cheat.** A cure is kept only when the project's own tests
  improve and no passing test regresses. Never skip, delete or weaken a patient's tests.
- **No secrets in the repo.** Keys (`BACKBOARD_API_KEY`, `BROWSERBASE_API_KEY`, `SENTRY_DSN`,
  `GITHUB_TOKEN`) come from the environment only.
- Keep the web UI free of external assets, and keep both themes at WCAG AA contrast
  (`tests/test_web.py` checks both).
