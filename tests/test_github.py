import io
import json
import urllib.error

import pytest

from revenant.harvest.github import GitHubClient, RateLimited, _next_link, harvest


class FakeResp(io.BytesIO):
    def __init__(self, body, headers):
        super().__init__(json.dumps(body).encode())
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeAPI:
    def __init__(self, pages, remaining=50):
        self.pages, self.calls, self.remaining = pages, [], remaining

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.calls.append(url)
        if self.remaining == 0:
            raise urllib.error.HTTPError(url, 403, "rate limited",
                                         {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "2000000000"}, None)
        self.remaining -= 1
        body, nxt = self.pages[url]
        headers = {"X-RateLimit-Remaining": str(self.remaining)}
        if nxt:
            headers["Link"] = f'<{nxt}>; rel="next", <{nxt}>; rel="last"'
        return FakeResp(body, headers)


API = "https://api.github.com"


def test_next_link_parsing():
    assert _next_link('<https://x/2>; rel="next", <https://x/9>; rel="last"') == "https://x/2"
    assert _next_link('<https://x/1>; rel="prev"') is None
    assert _next_link(None) is None


def test_paging_and_cache(tmp_path):
    api = FakeAPI({f"{API}/items": ([1, 2], f"{API}/items?page=2"), f"{API}/items?page=2": ([3], None)})
    c = GitHubClient(tmp_path, token="", opener=api)
    assert list(c.paged("/items")) == [1, 2, 3]
    assert c.requests_made == 2 and c.remaining == 48
    c2 = GitHubClient(tmp_path, token="", opener=api)   # new client, same cache
    assert list(c2.paged("/items")) == [1, 2, 3]
    assert c2.requests_made == 0 and c2.cache_hits == 2 and len(api.calls) == 2


def test_rate_limit_raises_and_harvest_keeps_partial(tmp_path):
    slug = "o/r"
    base = f"{API}/repos/{slug}"
    pages = {base: ({"full_name": slug}, None),
             f"{base}/issues?state=all&per_page=100&sort=created&direction=asc": ([{"number": 1}], None)}
    api = FakeAPI(pages, remaining=2)
    c = GitHubClient(tmp_path / "cache", token="", opener=api)
    summary = harvest(c, slug, tmp_path / "raw", log=lambda *a: None)
    assert summary["issues"] == 1
    assert set(summary["partial"]) == {"issue_comments", "review_comments", "pulls"}
    assert json.loads((tmp_path / "raw" / "repo.json").read_text()) == {"full_name": slug}
    with pytest.raises(RateLimited):
        c.get("/anything-new")
