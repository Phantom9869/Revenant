# Certificate of Death: psf/requests-html

*Examined 2026-10-27 by Revenant. Python 3.13 (x86_64), tests run inside a network-less bubblewrap sandbox.*

## The deceased

- **Last commit:** [`075ac16`](https://github.com/psf/requests-html/commit/075ac162dc62fc532037df0d98954ab840a97516) on 2023-04-03 by surister: "Merge pull request #539 from Skaylan/fix-typo"
- **Last non-merge commit:** [`efb2484`](https://github.com/psf/requests-html/commit/efb2484eef1c27a7567409dd380d33ec66a569f5) on 2023-03-16: "fix typo at docs"
- **First commit:** `7fb775b` on 2018-02-24 by Kenneth Reitz
- **Commits:** 462 total

```
2018  █████████████████████████████████████████ 410
2019  ███                                       30
2020  █                                         10
2021  █                                         2
2022  █                                         1
2023  █                                         9
```

## Post-mortem test run

Command (from Pipfile): `pytest -m not internet` with test deps `pytest, requests-file, pytest-asyncio`

| passed | failed | errors | skipped | seconds |
|---|---|---|---|---|
| 0 | 0 | 2 | 0 | 0.7 |

## Cause of death

### 1. lxml.html.clean was split out of lxml

lxml 5.2.0 (2024) moved lxml.html.clean into the separate lxml_html_clean package; importing it from lxml raises ImportError.

- **Evidence:** `E   ImportError: lxml.html.clean module is now a separate project lxml_html_clean.`
- **Where:** `requests_html.py:15`
- **Tests killed (2):** `tests.test_internet`, `tests.test_requests_html`
- **Witnesses in the issue tracker:** [#569](https://github.com/psf/requests-html/issues/569) LXML 5.2.0 breaks import; [#576](https://github.com/psf/requests-html/issues/576) Basic doc example no longer works; [#558](https://github.com/psf/requests-html/issues/558#issuecomment-2031436636) Consider switching from lxml's clean_html for enhanced security (and…

## Vital signs outside the code

| sign | status | detail |
|---|---|---|
| CI: .travis.yml | **dead** | Travis CI's free travis-ci.org service shut down in 2021; this config no longer runs anywhere. |
| Docs/site: html.python-requests.org | **dead** | URLError: <urlopen error [SSL: SSLV3_ALERT_HANDSHAKE_FAILURE] ssl/tls alert handshake failure (_ssl.c:1029)>. DNS: readthedocs.io -> 104.16.254.120 -> 104.16.253.120. Last archived snapshot: 2022-10-26 http://web.archive.org/web/20221026182615/https://html.python-requests.org/ |
| Docs/site: kennethreitz.com | **alive** | HTTP 200, title: kennethreitz.com |
| Docs/site: requests-html.kennethreitz.org (linked 8x in the tracker) | **stale** | HTTP 200, but the page is titled v0.3.4 while the latest release is 0.10.0 (title: Requests-HTML: HTML Parsing for Humans (writing Python 3)! — requests-HTML v0.3.4 documentation). The Sphinx config still says `release = 'v0.3.4'` (docs/source/conf.py) |
| PyPI | **stale** | latest release requests-html 0.10.0 on 2019-02-17; requires_python: >=3.6.0 |
