from revenant.diagnose import Outcome
from revenant.resurrect import judge


class Exam:
    def __init__(self, **status):
        self.outcomes = [Outcome(t, s) for t, s in status.items()]


def test_judge_keeps_strict_improvements():
    ok, why = judge(Exam(a="passed", b="failed"), Exam(a="passed", b="passed"))
    assert ok and "passing 1 -> 2" in why


def test_judge_reverts_regressions_even_if_net_positive():
    ok, why = judge(Exam(a="passed", b="failed", c="failed"), Exam(a="failed", b="passed", c="passed"))
    assert not ok and why.startswith("regressed 1 passing test(s): a")


def test_judge_reverts_no_change():
    ok, why = judge(Exam(a="failed"), Exam(a="failed"))
    assert not ok and why.startswith("no improvement")


def test_collection_error_replaced_by_real_tests_counts_as_progress():
    ok, _ = judge(Exam(mod="error"), Exam(t1="passed", t2="failed", t3="failed"))
    assert ok


def test_surgeon_model_failure_is_recorded_not_fatal(tmp_path):
    from types import SimpleNamespace

    from revenant.diagnose import Outcome
    from revenant.resurrect import _surgeon_fixes

    class Down:
        name = "backboard:openrouter/x"

        def chat(self, messages, **o):
            raise ConnectionResetError("Remote end closed connection without response")

    (tmp_path / "m.py").write_text("x = 1\n")
    exam = SimpleNamespace(outcomes=[Outcome("tests/test_m.py::test_x", "failed", "boom", "m.py:1")],
                           tally={"passed": 0, "failed": 1, "error": 0, "skipped": 0})
    res = SimpleNamespace(attempts=[])
    fixes, meta = _surgeon_fixes(Down(), tmp_path, exam, set(), 2, res, lambda *_: None)
    assert fixes == [] and len(res.attempts) == 2
    assert all(a.verdict == "unappliable" and "model call failed: ConnectionResetError" in a.reason for a in res.attempts)
