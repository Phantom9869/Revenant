from revenant.aftercare import ci_workflow, dead_badge_edit, python_metadata_edits, sphinx_release_edit
from revenant.sandbox import TestPlan

SETUP = """VERSION = '0.10.0'
setup(
    python_requires='>=3.6.0',
    classifiers=[
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: Implementation :: CPython',
    ],
)
"""


def test_metadata_matches_verified_versions(tmp_path):
    (tmp_path / "setup.py").write_text(SETUP)
    text = SETUP
    for _, old, new in python_metadata_edits(tmp_path, ["3.9", "3.13"]):
        text = text.replace(old, new)
    assert "python_requires='>=3.9'" in text
    assert "'Programming Language :: Python :: 3.9',\n        'Programming Language :: Python :: 3.13',\n" in text
    assert "3.6" not in text and "Implementation :: CPython" in text
    assert python_metadata_edits(tmp_path, []) == []


def test_ci_workflow_uses_project_test_command():
    yml = ci_workflow(TestPlan(["pytest", "pytest-asyncio"], ["-m", "not internet"], "Pipfile"), ["3.9", "3.13"], True)
    assert 'python-version: ["3.9", "3.13"]' in yml
    assert "pip install -e . pytest pytest-asyncio" in yml
    assert "pyppeteer-install" in yml
    assert 'python -m pytest -m "not internet"' in yml


def test_sphinx_release_and_dead_badge(tmp_path):
    (tmp_path / "setup.py").write_text(SETUP)
    (tmp_path / "docs" / "source").mkdir(parents=True)
    (tmp_path / "docs" / "source" / "conf.py").write_text("version = ''\nrelease = 'v0.3.4'\n")
    assert sphinx_release_edit(tmp_path)[2] == "release = 'v0.10.0'"
    (tmp_path / "README.rst").write_text("Title\n\n.. image:: https://travis-ci.com/o/r.svg?branch=master\n    :target: https://travis-ci.com/o/r\n\nBody\n")
    path, old, new = dead_badge_edit(tmp_path)
    assert path == "README.rst" and "travis" in old and new == ""
