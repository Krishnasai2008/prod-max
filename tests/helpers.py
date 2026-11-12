import io
import os
import subprocess
import tempfile
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from pm.calibrate import Posterior
from pm.cli import main
from pm.tasks import Task

TODAY = date(2026, 11, 9)
EXACT = {"*": Posterior(0.0, 1e6, 1e6, 1e-6, 0)}  # ratio ≈ 1.0


def task(id, est, due_days, logged=0, kind="task"):
    due = None if due_days is None else TODAY + timedelta(days=due_days)
    return Task(id, f"t{id}", None, kind, est, due, "deep", None, None, logged, False)


def git(cwd, *args) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t",
         "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True,
    ).stdout


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    (path / "a.c").write_text("for (i = 0; i <= n; i++)\n")
    git(path, "add", "a.c")
    git(path, "commit", "-q", "-m", "init")
    return path


class CliCase(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.patcher = mock.patch.dict(os.environ, {"PM_DB": f"{self.d.name}/pm.db",
                                                    "PM_NOW": "2026-11-09T10:00:00"})
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.d.cleanup()

    def pm(self, *args, now=None, stdin=None):
        if now:
            os.environ["PM_NOW"] = now
        out, err = io.StringIO(), io.StringIO()
        stdin_ctx = mock.patch("sys.stdin", io.StringIO(stdin)) if stdin is not None else nullcontext()
        with redirect_stdout(out), redirect_stderr(err), stdin_ctx:
            code = main(list(args))
        return code, out.getvalue() + err.getvalue()
