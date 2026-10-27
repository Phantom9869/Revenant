import io
import json

from revenant.integrations import tracing, wayback
from revenant.models import BackboardClient, OllamaClient, get_chat_model
from revenant.web.app import md_to_html


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_wayback_closest_parses_availability_api():
    body = {"archived_snapshots": {"closest": {"available": True, "timestamp": "20181103123045",
                                               "url": "http://web.archive.org/web/20181103123045/http://x.org/"}}}
    snap = wayback.closest("x.org", opener=lambda req, timeout: Resp(json.dumps(body).encode()))
    assert snap.date == "2018-11-03"
    assert snap.raw_url == "https://web.archive.org/web/20181103123045id_/x.org"
    assert wayback.closest("y.org", opener=lambda req, timeout: Resp(b'{"archived_snapshots": {}}')) is None


def test_html_to_text_drops_scripts_and_nav():
    html = "<html><head><title>t</title></head><body><nav>menu</nav><h1>Hi</h1><script>evil()</script><p>Body  text</p></body></html>"
    assert wayback.html_to_text(html) == "Hi\nBody text"


def test_archive_docs_are_citable():
    class F:
        name = "fake"

        def fetch(self, url):
            return "<p>Python 2 will retire soon.</p>"

    snap = wayback.Snapshot("https://html.python-requests.org/", "20181103123045", "http://archive/x")
    [d] = wayback.archive_docs(snap, F())
    assert d.ref == "archive:html.python-requests.org@2018-11-03" and d.kind == "archive"


def test_tracing_is_a_noop_without_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert tracing.init() is False and not tracing.enabled()
    with tracing.span("gen_ai.chat", "x") as s:
        assert s is None


def test_model_specs(monkeypatch):
    assert isinstance(get_chat_model("gemma4:e4b"), OllamaClient)
    monkeypatch.setenv("BACKBOARD_API_KEY", "k")
    m = get_chat_model("backboard:google/gemma-3-27b-it")
    assert isinstance(m, BackboardClient)


def test_md_to_html_handles_our_reports():
    out = md_to_html("# T\n\n| a | b |\n|---|---|\n| 1 | `x` |\n\n- **bold** [l](https://e.org)\n\n```\n<raw>\n```")
    assert "<h1>T</h1>" in out and "<td><code>x</code></td>" in out
    assert '<a href="https://e.org">l</a>' in out and "&lt;raw&gt;" in out


def test_cached_fetcher_fetches_each_url_once(tmp_path):
    calls = []

    class F:
        name = "fake"

        def fetch(self, url):
            calls.append(url)
            return "<p>page</p>"

    c = wayback.CachedFetcher(F(), tmp_path / "archive")
    assert c.fetch("https://a/x") == c.fetch("https://a/x") == "<p>page</p>"
    assert calls == ["https://a/x"] and (c.hits, c.misses) == (1, 1)
    assert wayback.CachedFetcher(F(), tmp_path / "archive").fetch("https://a/x") == "<p>page</p>" and len(calls) == 1


def test_browserbase_fetcher_reports_api_errors(monkeypatch):
    import io
    import urllib.error
    import pytest

    bb = wayback.BrowserbaseFetcher(api_key="k")

    def boom(req, timeout):
        assert req.get_header("X-bb-api-key") == "k"
        raise urllib.error.HTTPError(req.full_url, 402, "x", {}, io.BytesIO(b'{"message": "quota exceeded"}'))

    monkeypatch.setattr(wayback.BrowserbaseFetcher, "__call__", lambda self, req, timeout: boom(req, timeout))
    with pytest.raises(RuntimeError, match="HTTP 402 quota exceeded"):
        bb.fetch("https://web.archive.org/web/2020id_/x")


def test_snapshot_parse_takes_a_wayback_url():
    s = wayback.Snapshot.parse("https://web.archive.org/web/20190915235734/http://html.python-requests.org:80/")
    assert (s.timestamp, s.url, s.date) == ("20190915235734", "http://html.python-requests.org:80/", "2019-09-15")
    assert s.raw_url == "https://web.archive.org/web/20190915235734id_/http://html.python-requests.org:80/"
    assert wayback.Snapshot.parse("https://example.org/") is None


def test_ghost_traces_follow_gen_ai_conventions(monkeypatch):
    import pytest
    sentry_sdk = pytest.importorskip("sentry_sdk")
    from sentry_sdk.transport import Transport
    from revenant.ghost import Ghost
    from revenant.memory.retrieve import Hit
    from revenant.memory.store import Doc
    from revenant.models import ChatResult

    sent = []

    class Capture(Transport):
        def capture_envelope(self, envelope):
            sent.extend(item.payload.json for item in envelope.items if item.payload.json)

    sentry_sdk.init(dsn="https://k@o0.ingest.sentry.io/0", traces_sample_rate=1.0, transport=Capture,
                    stream_gen_ai_spans=False)
    monkeypatch.setattr(tracing, "_sdk", sentry_sdk)
    monkeypatch.delenv("REVENANT_TRACE_CONTENT", raising=False)

    doc = Doc(id="i1", kind="issue", ref="#1", url="u", title="t", author="a", date="2020", text="lxml broke")

    class R:
        last_semantic = True

        def search(self, q, k=8):
            return [Hit(doc, 1.0, 0.9), Hit(doc, 0.9, 0.8)]

    class M:
        name = "fake-model"

        def chat(self, messages, **o):
            return ChatResult(text="lxml broke it [#1].", model="fake-model", prompt_tokens=10,
                              completion_tokens=5, seconds=0.1)

    with tracing.transaction("t"):
        Ghost("p", R(), tracing.TracedModel(M(), "ghost")).ask("why?")
    sentry_sdk.flush()
    monkeypatch.setattr(tracing, "_sdk", None)
    spans = [s for e in sent for s in e.get("spans", [])]
    ops = {s["op"]: s for s in spans}
    assert {"gen_ai.invoke_agent", "gen_ai.memory.client", "gen_ai.chat"} <= set(ops)
    chat = ops["gen_ai.chat"]["data"]
    assert chat["gen_ai.operation.name"] == "chat" and chat["gen_ai.usage.total_tokens"] == 15
    assert ops["gen_ai.chat"]["parent_span_id"] == ops["gen_ai.invoke_agent"]["span_id"]
    assert "gen_ai.input.messages" not in chat  # content is opt-in
