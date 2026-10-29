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
