from pathlib import Path
from unittest import mock

from tests.helpers import CliCase

NOTE = """# Paging

## TLB
What does the TLB cache?

**Answer.** Page-table entries.

## Walk
How many accesses?

**Answer:** two.
"""


class TestQuestionCli(CliCase):
    def setUp(self):
        super().setUp()
        self.pm("topic", "add", "paging", "--course", "os")

    def test_add_and_list(self):
        self.assertEqual(self.pm("q", "add", "What is a TLB?", "--topic", "paging", "--answer", "a cache"),
                         (0, "question #1 added to paging\n"))
        code, out = self.pm("q", "add", "What is a TLB?", "--topic", "paging", "--answer", "a cache")
        self.assertEqual(code, 1)
        self.assertIn("already in the bank", out)
        self.assertEqual(self.pm("q", "add", "Faults?", "--topic", "paging", "--number", "12")[0], 0)
        self.assertEqual(self.pm("q", "add", "Pick", "--topic", "paging", "--choice", "FIFO;LRU", "--correct", "2")[0], 0)
        out = self.pm("q", "ls")[1].splitlines()
        self.assertEqual(out[0], "#1  os/paging  source  open  1 mark  What is a TLB?")
        self.assertIn("  number  ", out[1])
        self.assertIn("  choice  ", out[2])
        with self.assertRaises(SystemExit) as caught:
            self.pm("q", "add", "x", "--topic", "paging", "--answer", "a", "--number", "1")
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.pm("q", "retire", "1", "wrong", "key"), (0, "retired #1\n"))
        self.assertNotIn("What is a TLB?", self.pm("q", "ls")[1])
        self.assertEqual(self.pm("q", "restore", "1"), (0, "restored #1\n"))

    def test_import(self):
        note = Path(self.d.name) / "os.md"
        note.write_text(NOTE)
        self.assertEqual(self.pm("q", "import", str(note), "--topic", "paging"), (0, "added 2 questions to paging\n"))
        self.assertEqual(self.pm("q", "import", str(note), "--topic", "paging"),
                         (0, "added 0 questions to paging (2 already there)\n"))
        plain = Path(self.d.name) / "plain.md"
        plain.write_text("# A\nx\n")
        self.assertEqual(self.pm("q", "import", str(plain), "--topic", "paging"),
                         (0, "no sections with an answer in that file\n"))
        self.assertEqual(self.pm("q", "ls", "--course", "db"), (0, "no questions\n"))

    def test_papers(self):
        self.assertEqual(self.pm("paper", "ls"), (0, "no papers\n"))
        self.assertEqual(self.pm("paper", "add", "2025 midsem", "--course", "os", "--minutes", "90"),
                         (0, "paper #1 2025 midsem\n"))
        lines = Path(self.d.name) / "list.txt"
        lines.write_text("Q1 | 2 | paging\nQ2 | 3 | paging | | =12\nQ3 | x | paging\n")
        code, out = self.pm("paper", "import", "1", str(lines))
        self.assertEqual(code, 1)
        self.assertEqual(out, "added 2 questions\nline 3: marks must be a positive number\n")
        self.assertEqual(self.pm("paper", "ls"), (0, "#1  os  2025 midsem  2 questions  1h30m\n"))
        self.assertEqual(self.pm("paper", "import", "1", str(Path(self.d.name) / "nope.txt"))[0], 1)


class TestMockCli(CliCase):
    def setUp(self):
        super().setUp()
        self.pm("topic", "add", "paging", "--course", "os")
        self.pm("paper", "add", "set", "--course", "os")
        lines = Path(self.d.name) / "list.txt"
        lines.write_text("Q1 | 2 | paging | | =12\nQ2 | 5 | paging | | a cache of entries\n")
        self.pm("paper", "import", "1", str(lines))
        self.pm("q", "add", "Pick", "--topic", "paging", "--choice", "FIFO;LRU", "--correct", "2")

    def test_full_run(self):
        self.assertEqual(self.pm("mock", "ls"), (0, "no tests\n"))
        code, out = self.pm("mock", "new", "--paper", "1")
        self.assertEqual((code, out), (0, "test #1: 2 questions, 10m (pm mock take 1)\n"))
        self.assertIn("ready", self.pm("mock", "ls")[1])
        self.assertEqual(self.pm("mock", "show", "1")[0], 1)
        code, out = self.pm("mock", "take", "1", stdin="12\n80\nit caches entries\n60\n2\n")
        self.assertEqual(code, 0, out)
        for part in ("[1/2] paging  2 marks", "model answer:", "a cache of entries", "score 4 of 7 (57%)"):
            self.assertIn(part, out)
        self.assertIn("marked 57%", self.pm("mock", "ls")[1])
        self.assertTrue(self.pm("mock", "show", "1")[1].startswith("test #1  set\nscore 4 of 7 (57%)\n"))
        self.assertEqual(self.pm("mock", "retry", "1")[1], "test #2: 1 question, 8m (pm mock take 2)\n")

    def test_pause_and_resume(self):
        self.pm("mock", "new", "--paper", "1")
        self.assertTrue(self.pm("mock", "take", "1", stdin="q\n")[1].endswith(": paused test #1 (pm mock take 1)\n"))
        self.assertIn("[1/2]", self.pm("mock", "take", stdin="q\n")[1])
        out = self.pm("mock", "take", stdin="12\n80\nq\n")[1]
        self.assertIn("paused test #1", out)
        self.assertIn("[2/2]", self.pm("mock", "take", stdin="q\n")[1])

    def test_sample_and_errors(self):
        self.assertTrue(self.pm("mock", "new", "--course", "os", "-n", "3")[1].startswith("test #1: 3 questions, "))
        code, out = self.pm("mock", "new", "--course", "nope")
        self.assertEqual(code, 1)
        self.assertIn("no questions for nope yet", out)
        self.assertEqual(self.pm("mock", "new")[0], 1)


