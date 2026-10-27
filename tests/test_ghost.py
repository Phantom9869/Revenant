from revenant.ghost import SILENT, Ghost, check_citations, evidence_block
from revenant.memory.retrieve import Hit
from revenant.memory.store import Doc
from revenant.models import ChatResult

ALLOWED = {"#569", "#576", "c7d07a0", "README.rst"}


def test_valid_citations_are_kept():
    text, valid, stripped = check_citations("lxml split [#569]. Docs broke [#576, README.rst].", ALLOWED)
    assert valid == ["#569", "#576", "README.rst"] and stripped == []
    assert "[#576, README.rst]" in text


def test_invented_citations_are_stripped():
    text, valid, stripped = check_citations("It died in 2019 [#9999]. Fixed in [deadbee].", ALLOWED)
    assert valid == [] and stripped == ["#9999", "deadbee"]
    assert "[" not in text and text.endswith("Fixed in.")


def test_sha_prefixes_escapes_and_bare_numbers_resolve():
    _, valid, _ = check_citations("a [c7d07a0f1] b [\\#569] c [576] d [commit c7d07a0]", ALLOWED)
    assert valid == ["c7d07a0", "#569", "#576"]


def test_sha_that_only_shares_a_prefix_is_rejected():
    _, valid, stripped = check_citations("x [c7d07a1]", ALLOWED)
    assert valid == [] and stripped == ["c7d07a1"]


def doc(ref, kind="issue", text="lxml.html.clean is now a separate project"):
    return Doc(f"{kind}:{ref}", kind, ref, f"https://example/{ref}", "LXML 5.2.0 breaks import", "ana", "2024-04-01", text)


class FakeRetriever:
    def __init__(self, hits, semantic=True):
        self.hits, self.last_semantic = hits, semantic

    def search(self, q, k=8):
        return self.hits


class FakeModel:
    name = "fake"

    def __init__(self, reply):
        self.reply, self.seen = reply, None

    def chat(self, messages, **opts):
        self.seen = messages
        return ChatResult(self.reply, "fake", 10, 5, 0.1)


def test_ghost_answers_with_checked_citations():
    m = FakeModel("lxml.html.clean became a separate project [#569]. I made up [#1].")
    g = Ghost("demo", FakeRetriever([Hit(doc("#569"), 0.03, 0.7)]), m)
    a = g.ask("why can't I import you?")
    assert not a.refused and a.cited == ["#569"] and a.stripped == ["#1"]
    assert a.sources() == [("#569", "https://example/#569")]
    assert "[#569] (issue, 2024-04-01 by ana)" in m.seen[1]["content"]


def test_ghost_refuses_without_relevant_evidence_and_never_calls_the_model():
    m = FakeModel("should not be called")
    a = Ghost("demo", FakeRetriever([Hit(doc("#1"), 0.01, 0.1)]), m).ask("sourdough recipe?")
    assert a.refused and a.text == SILENT and m.seen is None


def test_ghost_refuses_uncited_answers():
    a = Ghost("demo", FakeRetriever([Hit(doc("#569"), 0.03, 0.8)]), FakeModel("Trust me, it was cosmic rays.")).ask("why?")
    assert a.refused and a.text == SILENT and a.reason == "answer carried no verifiable citation"


def test_keyword_only_mode_needs_two_hits():
    hits = [Hit(doc("#569"), 0.03, 0.0)]
    a = Ghost("demo", FakeRetriever(hits, semantic=False), FakeModel("x [#569]")).ask("q")
    assert a.refused
    a = Ghost("demo", FakeRetriever(hits + [Hit(doc("#576"), 0.02, 0.0)], semantic=False), FakeModel("x [#569]")).ask("q")
    assert not a.refused


def test_evidence_block_truncates_long_docs():
    block = evidence_block([Hit(doc("#5", text="x" * 5000), 0, 0)], max_chars=100)
    assert block.count("x") == 100
