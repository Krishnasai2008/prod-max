import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

from pm.links import short

from tests.helpers import CliCase


class TestCli(CliCase):
    def test_empty_db_reads(self):
        for cmd, msg in [("ls", "no open tasks"), ("risk", "nothing with a due date"),
                         ("bias", "no finished tasks yet (assuming x1.50)"), ("today", "nothing to do")]:
            self.assertEqual(self.pm(cmd), (0, msg + "\n"))

    def test_full_loop(self):
        self.assertEqual(self.pm("add", "OS lab 3", "--est", "4h", "--due", "+3", "--kind", "lab",
                                 "--first", "open lab3.pdf"), (0, "added #1\n"))
        code, out = self.pm("start", "1")
        self.assertIn("first step: open lab3.pdf", out)
        self.assertEqual(self.pm("stop", "bug in fork()", now="2026-11-09T10:45:00"), (0, "stopped #1 after 45m\n"))
        self.assertIn("where you left off: bug in fork()", self.pm("start", "1")[1])
        self.assertIn("▶", self.pm("ls")[1])
        code, out = self.pm("risk")
        self.assertIn("start by 2026-11-", out)
        self.assertIn("crunch risk", out)
        self.assertIn("Deep work (peak 09-12):", self.pm("today")[1])
        self.assertEqual(self.pm("done", "1", now="2026-11-09T14:45:00"), (0, "done #1: 4h45m logged, estimated 4h\n"))

    def test_long_session_warning(self):
        self.pm("add", "x", "--est", "1h")
        self.pm("start", "1")
        self.assertIn("warning: that ran 14h", self.pm("stop", now="2026-11-10T00:00:00")[1])

    def test_errors(self):
        self.assertEqual(self.pm("start", "9"), (1, "error: no task #9\n"))
        self.assertEqual(self.pm("stop"), (1, "nothing running\n"))
        self.assertEqual(self.pm("set", "colour", "red")[0], 1)
        self.assertEqual(self.pm("set", "hours_per_day", "0.001")[0], 1)  # rounds to 0 min: would crash risk
        self.assertEqual(self.pm("set", "hours_per_day", "0.1"), (0, "hours_per_day = 0.1\n"))
        with self.assertRaises(SystemExit):
            self.pm("add", "x", "--est", "abc")

    def test_nudge_hours_must_be_a_forward_window(self):
        self.assertEqual(self.pm("set", "nudge_hours", "22-08")[0], 1)
        self.assertEqual(self.pm("set", "nudge_hours", "09-21"), (0, "nudge_hours = 09-21\n"))

    def test_edit_and_drop(self):
        self.pm("add", "a", "--est", "1h", "--due", "+3")
        self.assertEqual(self.pm("edit", "1", "--title", "b", "--no-due"), (0, "edited #1\n"))
        code, out = self.pm("ls")
        self.assertIn("b", out)
        self.assertIn("due -", out)
        self.assertEqual(self.pm("edit", "1"), (1, "error: nothing to change\n"))
        with self.assertRaises(SystemExit) as exit:
            self.pm("edit", "1", "--due", "+1", "--no-due")
        self.assertEqual(exit.exception.code, 2)
        self.assertEqual(self.pm("drop", "1"), (0, "dropped #1\n"))
        self.assertEqual(self.pm("ls"), (0, "no open tasks\n"))
        self.assertEqual(self.pm("bias"), (0, "no finished tasks yet (assuming x1.50)\n"))

    def test_edit_clears_course_and_first_step(self):
        self.pm("add", "a", "--est", "1h", "--course", "os", "--first", "open it")
        self.assertEqual(self.pm("edit", "1", "--course", "", "--first", ""), (0, "edited #1\n"))
        code, out = self.pm("ls")
        self.assertIn("#1  a  [task/-]", out)

    def test_link_add_list_and_remove(self):
        self.pm("add", "a", "--est", "1h")
        path = Path(self.d.name) / "lab3.pdf"
        path.write_text("x")
        target = short(str(path.resolve()))
        self.assertEqual(self.pm("link", "1", str(path)), (0, f"linked #1: {target}\n"))
        self.assertEqual(self.pm("link", "1"), (0, f"1  {target}\n"))
        self.assertEqual(self.pm("link", "1", "--rm", "1"), (0, f"unlinked #1: {target}\n"))
        self.assertEqual(self.pm("link", "1"), (0, "no links on #1\n"))
        self.assertEqual(self.pm("link", "1", "--rm", "5"), (1, "error: #1 has no link 5\n"))

    def test_link_rm_uses_the_listed_number(self):
        self.pm("add", "a", "--est", "1h")
        first = Path(self.d.name) / "a.pdf"
        first.write_text("x")
        second = Path(self.d.name) / "folder"
        second.mkdir()
        self.pm("link", "1", str(first))
        self.pm("link", "1", str(second))
        self.assertEqual(self.pm("link", "1", "--rm", "1"),
                         (0, f"unlinked #1: {short(str(first.resolve()))}\n"))
        self.assertEqual(self.pm("link", "1"), (0, f"1  {short(str(second.resolve()))}\n"))

    def test_link_resolves_a_relative_path_from_the_current_directory(self):
        self.pm("add", "a", "--est", "1h")
        (Path(self.d.name) / "lab3.pdf").write_text("x")
        cwd = os.getcwd()
        try:
            os.chdir(self.d.name)
            code, out = self.pm("link", "1", "lab3.pdf")
        finally:
            os.chdir(cwd)
        target = short(str((Path(self.d.name) / "lab3.pdf").resolve()))
        self.assertEqual((code, out), (0, f"linked #1: {target}\n"))

    def test_link_adds_and_lists_an_https_address(self):
        self.pm("add", "a", "--est", "1h")
        target = "https://example.com/a?b=1"
        self.assertEqual(self.pm("link", "1", target), (0, f"linked #1: {target}\n"))
        self.assertEqual(self.pm("link", "1"), (0, f"1  {target}\n"))

    def test_link_on_an_unknown_task_is_an_error(self):
        self.assertEqual(self.pm("link", "99"), (1, "error: no task #99\n"))

    def test_link_refuses_an_empty_target(self):
        self.pm("add", "a", "--est", "1h")
        for target in ("", "   "):
            with self.subTest(target=target):
                self.assertEqual(self.pm("link", "1", target),
                                 (1, "error: give a full path or an http(s) address\n"))

    def test_link_rm_and_a_target_are_mutually_exclusive(self):
        self.pm("add", "a", "--est", "1h")
        with self.assertRaises(SystemExit) as exit:
            self.pm("link", "1", "--rm", "2", "file.pdf")
        self.assertEqual(exit.exception.code, 2)

    def test_start_opens_links_and_prints_what_it_skipped(self):
        self.pm("add", "a", "--est", "1h")
        with mock.patch("pm.cli.open_links", return_value=(2, ["gone ~/x.pdf"])) as opened:
            code, out = self.pm("start", "1")
        self.assertEqual(code, 0)
        self.assertTrue(out.endswith("opened 2 links\nskipped: gone ~/x.pdf\n"))
        opened.assert_called_once_with(mock.ANY, 1)

    def test_start_prints_a_single_link_in_the_singular(self):
        self.pm("add", "a", "--est", "1h")
        with mock.patch("pm.cli.open_links", return_value=(1, [])):
            code, out = self.pm("start", "1")
        self.assertEqual(code, 0)
        self.assertTrue(out.endswith("opened 1 link\n"))

    def test_start_with_no_links_prints_nothing_new(self):
        self.pm("add", "a", "--est", "1h")
        self.assertEqual(self.pm("start", "1"), (0, "started #1 a\n"))

    def test_start_no_open_lists_the_links_and_does_not_launch(self):
        self.pm("add", "a", "--est", "1h")
        path = Path(self.d.name) / "lab3.pdf"
        path.write_text("x")
        target = short(str(path.resolve()))
        self.pm("link", "1", str(path))
        with mock.patch("pm.cli.open_links") as opened:
            code, out = self.pm("start", "1", "--no-open")
        opened.assert_not_called()
        self.assertEqual((code, out), (0, f"started #1 a\nlinks:\n  {target}\n"))

    def test_course_codes_must_be_name_code_pairs(self):
        self.assertEqual(self.pm("set", "course_codes", "os=CS F372; dbms")[0], 1)
        self.assertEqual(self.pm("set", "course_codes", "os=CS F372; dbms=CS F212"),
                         (0, "course_codes = os=CS F372; dbms=CS F212\n"))

    def test_set_checks_hours_urls_and_watch_folders(self):
        self.assertEqual(self.pm("set", "hours_per_day", "abc"),
                         (1, "error: hours_per_day must be between 0.1 and 16\n"))
        self.assertEqual(self.pm("set", "hours_per_day", "nan")[0], 1)
        self.assertEqual(self.pm("set", "notes_url", "http://x.dev"),
                         (1, "error: notes_url must be empty or https://your-site\n"))
        self.assertEqual(self.pm("set", "notes_url", "https://x.dev"),
                         (0, "notes_url = https://x.dev\n"))
        self.assertEqual(self.pm("set", "watch", "Downloads"),
                         (1, "error: watch folders must be full paths like ~/Downloads\n"))
        self.assertEqual(self.pm("set", "watch", "/tmp:~/Downloads"),
                         (0, "watch = /tmp:~/Downloads\n"))
        self.assertEqual(self.pm("set", "watch_ignore", "Downloads"),
                         (1, "error: watch_ignore folders must be full paths like ~/Downloads\n"))
        self.assertEqual(self.pm("set", "watch_ignore", ""), (0, "watch_ignore = \n"))

    def test_llm_without_a_command(self):
        self.assertEqual(self.pm("llm", "hi"),
                         (1, "error: set llm_cmd first, like: pm set llm_cmd 'my-llm --model small'\n"))

    def test_llm_error_exits(self):
        for message in ("the llm command failed (exit 2): boom",
                        "llm_cmd not found: no-such-llm",
                        "the llm command took over 120s"):
            with self.subTest(message=message), \
                    mock.patch("pm.cli.llm_ask", side_effect=ValueError(message)):
                self.assertEqual(self.pm("llm", "hi"), (1, f"error: {message}\n"))

    def test_llm_joins_the_words_and_prints_the_reply(self):
        with mock.patch("pm.cli.llm_ask", return_value="pong") as ask:
            self.assertEqual(self.pm("llm", "hello", "there"), (0, "pong\n"))
        self.assertEqual(ask.call_args.args[1], "hello there")

    @unittest.skipUnless(shutil.which("cat"), "needs cat")
    def test_llm_runs_the_configured_command(self):
        self.assertEqual(self.pm("set", "llm_cmd", "cat"), (0, "llm_cmd = cat\n"))
        self.assertEqual(self.pm("llm", "hello", "there"), (0, "hello there\n"))