class TestGeneratedMockCli(CliCase):
    def test_generated_test(self):
        self.pm("topic", "add", "paging", "--course", "os")
        self.pm("practice", "link", "paging", "--topic", "paging")
        self.assertEqual(self.pm("mock", "new", "--course", "os", "-n", "2")[0], 0)
        code, out = self.pm("mock", "take", "1", stdin="\n\n")
        self.assertEqual(code, 0, out)
        self.assertIn("Frames: ", out)
        self.assertIn("score 0 of 4 (0%)", out)


class TestVaryCli(CliCase):
    def test_vary(self):
        from tests.test_variants import good
        self.pm("topic", "add", "disk", "--course", "os")
        self.pm("q", "add", "A disk has 200 cylinders. How far does the head move?", "--topic", "disk", "--number", "36")
        ask = good()
        with mock.patch("pm.cli.llm_ask", side_effect=lambda conn, prompt: ask(prompt)):
            self.assertEqual(self.pm("q", "vary", "1"), (0, "3 variants of #1 added, 0 dropped\n"))
        lines = self.pm("q", "ls")[1].splitlines()
        self.assertEqual(sum("  checked  " in line for line in lines), 3)
        self.assertEqual(self.pm("q", "vary", "9")[0], 1)


class TestPaperDraftCli(CliCase):
    def test_draft(self):
        from pm.excerpt import Section
        self.pm("topic", "add", "paging", "--course", "os")
        pdf = Path(self.d.name) / "midsem.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        self.pm("paper", "add", "2025 midsem", "--course", "os", "--file", str(pdf))
        sections = [Section("p1", "page 1", 1, 0, True, True)]
        with mock.patch("pm.drafts.outline", return_value=sections), \
                mock.patch("pm.bank.outline", return_value=sections), \
                mock.patch("pm.drafts.excerpt", return_value="Q1 (5 marks) What is a TLB?"), \
                mock.patch("pm.cli.llm_ask", return_value="Q1 | 5 | paging | p1"):
            code, out = self.pm("paper", "draft", "1")
        self.assertEqual(code, 0, out)
        self.assertIn("# label | marks | topic | where | answer\n", out)
        self.assertIn("\nQ1 | 5 | paging | p1\n", out)
        self.assertTrue(out.endswith("review this list before importing it: marks and topics are the model's guesses\n"))


class TestReviewCli(CliCase):
    def test_review(self):
        import os
        from pm.db import connect
        self.assertEqual(self.pm("q", "review"), (0, "no questions need a look\n"))
        self.pm("topic", "add", "paging", "--course", "os")
        self.pm("q", "add", "What is the page size?\nmore", "--topic", "paging", "--number", "4096")
        conn = connect(os.environ["PM_DB"])
        conn.execute("UPDATE questions SET trust='unverified'")
        for score in (0, 0.5):
            mid = conn.execute("INSERT INTO mocks(course, title, minutes, created, marked) VALUES('os', 't', 10,"
                               " '2026-11-09', '2026-11-09')").lastrowid
            conn.execute("INSERT INTO mock_items(mock_id, pos, question_id, topic_id, marks, score, confidence)"
                         " VALUES(?, 1, 1, 1, 1, ?, 0.9)", (mid, score))
        conn.commit()
        conn.close()
        self.assertEqual(self.pm("q", "review"), (0, "#1  suspect  unverified  2 tries, mean 25%  What is the page size?\n"
                                                     "retire one with: pm q retire ID reason\n"))
