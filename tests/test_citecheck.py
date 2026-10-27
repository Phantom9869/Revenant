from revenant.citecheck import apply_support, check_support, hard_details, split_sentences
from revenant.ghost import Ghost, _normalise
from revenant.memory.retrieve import Hit
from revenant.memory.store import Doc
from revenant.models import ChatResult

SRC = {
    "#569": "lxml.html.clean module is now a separate project lxml_html_clean. Add lxml_html_clean "
            "as an explicit dependency in setup.py until requests-html moves to bleach or nh3.",
    "tags": "Latest release tag: v0.10.0, tagged 2019-02-17 at commit c561e9b.",
}


def verdicts(text):
    return [(c.verdict, c.supported_by, c.unsupported_refs, c.missing) for c in check_support(text, SRC, _normalise)]


def test_sentences_keep_trailing_citations():
    s = split_sentences("It broke. [#569]\n\nIt was fixed in setup.py [#569]. I remember.")
    assert s == ["It broke. [#569]", "It was fixed in setup.py [#569].", "I remember."]


def test_hard_details_are_extracted():
    d = hard_details('Release v0.10.0 on 2019-02-17 broke `HTMLSession` in lxml.html.clean, see #12 and "Some quoted error"')
    for x in ("0.10.0", "2019-02-17", "HTMLSession", "lxml.html.clean", "#12", "Some quoted error"):
        assert x in d


def test_supported_sentence_passes():
    [(v, ok, bad, missing)] = verdicts("The lxml.html.clean module became a separate project, lxml_html_clean [#569].")
    assert v == "supported" and ok == ["#569"] and not bad and not missing


def test_citation_pointing_at_unrelated_record_is_removed():
    text = "The lxml.html.clean module became a separate project, lxml_html_clean [#569, tags]."
    [(v, ok, bad, _)] = verdicts(text)
    assert v == "supported" and ok == ["#569"] and bad == ["tags"]
    new, removed, withheld = apply_support(text, check_support(text, SRC, _normalise), _normalise)
    assert new == "The lxml.html.clean module became a separate project, lxml_html_clean [#569]."
    assert removed == ["tags"] and not withheld


def test_invented_detail_is_withheld():
    text = "My last release was v0.11.0, tagged 2019-02-17 [tags]. lxml.html.clean became lxml_html_clean [#569]."
    claims = check_support(text, SRC, _normalise)
    assert claims[0].verdict == "unsupported" and claims[0].missing == ["0.11.0"]
    new, removed, withheld = apply_support(text, claims, _normalise)
    assert new == "lxml.html.clean became lxml_html_clean [#569]."
    assert [c.sentence for c in withheld] == ["My last release was v0.11.0, tagged 2019-02-17."]


def test_version_prefix_matching_is_strict():
    assert verdicts("The last release tag was 0.10 [tags].")[0][0] == "supported"   # 0.10 ~ 0.10.0
    assert verdicts("The last release tag was 10.0 [tags].")[0][0] == "unsupported"


def test_off_topic_claim_is_withheld():
    assert verdicts("Guido archived the project in 2023 for security reasons [#569].")[0][0] == "unsupported"


def test_uncited_flourish_is_kept():
    text = "I remember it well. lxml.html.clean became lxml_html_clean [#569]."
    claims = check_support(text, SRC, _normalise)
    assert [c.verdict for c in claims] == ["uncited", "supported"]
    assert apply_support(text, claims, _normalise)[0] == text


class FakeRetriever:
    last_semantic = False

    def __init__(self, hits):
        self.hits = hits

    def search(self, q, k=8):
        return self.hits


class FakeModel:
    name = "fake"

    def __init__(self, text):
        self.text = text

    def chat(self, messages, **o):
        return ChatResult(self.text, "fake", 10, 5, 0.1)


def _hits():
    docs = [Doc("1", "issue", "#569", "u1", "lxml", "a", "2024-04-01", SRC["#569"]),
            Doc("2", "record", "tags", "u2", "tags", "", "", SRC["tags"])]
    return [Hit(d, 1.0, 0.0) for d in docs]


def test_ghost_refuses_when_no_citation_supports_its_sentence():
    g = Ghost("x", FakeRetriever(_hits()), FakeModel("I was archived by Guido in 2023 [#569]."))
    a = g.ask("why?")
    assert a.refused and a.reason == "no citation supported its sentence" and a.withheld


def test_ghost_strips_unsupported_and_keeps_raw():
    raw = "lxml.html.clean became lxml_html_clean [#569, tags]. My last release was v9.9.9 [tags]."
    a = Ghost("x", FakeRetriever(_hits()), FakeModel(raw)).ask("why?")
    assert not a.refused and a.text == "lxml.html.clean became lxml_html_clean [#569]."
    assert a.cited == ["#569"] and a.raw == raw and set(a.unsupported) == {"tags"}


def test_ghost_without_verification_is_unchanged():
    raw = "lxml.html.clean became lxml_html_clean [#569, tags]."
    a = Ghost("x", FakeRetriever(_hits()), FakeModel(raw), verify=False).ask("why?")
    assert a.text == raw and a.claims == []


def test_project_name_needs_no_source_and_camelcase_counts_as_detail():
    text = "Importing old_patient raises ImportError from lxml.html.clean [#569]."
    assert check_support(text, SRC, _normalise)[0].missing == ["old_patient", "ImportError"]
    claims = check_support(text, SRC, _normalise, known=("old-patient", "old_patient"))
    assert claims[0].missing == ["ImportError"]


def test_verified_detail_plus_a_third_of_the_words_is_enough():
    # regression: a correct install instruction was withheld at 1/3 overlap with a 0.34 cut-off
    src = {"archive:x": "Installing Requests-HTML is simple:\n$ pipenv install requests-html\nOnly Python 3.6 is supported."}
    [c] = check_support("To install me, one uses the command `$ pipenv install requests-html` [archive:x].", src, _normalise)
    assert c.verdict == "supported" and round(c.overlap, 2) == 0.33
