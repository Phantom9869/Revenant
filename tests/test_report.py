"""The resurrection log: what it records about each operation, the matrix, and what is left."""
from types import SimpleNamespace as NS

from revenant.config import Patient
from revenant.diagnose import Outcome
from revenant.report import resurrection_log
from revenant.surgeon.edits import Fix


def _exam(passed=0, failed=0, error=0, left=()):
    return NS(tally={"passed": passed, "failed": failed, "error": error}, outcomes=list(left))


def _res(**kw):
    kept = NS(fix=Fix("lxml", "Depend on lxml_html_clean", [], "lxml 5.2 split it out", citations=["c7d07a0"]),
              verdict="kept", reason="passing 0 -> 24", commit="0e97c6d", diff="+lxml_html_clean\n", model_seconds=0.0)
    reverted = NS(fix=Fix("surgeon:t", "Surgeon's edit for t", [], "proposed", source="surgeon:qwen"),
                  verdict="reverted", reason="regressed 3 passing tests", commit="", diff="", model_seconds=12.34)
    base = dict(patient=Patient("psf/requests-html"), initial=_exam(error=2), final=_exam(passed=30),
                attempts=[kept, reverted])
    return NS(**{**base, **kw})


def test_log_records_each_operation_with_its_verdict_and_evidence():
    md = resurrection_log(_res())
    assert md.startswith("# Resurrection log: psf/requests-html\n")
    assert "| before (Python 3.13, today's dependencies) | 0 | 0 | 2 |" in md and "| after | 30 | 0 | 0 |" in md
    assert "### 1. Depend on lxml_html_clean (KEPT)" in md and "### 2. Surgeon's edit for t (REVERTED)" in md
    assert "[`c7d07a0`](https://github.com/psf/requests-html/commit/c7d07a0)" in md
    assert "- **Verdict:** passing 0 -> 24, committed as `0e97c6d`" in md
    assert "- **Source:** surgeon:qwen (model time 12.3s)" in md
    assert "```diff\n+lxml_html_clean\n```" in md
    assert "Still dead" not in md and "Python matrix" not in md and "Surgeon usage" not in md


def test_log_lists_matrix_aftercare_survivors_and_usage():
    left = [Outcome("tests/test_x.py::test_render", "error", "Chromium not found")]
    res = _res(final=_exam(passed=27, error=1, left=left),
               matrix={"3.9": {"passed": 30, "failed": 0, "error": 0, "ok": True},
                       "3.8": {"error": "no matching distribution"}})
    usage = {"model": "qwen2.5-coder:7b", "calls": 10, "prompt_tokens": 8902, "completion_tokens": 852,
             "model_seconds": 141.6, "cost_usd": None, "errors": ["timeout"]}
    md = resurrection_log(res, notes=["Added GitHub Actions CI"], usage=usage)
    assert "| 3.9 | 30 | 0 | 0 | green |" in md
    assert "| 3.8 | - | - | - | install failed: no matching distribution |" in md
    assert "## Aftercare\n\n- Added GitHub Actions CI" in md
    assert "## Still dead\n\n- `tests/test_x.py::test_render`: Chromium not found" in md
    assert "| `qwen2.5-coder:7b` | 10 | 8902 | 852 | 141.6s | not reported |" in md
    assert "Model call errors:\n\n- timeout" in md