class TestAgentCli(CliCase):
    def test_agent(self):
        self.assertEqual(self.pm("agent", "ls"), (0, "no jobs\nbudget: 0 of 0 calls used today\n"))
        self.pm("set", "agent_daily_calls", "5")
        self.pm("set", "llm_cmd", "my-llm")
        self.assertEqual(self.pm("agent", "add", "ping"), (0, "queued ping #1\n"))
        with mock.patch("pm.cli.llm_ask", return_value="ok") as ask:
            code, out = self.pm("agent", "run")
        self.assertEqual((code, out), (0, "ping #1: ping: ok\n"))
        self.assertEqual(ask.call_args.args[1], "Reply with the word ok.")
        self.assertEqual(self.pm("agent", "ls"), (0, "#1  ping  done  1 call  ping: ok\nbudget: 1 of 5 calls used today\n"))
        self.assertEqual(self.pm("agent", "run"), (0, "nothing queued\n"))
        self.assertEqual(self.pm("agent", "add", "nope")[0], 1)

    def test_no_budget(self):
        self.pm("agent", "add", "ping")
        self.assertEqual(self.pm("agent", "run"), (0, "no budget left today (pm set agent_daily_calls N)\n"))
        self.assertIn("#1  ping  queued  0 calls\n", self.pm("agent", "ls")[1])
