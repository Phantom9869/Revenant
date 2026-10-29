import subprocess

import pytest

from revenant.sandbox import bwrap_available, detect_test_plan


def test_plan_from_pipfile(tmp_path):
    (tmp_path / "Pipfile").write_text('''
[dev-packages]
twine = "*"
pytest = "*"
requests-file = "*"
pytest-asyncio = "*"
sphinx = "*"
e1839a8 = {path = ".", editable = true}

[scripts]
tests = "pytest -v -m 'not internet'"
''')
    plan = detect_test_plan(tmp_path)
    assert plan.deps == ["pytest", "requests-file", "pytest-asyncio"]
    assert plan.args == ["-m", "not internet"] and plan.source == "Pipfile"


def test_plan_from_requirements(tmp_path):
    (tmp_path / "requirements-dev.txt").write_text("nose>=1.3  # old\n-e .\nflake8\nmock\n")
    plan = detect_test_plan(tmp_path)
    assert plan.deps == ["pytest", "nose>=1.3", "mock"]


@pytest.mark.skipif(not bwrap_available(), reason="bubblewrap not usable here")
def test_sandbox_really_has_no_network():
    r = subprocess.run(["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--unshare-net",
                        "python3", "-c", "import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)"],
                       capture_output=True, text=True)
    assert r.returncode != 0 and "unreachable" in r.stderr.lower()
