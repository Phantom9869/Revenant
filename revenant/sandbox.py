"""Run a patient's test suite in a throwaway environment.

Install happens with network (it has to). The test run itself happens inside a
bubblewrap sandbox with no network namespace, a read-only view of the host, a
private /tmp, and write access only to the patient's working tree and a scratch dir.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Pipfile/requirements entries that are tooling, not needed to run tests.
NOT_FOR_TESTS = {"twine", "sphinx", "mypy", "white", "black", "flake8", "pylint", "tox",
                 "coverage", "coveralls", "codecov", "wheel", "setuptools", "docutils",
                 "readme-renderer", "bumpversion", "sphinx-rtd-theme", "ipython", "pre-commit"}


# Directories tools insist on writing to under $HOME. Inside the sandbox each existing
# one gets a private, empty tmpfs so the host's home stays read-only.
SCRATCH_DIRS = ["~/.local/share/pyppeteer/.dev_profile"] + [
    d for d in os.environ.get("REVENANT_SANDBOX_TMPFS", "").split(":") if d]


@dataclass
class TestPlan:
    __test__ = False  # not a pytest test class
    deps: list[str]
    args: list[str]          # pytest args, e.g. ["-m", "not internet"]
    source: str              # where we learned it


@dataclass
class RunResult:
    returncode: int
    seconds: float
    junit: Path
    stdout: str
    command: list[str] = field(default_factory=list)
    sandboxed: bool = True


def _req_name(spec: str) -> str:
    for sep in "<>=!~[; ":
        spec = spec.split(sep)[0]
    return spec.strip().lower()


def detect_test_plan(repo: Path) -> TestPlan:
    repo = Path(repo)
    deps, args, source = ["pytest"], [], "default"
    pipfile = repo / "Pipfile"
    if pipfile.exists():
        data = tomllib.loads(pipfile.read_text())
        for name, spec in (data.get("dev-packages") or {}).items():
            if _req_name(name) in NOT_FOR_TESTS or isinstance(spec, dict) and ("path" in spec or "git" in spec):
                continue
            if _req_name(name) not in {_req_name(d) for d in deps}:
                deps.append(name if spec in ("*", "") or not isinstance(spec, str) else name + spec)
        script = (data.get("scripts") or {}).get("tests", "")
        if "pytest" in script:
            import shlex
            parts = shlex.split(script)
            args = parts[parts.index("pytest") + 1:] if "pytest" in parts else []
            args = [a for a in args if a not in ("-v",)]
        source = "Pipfile"
    for name in ("requirements-dev.txt", "dev-requirements.txt", "test-requirements.txt", "requirements-test.txt"):
        f = repo / name
        if f.exists():
            for line in f.read_text().splitlines():
                line = line.split("#")[0].strip()
                if line and not line.startswith("-") and _req_name(line) not in NOT_FOR_TESTS:
                    if _req_name(line) not in {_req_name(d) for d in deps}:
                        deps.append(line)
            source = name if source == "default" else source + "+" + name
    return TestPlan(deps=deps, args=args, source=source)


def bwrap_available() -> bool:
    if not shutil.which("bwrap"):
        return False
    r = subprocess.run(["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--unshare-net", "true"],
                       capture_output=True)
    return r.returncode == 0


class Sandbox:
    def __init__(self, repo: Path, workdir: Path, python: str = "3.13"):
        self.repo = Path(repo).resolve()
        self.workdir = Path(workdir).resolve()
        self.venv = self.workdir / "venv"
        self.python = python
        self.workdir.mkdir(parents=True, exist_ok=True)

    @property
    def py(self) -> Path:
        return self.venv / "bin" / "python"

    def install(self, plan: TestPlan, extra: list[str] | None = None, fresh: bool = False) -> str:
        """Create the venv and install the project + test deps (network allowed)."""
        if fresh and self.venv.exists():
            shutil.rmtree(self.venv)
        log = []
        if not self.py.exists():
            r = subprocess.run(["uv", "venv", "-q", "--python", self.python, str(self.venv)],
                               capture_output=True, text=True)
            log.append(r.stdout + r.stderr)
            if r.returncode:
                raise RuntimeError("venv creation failed: " + r.stderr)
        env = dict(os.environ, VIRTUAL_ENV=str(self.venv))
        cmd = ["uv", "pip", "install", "-q", "--python", str(self.py), "-e", str(self.repo), *plan.deps, *(extra or [])]
        r = subprocess.run(cmd, capture_output=True, text=True, env=env)
        log.append(r.stdout + r.stderr)
        if r.returncode:
            raise RuntimeError("install failed: " + r.stderr[-2000:])
        return "\n".join(l for l in log if l.strip())

    def run_tests(self, plan: TestPlan, timeout: int = 900, network: bool = False) -> RunResult:
        out = self.workdir / "out"
        out.mkdir(exist_ok=True)
        junit = out / "junit.xml"
        junit.unlink(missing_ok=True)
        pytest = [str(self.py), "-m", "pytest", "-p", "no:cacheprovider", "-rA", "-q",
                  f"--junitxml={junit}", *plan.args]
        home = os.environ.get("HOME", "/root")
        if bwrap_available():
            cmd = ["bwrap", "--ro-bind", "/", "/", "--bind", str(self.repo), str(self.repo),
                   "--bind", str(out), str(out), "--dev", "/dev", "--proc", "/proc",
                   "--tmpfs", "/tmp", "--die-with-parent", "--chdir", str(self.repo)]
            for d in SCRATCH_DIRS:
                d = os.path.expanduser(d)
                if os.path.isdir(d):
                    cmd += ["--tmpfs", d]
            if not network:
                cmd.append("--unshare-net")
            cmd += ["--", *pytest]
            sandboxed = True
        else:  # degrade loudly rather than silently
            cmd, sandboxed = pytest, False
        env = {"PATH": f"{self.venv}/bin:/usr/bin:/bin", "HOME": home, "LANG": "C.UTF-8",
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"}
        t = time.time()
        try:
            r = subprocess.run(cmd, cwd=self.repo, capture_output=True, text=True, timeout=timeout, env=env)
            rc, text = r.returncode, r.stdout + r.stderr
        except subprocess.TimeoutExpired as e:
            rc, text = -9, (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            text += f"\n[revenant] test run timed out after {timeout}s"
        return RunResult(rc, time.time() - t, junit, text, cmd, sandboxed)
