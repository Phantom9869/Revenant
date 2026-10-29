import json

from revenant.memory import ingest
from revenant.memory.retrieve import Retriever, rrf
from revenant.memory.store import Doc, Memory


def d(i, text, kind="issue", ref=None):
    return Doc(f"{kind}:{i}", kind, ref or f"#{i}", "u", f"title {i}", "a", "2020-01-01", text)


def test_add_is_idempotent_and_keyword_search_ranks(tmp_path):
    m = Memory(tmp_path / "g.db")
    docs = [d(1, "the event loop is closed"), d(2, "lxml clean import error"), d(3, "unrelated docs typo")]
    assert m.add(docs) == 3 and m.add(docs) == 0
    hits = m.keyword("lxml import", 5)
    assert hits[0][0] == "issue:2"
    assert m.count() == {"issue": 3}



def test_memory_can_be_shared_between_threads(tmp_path):
    """The web server caches one ghost per patient and answers each request on a new thread."""
    import threading
    m = Memory(tmp_path / "g.db")
    m.add([d(i, f"lxml import error number {i}") for i in range(20)])
    errors, gate = [], threading.Barrier(8)

    def search():
        gate.wait()   # all threads alive at once, so none can reuse the creating thread's id
        try:
            for _ in range(20):
                assert m.keyword("lxml import", 5) and m.get("issue:3")
        except Exception as e:   # pragma: no cover - the failure being guarded against
            errors.append(e)

    threads = [threading.Thread(target=search) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []

def test_vectors_roundtrip_and_semantic_search(tmp_path):
    m = Memory(tmp_path / "g.db")
    m.add([d(1, "alpha"), d(2, "beta")])

    class Emb:
        name = "toy"

        def embed_query(self, q):
            return [1.0, 0.0] if "alpha" in q else [0.0, 1.0]

    m.put_vectors("toy", [("issue:1", [1.0, 0.0]), ("issue:2", [0.0, 1.0])])
    assert m.missing_vectors("toy") == []
    ids, mat = m.vectors("toy")
    assert ids == ["issue:1", "issue:2"] and mat.shape == (2, 2)
    r = Retriever(m, Emb())
    assert r.semantic("alpha?", 1)[0][0] == "issue:1"
    hits = r.search("beta", k=2)
    assert hits[0].doc.id == "issue:2" and r.last_semantic


def test_rrf_rewards_agreement():
    s = rrf([["a", "b", "c"], ["b", "a"]])
    assert s["a"] == s["b"] > s["c"]


def test_chunks_respect_size_and_keep_text():
    text = "\n\n".join(f"para {i} " + "w" * 300 for i in range(10))
    parts = ingest.chunks(text, 1000)
    assert all(len(p) <= 1000 for p in parts)
    assert "".join(parts).replace("\n", "").count("para") == 10
    assert ingest.chunks("") == []


def test_issue_docs_distinguish_prs_and_comments(tmp_path):
    raw = tmp_path
    (raw / "issues.json").write_text(json.dumps([
        {"number": 1, "title": "Bug", "state": "open", "body": "it broke", "html_url": "u1", "user": {"login": "x"},
         "created_at": "2024-01-01T00:00:00Z", "labels": [{"name": "bug"}]},
        {"number": 2, "title": "Fix", "state": "closed", "body": "", "html_url": "u2", "user": {"login": "y"},
         "created_at": "2024-01-02T00:00:00Z", "labels": [], "pull_request": {}}]))
    (raw / "pulls.json").write_text(json.dumps([{"number": 2, "merged_at": "2024-01-03T00:00:00Z"}]))
    (raw / "issue_comments.json").write_text(json.dumps([
        {"id": 9, "issue_url": "https://api/x/issues/1", "html_url": "c9", "body": "same here", "user": {"login": "z"},
         "created_at": "2024-01-04T00:00:00Z"}]))
    (raw / "review_comments.json").write_text("[]")
    docs = {x.id: x for x in ingest.issue_docs(raw)}
    assert docs["issue:1:0"].text.startswith("Issue #1 [open] Bug (labels: bug)")
    assert docs["pr:2:0"].text.startswith("PR #2 [merged 2024-01-03] Fix")
    assert docs["comment:9:0"].ref == "#1" and "Bug" in docs["comment:9:0"].text
