from revenant.diagnose import classify, locate, parse_junit, tally

JUNIT = """<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">
<testcase classname="tests.test_x" name="test_ok" time="0.1"/>
<testcase classname="tests.test_x" name="test_count"><failure message="assert 191 == 192">tests/test_x.py:68: in test_count
    assert len(python) == 192
E   assert 191 == 192</failure></testcase>
<testcase classname="tests.test_x" name="test_loop"><failure message="RuntimeError: There is no current event loop in thread 'MainThread'.">tests/test_x.py:250: in test_loop
    r.html.render()
requests_html.py:797: in browser
    self.loop = asyncio.get_event_loop()
E   RuntimeError: There is no current event loop in thread 'MainThread'.</failure></testcase>
<testcase classname="tests.test_x" name="test_async"><error message="failed on setup with &quot;file x, line 38&quot;">E       fixture 'event_loop' not found</error></testcase>
<testcase classname="tests.test_x" name="test_weird"><failure message="ZeroDivisionError">boom</failure></testcase>
<testcase classname="tests.test_x" name="test_skip"><skipped message="no network"/></testcase>
</testsuite></testsuites>"""


def test_parse_and_tally(tmp_path):
    f = tmp_path / "j.xml"
    f.write_text(JUNIT)
    out = parse_junit(f)
    assert tally(out) == {"passed": 1, "failed": 3, "error": 1, "skipped": 1}
    assert out[0].test == "tests.test_x::test_ok"


def test_classify_names_each_cause(tmp_path):
    f = tmp_path / "j.xml"
    f.write_text(JUNIT)
    symptoms, unexplained = classify(parse_junit(f))
    by = {s.rule.id: s for s in symptoms}
    assert set(by) == {"assertion-drift", "no-current-event-loop", "event-loop-fixture"}
    assert by["no-current-event-loop"].location == "requests_html.py:797"
    assert by["assertion-drift"].evidence == "assert 191 == 192"
    assert [o.test for o in unexplained] == ["tests.test_x::test_weird"]


def test_collection_failure_without_testcases():
    out = "E   ImportError: lxml.html.clean module is now a separate project lxml_html_clean.\nrequests_html.py:15: in <module>"
    symptoms, _ = classify([], out)
    assert symptoms[0].rule.id == "lxml-html-clean" and symptoms[0].tests == ["<collection>"]


def test_locate_prefers_project_frames():
    tb = ("tests/test_a.py:10: in test_a\n.venv/lib/python3.13/site-packages/x.py:5: in f\n"
          "pkg/core.py:42: in g\n/usr/lib/python3.13/asyncio/events.py:1: in h\n")
    assert locate(tb) == "pkg/core.py:42"
    assert locate("tests/test_a.py:10: in test_a\n") == "tests/test_a.py:10"
