import pytest

from revenant.config import Patient, parse_slug


@pytest.mark.parametrize("given", ["psf/requests-html", "https://github.com/psf/requests-html",
                                   "https://github.com/psf/requests-html/", "git@github.com:psf/requests-html.git",
                                   "github.com/psf/requests-html.git"])
def test_parse_slug_accepts_common_forms(given):
    assert parse_slug(given) == "psf/requests-html"


@pytest.mark.parametrize("bad", ["requests-html", "a/b/c", "psf/req uests", ""])
def test_parse_slug_rejects_garbage(bad):
    with pytest.raises(ValueError):
        parse_slug(bad)


def test_patient_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("REVENANT_HOME", str(tmp_path))
    p = Patient("psf/requests-html").ensure()
    assert p.root == tmp_path / "psf__requests-html"
    assert p.db.name == "ghost.db" and p.cache.is_dir() and p.reports.is_dir()
