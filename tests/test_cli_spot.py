import os
import tempfile
from pathlib import Path
from unittest import mock

from pm.db import connect
from pm.study import record_review
from tests.helpers import CliCase

NOTE = "## TLB\none\ntwo\nthree\nfour\nfive\nsix\n"


def change_three(conn, prompt):
    lines = prompt.split("<excerpt>\n")[1].split("\n</excerpt>")[0].split("\n")
    lines[2] = "THREE"
    return "\n".join(lines)


class TestCliSpot(CliCase):
    def setUp(self):
        super().setUp()
        self.note = Path(self.d.name) / "os.md"
        self.note.write_text(NOTE)
        self.assertEqual(self.pm("topic", "add", "paging", "--course", "os")[0], 0)
        self.assertEqual(self.pm("study", "add", f"{self.note}#TLB", "--topic", "paging")[0], 0)

    def reviewed(self):
        conn = connect(os.environ["PM_DB"])
        try:
            from datetime import datetime
            record_review(conn, 1, 3, 0.8, datetime(2026, 11, 9, 9))
        finally:
            conn.close()

    def test_nothing_to_make_from(self):
        self.assertEqual(self.pm("spot", "--make", "1"),
                         (0, "nothing to make cards from (review some text items first)\n"))

    def test_make_and_answer_right(self):
        self.reviewed()
        with mock.patch("pm.cli.llm_ask", side_effect=change_three):
            self.assertEqual(self.pm("spot", "--make", "1"), (0, "made 1 card\n"))
        code, out = self.pm("spot", stdin="80\n3\n")
        self.assertEqual(code, 0)
        self.assertIn("[1/1] os/paging: os.md#TLB", out)
        self.assertIn("  3  THREE", out)
        self.assertIn("right: line 3", out)
        self.assertIn("was:   two", out)
        self.assertIn("shown: THREE", out)
        self.assertTrue(out.endswith("answered 1\n"))
        self.assertEqual(self.pm("spot"), (0, "no spot cards (pm spot --make 3)\n"))

    def test_answer_wrong(self):
        self.reviewed()
        with mock.patch("pm.cli.llm_ask", side_effect=change_three):
            self.pm("spot", "--make", "1")
        code, out = self.pm("spot", stdin="80\n2\n")
        self.assertIn("wrong: it was line 3", out)

    def test_quitting_answers_nothing(self):
        self.reviewed()
        with mock.patch("pm.cli.llm_ask", side_effect=change_three):
            self.pm("spot", "--make", "1")
        code, out = self.pm("spot", stdin="q\n")
        self.assertTrue(out.endswith("answered 0\n"))
        self.assertNotIn("was:", out)

    def test_no_model_is_an_error(self):
        self.reviewed()
        code, out = self.pm("spot", "--make", "1")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("error: set llm_cmd first"), out)

    def test_a_bad_reply_is_skipped(self):
        self.reviewed()
        with mock.patch("pm.cli.llm_ask", return_value="nope"):
            code, out = self.pm("spot", "--make", "1")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], "made 0 cards")
        self.assertTrue(out.splitlines()[1].startswith("skipped #1: the model didn't change"))
