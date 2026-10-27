import textwrap

from revenant.diagnose import RULES, Symptom
from revenant.surgeon import grimoire
from revenant.surgeon.edits import apply_fix

RULE = {r.id: r for r in RULES}


def test_lxml_html_clean_adds_dependency(tmp_path):
    (tmp_path / "setup.py").write_text("REQUIRED = [\n    'requests', 'lxml'\n]\nsetup(install_requires=REQUIRED)\n")
    fix = grimoire.cure_lxml_html_clean(tmp_path, Symptom(RULE["lxml-html-clean"]))
    apply_fix(tmp_path, fix)
    assert "'requests', 'lxml', 'lxml_html_clean'" in (tmp_path / "setup.py").read_text()
    assert fix.reinstall
    assert grimoire.cure_lxml_html_clean(tmp_path, Symptom(RULE["lxml-html-clean"])) is None  # already there


def test_asyncio_loop_helper_replaces_every_call(tmp_path):
    src = "import asyncio\nfrom x import y\n\ndef a():\n    return asyncio.get_event_loop()\n\ndef b(loop=None):\n    return loop or asyncio.get_event_loop()\n"
    (tmp_path / "lib.py").write_text(src)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_lib.py").write_text("import asyncio\nasyncio.get_event_loop()\n")
    fix = grimoire.cure_asyncio_loop(tmp_path, Symptom(RULE["no-current-event-loop"]))
    assert [e.path for e in fix.edits] == ["lib.py"]  # tests are left alone
    apply_fix(tmp_path, fix)
    new = (tmp_path / "lib.py").read_text()
    assert "return asyncio.get_event_loop()" not in new and "or asyncio.get_event_loop()" not in new
    assert "return _get_event_loop()" in new and "loop or _get_event_loop()" in new
    ns = {"__name__": "lib"}
    exec(compile(new.replace("from x import y\n", ""), "lib.py", "exec"), ns)
    loop = ns["a"]()
    assert not loop.is_closed() and ns["a"]() is loop
    loop.close()


def test_event_loop_fixture_becomes_async(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(textwrap.dedent('''\
        import pytest

        @pytest.fixture
        def session(event_loop):
            return 1
        '''))
    fix = grimoire.cure_event_loop_fixture(tmp_path, Symptom(RULE["event-loop-fixture"]))
    apply_fix(tmp_path, fix)
    text = (tmp_path / "tests" / "test_a.py").read_text()
    assert "import pytest_asyncio\n" in text
    assert "@pytest_asyncio.fixture\nasync def session():\n" in text


def test_history_assertion_restores_only_what_history_proves(gitrepo):
    a = gitrepo.commit({"tests/test_a.py": "def test_c():\n    assert len(x) == 191\n"}, "containing test", author="Kenneth")
    b = gitrepo.commit({"tests/test_a.py": "def test_c():\n    assert len(x) == 192\n"}, "Fix tests", author="Ordanis")
    s = Symptom(RULE["assertion-drift"], ["tests.test_a::test_c"], "assert 191 == 192")
    [fix] = grimoire.cure_history_assertion(gitrepo, s)
    assert fix.citations == [a[:7], b[:7]] and fix.source == "history"
    assert "Kenneth" in fix.why and "Ordanis" in fix.why
    apply_fix(gitrepo, fix)
    assert "== 191" in (gitrepo / "tests" / "test_a.py").read_text()
    # an observed value the history never asserted is not "restored"
    s2 = Symptom(RULE["assertion-drift"], ["tests.test_a::test_c"], "assert 7 == 191")
    assert grimoire.cure_history_assertion(gitrepo, s2) == []


def test_prescribe_skips_unknown_rules(tmp_path):
    from revenant.diagnose import Rule
    assert grimoire.prescribe(tmp_path, [Symptom(Rule("x", "x", "x", "x"))]) == []
