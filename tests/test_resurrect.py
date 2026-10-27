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
