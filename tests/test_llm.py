import os
import shutil
import subprocess
import time
import unittest

from pm.db import connect, put_setting, set_setting
from pm.llm import MAX_REPLY, ask, available, command, fenced


class TestLlm(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)

    def fake(self, stdout="", stderr="", code=0, error=None):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            if error is not None:
                raise error
            return subprocess.CompletedProcess(argv, code, stdout, stderr)

        return run, calls

    def test_command_and_available(self):
        self.assertIsNone(command(self.conn))
        self.assertFalse(available(self.conn))
        put_setting(self.conn, "llm_cmd", "my-llm --model small")
        self.assertEqual(command(self.conn), ["my-llm", "--model", "small"])
        self.assertTrue(available(self.conn))

    def test_available_is_false_for_a_bad_stored_value(self):
        for value in ("my-llm 'unclosed", "   ", "''"):
            with self.subTest(value=value):
                set_setting(self.conn, "llm_cmd", value)
                self.assertFalse(available(self.conn))
                with self.assertRaisesRegex(ValueError, "^llm_cmd must be a command line"):
                    command(self.conn)

    def test_a_tilde_command_is_expanded(self):
        put_setting(self.conn, "llm_cmd", "~/bin/my-llm --model small")
        self.assertEqual(command(self.conn),
                         [os.path.expanduser("~/bin/my-llm"), "--model", "small"])

    def test_unset_setting(self):
        run, calls = self.fake(stdout="x")
        with self.assertRaisesRegex(ValueError, "^set llm_cmd first"):
            ask(self.conn, "the prompt", run=run)
        self.assertEqual(calls, [])

    def test_argv_is_split_and_the_prompt_goes_on_stdin(self):
        put_setting(self.conn, "llm_cmd", "echo hi; rm -rf ~")
        run, calls = self.fake(stdout="answer")
        self.assertEqual(ask(self.conn, "the prompt", run=run), "answer")
        argv, kwargs = calls[0]
        self.assertEqual(argv, ["echo", "hi;", "rm", "-rf", "~"])
        self.assertEqual(kwargs["input"], "the prompt")
        self.assertNotIn("shell", kwargs)
        self.assertTrue(kwargs["capture_output"])
        self.assertTrue(kwargs["text"])
        self.assertEqual(kwargs["errors"], "replace")
        self.assertEqual(kwargs["timeout"], 120)

    def test_an_unparseable_stored_value_is_a_bad_command_line(self):
        set_setting(self.conn, "llm_cmd", "my-llm 'unclosed")
        run, calls = self.fake(stdout="x")
        with self.assertRaisesRegex(ValueError, "^llm_cmd must be a command line, like:"
                                      " my-llm --model small$"):
            ask(self.conn, "the prompt", run=run)
        self.assertEqual(calls, [])

    def test_a_blank_stored_value_is_a_bad_command_line(self):
        set_setting(self.conn, "llm_cmd", "   ")
        run, calls = self.fake(stdout="x")
        with self.assertRaisesRegex(ValueError, "^llm_cmd must be a command line, like:"
                                      " my-llm --model small$"):
            ask(self.conn, "the prompt", run=run)
        self.assertEqual(calls, [])

    def test_stdout_is_stripped(self):
        put_setting(self.conn, "llm_cmd", "x")
        run, _ = self.fake(stdout="  answer\n")
        self.assertEqual(ask(self.conn, "p", run=run), "answer")

    def test_nonzero_exit(self):
        put_setting(self.conn, "llm_cmd", "x")
        run, _ = self.fake(code=2, stderr="\n boom \nmore\n")
        with self.assertRaises(ValueError) as caught:
            ask(self.conn, "p", run=run)
        self.assertEqual(str(caught.exception), "the llm command failed (exit 2): boom")

    def test_nonzero_exit_without_stderr(self):
        put_setting(self.conn, "llm_cmd", "x")
        for stderr in ("", "  \n\t\n"):
            with self.subTest(stderr=stderr):
                run, _ = self.fake(code=2, stderr=stderr)
                with self.assertRaises(ValueError) as caught:
                    ask(self.conn, "p", run=run)
                self.assertEqual(str(caught.exception), "the llm command failed (exit 2)")

    def test_stderr_is_cut_to_200_characters(self):
        put_setting(self.conn, "llm_cmd", "x")
        run, _ = self.fake(code=1, stderr="e" * 300)
        with self.assertRaises(ValueError) as caught:
            ask(self.conn, "p", run=run)
        self.assertEqual(str(caught.exception), "the llm command failed (exit 1): " + "e" * 200)

    def test_empty_output(self):
        put_setting(self.conn, "llm_cmd", "x")
        run, _ = self.fake(stdout=" \n ")
        with self.assertRaisesRegex(ValueError, "^the llm command printed nothing$"):
            ask(self.conn, "p", run=run)

    def test_missing_command(self):
        put_setting(self.conn, "llm_cmd", "echo hi")
        run, _ = self.fake(error=FileNotFoundError(2, "No such file or directory"))
        with self.assertRaisesRegex(ValueError, "^llm_cmd not found: echo$"):
            ask(self.conn, "p", run=run)

    def test_permission_denied_looks_missing(self):
        put_setting(self.conn, "llm_cmd", "secret-llm")
        run, _ = self.fake(error=PermissionError(13, "Permission denied"))
        with self.assertRaisesRegex(ValueError, "^llm_cmd not found: secret-llm$"):
            ask(self.conn, "p", run=run)

    def test_other_oserror(self):
        put_setting(self.conn, "llm_cmd", "x")
        run, _ = self.fake(error=OSError("too many open files"))
        with self.assertRaisesRegex(ValueError, "^couldn't run the llm command: too many open files$"):
            ask(self.conn, "p", run=run)

    def test_timeout(self):
        put_setting(self.conn, "llm_cmd", "x")
        run, _ = self.fake(error=subprocess.TimeoutExpired(["x"], 120))
        with self.assertRaisesRegex(ValueError, "^the llm command took over 120s$"):
            ask(self.conn, "p", run=run)

    def test_a_custom_timeout(self):
        put_setting(self.conn, "llm_cmd", "x")
        run, calls = self.fake(error=subprocess.TimeoutExpired(["x"], 5))
        with self.assertRaisesRegex(ValueError, "^the llm command took over 5s$"):
            ask(self.conn, "p", timeout=5, run=run)
        self.assertEqual(calls[0][1]["timeout"], 5)

    def test_reply_is_cut(self):
        put_setting(self.conn, "llm_cmd", "x")
        run, _ = self.fake(stdout="x" * 300_000)
        self.assertEqual(len(ask(self.conn, "p", run=run)), MAX_REPLY)
        self.assertEqual(MAX_REPLY, 200_000)

    def test_fenced(self):
        self.assertEqual(fenced("```md\na\nb\n```"), "a\nb")
        self.assertEqual(fenced("a\n```\nb\n```"), "a\n```\nb\n```")
        self.assertEqual(fenced("plain"), "plain")
        self.assertEqual(fenced("  ```md\na\n```"), "a")
        self.assertEqual(fenced("```md\na\n```\n\n"), "a")

    @unittest.skipUnless(shutil.which("cat"), "needs cat")
    def test_real_command(self):
        put_setting(self.conn, "llm_cmd", "cat")
        self.assertEqual(ask(self.conn, "hello"), "hello")

    @unittest.skipUnless(shutil.which("sh") and shutil.which("sleep"), "needs sh and sleep")
    def test_a_timeout_also_stops_a_wrapper_scripts_child(self):
        put_setting(self.conn, "llm_cmd", "sh -c 'sleep 30; true'")  # sh waits on a child that holds the output open
        start = time.monotonic()
        with self.assertRaisesRegex(ValueError, "took over 1s"):
            ask(self.conn, "hello", timeout=1)
        self.assertLess(time.monotonic() - start, 10)

