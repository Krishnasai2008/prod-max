import io
import os
import shlex
import shutil
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from pm.cli import main
from pm.db import connect
from tests.helpers import CliCase, git, make_repo

CHECK = [sys.executable, "check.py"]


@unittest.skipUnless(shutil.which("git"), "needs git")
class TestBugsCli(CliCase):
    def setUp(self):
        super().setUp()
        self.repo = make_repo(Path(self.d.name) / "repo")
        self.old = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, self.old)
        (self.repo / "check.py").write_text(
            'import sys\nsys.exit(1 if "<=" in open("a.c").read() else 0)\n')
        git(self.repo, "add", "check.py")
        git(self.repo, "commit", "-q", "-m", "check")

    def fail_then_fix(self):
        self.pm("run", "--", *CHECK, now="2026-11-09T10:00:00")
        Path("a.c").write_text("for (i = 0; i < n; i++)\n")
        return self.pm("run", "--", *CHECK, now="2026-11-09T10:25:00")

    def test_fail_then_fix_end_to_end(self):
        code, out = self.pm("run", "--", *CHECK, now="2026-11-09T10:00:00")
        self.assertEqual((code, out), (1, ""))
        Path("a.c").write_text("for (i = 0; i < n; i++)\n")
        code, out = self.pm("run", "--", *CHECK, now="2026-11-09T10:25:00")
        self.assertEqual(code, 0)
        self.assertEqual(out, "pm: fixed bug #1 after 1 fail, 25m lost [off-by-one]\n")
        code, out = self.pm("bug", "1")
        self.assertIn("+for (i = 0; i < n; i++)", out)

    def test_pm_line_goes_to_stderr(self):
        self.pm("run", "--", *CHECK, now="2026-11-09T10:00:00")
        Path("a.c").write_text("for (i = 0; i < n; i++)\n")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"PM_NOW": "2026-11-09T10:25:00"}), \
                redirect_stdout(out), redirect_stderr(err):
            code = main(["run", "--", *CHECK])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("pm: fixed bug #1", err.getvalue())

    def test_exit_code_passes_through(self):
        self.assertEqual(self.pm("run", sys.executable, "-c", "raise SystemExit(7)")[0], 7)

    def test_unknown_command_logs_nothing(self):
        code, out = self.pm("run", "--", "no-such-cmd-pm")
        self.assertEqual((code, out), (1, "error: command not found: no-such-cmd-pm\n"))
        self.assertEqual(self.pm("bugs")[1], "no bugs yet\n")

    def test_no_command(self):
        self.assertEqual(self.pm("run"), (1, "error: give a command, like pm run -- make test\n"))
        self.assertEqual(self.pm("run", "--")[0], 1)

    def test_keyboard_interrupt_is_not_logged(self):
        with mock.patch("pm.cli.snapshot", return_value=None), \
                mock.patch("pm.cli.subprocess.run", side_effect=KeyboardInterrupt):
            code, out = self.pm("run", "--", "x")
        self.assertEqual((code, out), (130, ""))
        self.assertEqual(self.pm("bugs")[1], "no bugs yet\n")

    def test_run_records_the_running_task(self):
        self.pm("add", "work", "--est", "30m")
        self.pm("start", "1", now="2026-11-09T09:00:00")
        self.pm("run", "--", *CHECK, now="2026-11-09T10:00:00")
        conn = connect(os.environ["PM_DB"])
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("SELECT task_id FROM runs").fetchone()[0], 1)

    def test_outside_a_repo_still_makes_an_episode(self):
        plain = Path(self.d.name) / "plain"
        plain.mkdir()
        (plain / "t.py").write_text("import sys\nsys.exit(int(open('flag').read()))\n")
        (plain / "flag").write_text("1\n")
        os.chdir(plain)
        cmd = [sys.executable, "t.py"]
        self.assertEqual(self.pm("run", "--", *cmd, now="2026-11-09T10:00:00")[0], 1)
        (plain / "flag").write_text("0\n")
        code, out = self.pm("run", "--", *cmd, now="2026-11-09T10:05:00")
        self.assertEqual(code, 0)
        self.assertIn("pm: fixed bug #1", out)
        self.assertIn("no diff (not a git repo, or not fixed)", self.pm("bug", "1")[1])

    def test_bugs_summary(self):
        self.fail_then_fix()
        code, out = self.pm("bugs")
        self.assertEqual(code, 0)
        self.assertIn("episodes 1: 1 fixed, 0 open, 0 abandoned  lost 25m", out)
        self.assertIn("tags: off-by-one 1", out)
        self.assertIn("recent:", out)
        self.assertIn(f"  #1  fixed  {shlex.join(CHECK)}  1 fail  lost 25m  [off-by-one]  {self.repo}", out)

    def test_bug_shows_details(self):
        self.fail_then_fix()
        code, out = self.pm("bug", "1")
        self.assertEqual(code, 0)
        self.assertIn(f"#1 fixed  {shlex.join(CHECK)}  {self.repo}", out)
        self.assertIn("opened 2026-11-09 10:00  closed 2026-11-09 10:25  1 fail  lost 25m", out)
        self.assertIn("tags: off-by-one", out)
        self.assertIn("+for (i = 0; i < n; i++)", out)

    def test_bug_tag_replacement(self):
        self.fail_then_fix()
        self.assertEqual(self.pm("bug", "1", "bounds", "off-by-one"),
                         (0, "#1 tags: bounds, off-by-one\n"))
        self.assertEqual(self.pm("bug", "1", "none"), (0, "#1 tags: none\n"))
        self.assertEqual(self.pm("bug", "1", "none", "overflow"),
                         (1, "error: 'none' isn't a tag; pm bug ID none clears the tags\n"))
        self.assertIn("tags: none", self.pm("bug", "1")[1])
        code, out = self.pm("bug", "1", "Bad")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("error: "))
        self.assertEqual(self.pm("bug", "9"), (1, "error: no bug #9\n"))
