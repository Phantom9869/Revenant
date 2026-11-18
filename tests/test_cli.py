"""The command line's error paths: plain messages, not tracebacks, and no stray folders."""
import pytest

from revenant import cli


@pytest.fixture(autouse=True)
def quiet(monkeypatch, tmp_path):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("BACKBOARD_API_KEY", raising=False)
    monkeypatch.setenv("REVENANT_HOME", str(tmp_path / "home"))


def test_bad_slug_is_a_message_not_a_traceback():
    with pytest.raises(SystemExit) as e:
        cli.main(["ask", "not a repo!", "hi"])
    assert "not a GitHub repo slug" in str(e.value.code) and "owner/name" in str(e.value.code)


def test_ask_without_memory_says_how_to_summon_and_creates_nothing(tmp_path):
    with pytest.raises(SystemExit) as e:
        cli.main(["ask", "psf/requests-html", "hi"])
    assert "revenant summon psf/requests-html" in str(e.value.code)
    assert not (tmp_path / "home").exists()


def test_missing_backboard_key_is_a_message(tmp_path):
    from revenant.config import Patient
    from revenant.memory.store import Memory
    p = Patient("psf/requests-html").ensure()
    Memory(p.db).close()
    with pytest.raises(SystemExit) as e:
        cli.main(["ask", "psf/requests-html", "hi", "--model", "backboard:openrouter/some-model"])
    assert "BACKBOARD_API_KEY is not set" in str(e.value.code)


def _boom(exc):
    def run(args):
        raise exc
    return run


def test_summon_unknown_repo_is_a_message(monkeypatch):
    import subprocess
    monkeypatch.setattr(cli, "_summon", _boom(subprocess.CalledProcessError(128, ["git", "clone", "--quiet", "u", "d"])))
    with pytest.raises(SystemExit) as e:
        cli.main(["summon", "psf/no-such-repo"])
    msg = str(e.value.code)
    assert "`git clone` failed" in msg and "psf/no-such-repo" in msg and "Traceback" not in msg


def test_summon_github_http_error_is_a_message(monkeypatch):
    import urllib.error
    err = urllib.error.HTTPError("https://api.github.com/repos/o/r", 404, "Not Found", {}, None)
    monkeypatch.setattr(cli, "_summon", _boom(err))
    with pytest.raises(SystemExit) as e:
        cli.main(["summon", "o/r"])
    assert "HTTP 404" in str(e.value.code) and "GITHUB_TOKEN" not in str(e.value.code)
    err = urllib.error.HTTPError("https://api.github.com/repos/o/r", 401, "Unauthorized", {}, None)
    monkeypatch.setattr(cli, "_summon", _boom(err))
    with pytest.raises(SystemExit) as e:
        cli.main(["summon", "o/r"])
    assert "GITHUB_TOKEN" in str(e.value.code)


def test_summon_offline_is_a_message(monkeypatch):
    import urllib.error
    monkeypatch.setattr(cli, "_summon", _boom(urllib.error.URLError("[Errno -2] Name or service not known")))
    with pytest.raises(SystemExit) as e:
        cli.main(["summon", "o/r"])
    assert "could not reach" in str(e.value.code) and "--no-github" in str(e.value.code)
