import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from pm.bank import (add_paper, add_question, check_paper_lines, counts, stats, to_check, get_question, has, import_note, import_paper, questions,
                     restore, retire)
from pm.db import connect
from pm.excerpt import Section
from pm.study import add_topic

NOW = datetime(2026, 11, 9, 10, 0)
NOTE = """# Paging

## TLB
What does the TLB cache?

**Answer.** Page-table entries.

## Walk
How many accesses in a 2-level walk?

**Answer:** two, plus the data.

## Plain
Just notes here.
a
b
"""
LINES = ["# label | marks | topic | where | answer",
         "Q1a | 5 | paging | p2",
         "Q1b | 3 | paging | p2 | =12",
         "Q2  | 4 | scheduling | p3 | =6.25~0.01",
         "Q3  | 8 | deadlock |  | Safe; one safe order is P1 P3 P4 P0 P2."]


class BankCase(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)
        for name in ("paging", "scheduling", "deadlock"):
            add_topic(self.c, name, course="os")
        add_topic(self.c, "joins", course="db")

    def q(self, ref="m1", **kw):
        args = dict(origin="manual", ref=ref, prompt="What is a TLB?", now=NOW, trust="source", topic_id=1,
                    answer="a cache")
        args.update(kw)
        return add_question(self.c, **args)


class TestQuestions(BankCase):
    def test_round_trip(self):
        q = get_question(self.c, self.q())
        self.assertEqual((q.kind, q.expected, q.answer, q.trust), ("open", None, "a cache", "source"))
        n = get_question(self.c, self.q("m2", kind="number", expected={"value": 12, "tol": 0}, answer=None))
        self.assertEqual(n.expected, {"value": 12, "tol": 0})

    def test_has(self):
        self.assertFalse(has(self.c, "manual", "m1"))
        self.q()
        self.assertTrue(has(self.c, "manual", "m1"))
        self.assertFalse(has(self.c, "lh", "m1"))

    def test_rules(self):
        self.q()
        cases = [
            (dict(prompt="  "), "a question needs text"),
            (dict(prompt="x" * 20_001), "that question is too long"),
            (dict(marks=0), "marks must be positive"),
            (dict(origin="web"), "unknown origin 'web'"),
            (dict(trust="great"), "unknown trust level 'great'"),
            (dict(expected={"value": 1}), "an open question has no answer key"),
            (dict(kind="number"), "a number question needs an answer key"),
            (dict(kind="choice", expected={"options": ["a", "b"], "correct": [3]}), "correct must name options 1-2"),
            (dict(origin="paper"), "a paper question needs its paper"),
            (dict(ref="m1"), "that question is already in the bank"),
        ]
        for n, (kw, message) in enumerate(cases):
            kw = {"ref": f"r{n}", **kw}
            with self.subTest(kw=kw), self.assertRaises(ValueError) as e:
                self.q(**kw)
            self.assertEqual(str(e.exception), message)
        with self.assertRaises(LookupError):
            self.q("r99", topic_id=99)
        with self.assertRaises(LookupError):
            get_question(self.c, 99)

    def test_retire_restore_filter_counts(self):
        self.q()
        self.q("m2", topic_id=1)
        self.q("m3", topic_id=4)
        self.assertEqual(counts(self.c), [(1, "source", 2), (4, "source", 1)])
        retire(self.c, 1, "wrong key")
        self.assertEqual([q.id for q in questions(self.c)], [2, 3])
        self.assertEqual(questions(self.c, retired=True)[0].retired, "wrong key")
        restore(self.c, 1)
        self.assertEqual([q.id for q in questions(self.c, course="os")], [1, 2])
        self.assertEqual([q.id for q in questions(self.c, topic_id=4)], [3])
        self.assertEqual(questions(self.c, origin="paper"), [])


class TestImportNote(BankCase):
    def test_import(self):
        path = self.dir / "os.md"
        path.write_text(NOTE)
        self.assertEqual(import_note(self.c, path, 1, NOW), (2, 0))
        first, second = questions(self.c)
        self.assertEqual(first.prompt, "What does the TLB cache?")
        self.assertTrue(first.answer.startswith("**Answer"))
        self.assertEqual((first.origin, first.locator, first.trust), ("note", "TLB", "source"))
        self.assertEqual(second.prompt, "How many accesses in a 2-level walk?")
        self.assertEqual(import_note(self.c, path, 1, NOW), (0, 2))

    def test_errors_and_empty(self):
        txt = self.dir / "a.txt"
        txt.write_text("x")
        with self.assertRaises(ValueError) as e:
            import_note(self.c, txt, 1, NOW)
        self.assertEqual(str(e.exception), "question import needs a markdown file")
        plain = self.dir / "plain.md"
        plain.write_text("# A\nx\ny\nz\n")
        self.assertEqual(import_note(self.c, plain, 1, NOW), (0, 0))


class TestPapers(BankCase):
    def pdf(self):
        path = self.dir / "midsem.pdf"
        path.write_bytes(b"%PDF-1.4\n")
        return path

    def pages(self, n=3):
        return mock.patch("pm.bank.outline", return_value=[Section(f"p{k}", f"page {k}", 1, 0, True, True)
                                                            for k in range(1, n + 1)])

    def test_add_paper(self):
        self.assertEqual(add_paper(self.c, "os", "2025 midsem", NOW, minutes=90), 1)
        for args, message in [(("os", "2025 midsem"), "os already has a paper called '2025 midsem'"),
                              (("", "x"), "a paper needs a course and a title")]:
            with self.assertRaises(ValueError) as e:
                add_paper(self.c, *args, NOW)
            self.assertEqual(str(e.exception), message)
        with self.assertRaisesRegex(ValueError, "^no such file: "):
            add_paper(self.c, "os", "y", NOW, path=self.dir / "gone.pdf")
        with self.assertRaisesRegex(ValueError, "^minutes must be positive$"):
            add_paper(self.c, "os", "z", NOW, minutes=0)

    def test_import(self):
        paper = add_paper(self.c, "os", "2025 midsem", NOW, path=self.pdf())
        with self.pages():
            self.assertEqual(import_paper(self.c, paper, LINES, NOW), (4, 0, []))
            q1a, q1b, q2, q3 = questions(self.c, paper_id=paper)
            self.assertEqual((q1a.kind, q1a.locator, q1a.marks, q1a.prompt), ("open", "p2", 5, "2025 midsem Q1a"))
            self.assertEqual((q1b.kind, q1b.expected), ("number", {"value": 12, "tol": 0}))
            self.assertEqual(q2.expected["tol"], 0.01)
            self.assertEqual((q3.kind, q3.answer, q3.locator), ("open", "Safe; one safe order is P1 P3 P4 P0 P2.", None))
            self.assertEqual(import_paper(self.c, paper, LINES, NOW), (0, 4, []))

    def test_bad_lines(self):
        paper = add_paper(self.c, "os", "endsem", NOW, path=self.pdf())
        lines = ["Q8 | 2 | paging", "Q9 | x | paging", "Q10 | 2 | pagin", "Q11 | 2", "Q12 | 2 | paging | p9",
                 "Q13 | 2 | paging | | =abc", "", "# comment", "Q8 | 2 | paging"]
        with self.pages():
            checked = check_paper_lines(self.c, paper, lines)
            self.assertEqual(questions(self.c, paper_id=paper), [])
            added, skipped, errors = import_paper(self.c, paper, lines, NOW)
        self.assertEqual(checked, errors)
        self.assertEqual((added, skipped), (1, 1))
        self.assertEqual(errors, ["line 2: marks must be a positive number",
                                  "line 3: no topic 'pagin' in os",
                                  "line 4: expected label | marks | topic",
                                  "line 5: no page 9 in midsem.pdf",
                                  "line 6: couldn't read '=abc' as a number"])

    def test_no_pdf(self):
        paper = add_paper(self.c, "os", "quiz", NOW)
        self.assertEqual(import_paper(self.c, paper, ["Q1 | 2 | paging | p2"], NOW),
                         (0, 0, ['line 1: this paper has no PDF, so leave "where" empty']))


class TestStats(BankCase):
    def marked(self, scores, *, trust="source", confidence=None, marked=True, question=None):
        """One test per score on one question; returns the question id."""
        qid = question or self.q(f"s{self.c.execute('SELECT count(*) FROM questions').fetchone()[0]}", trust=trust)
        for score in scores:
            mid = self.c.execute("INSERT INTO mocks(course, title, minutes, created, marked) VALUES('os', 't', 10, ?, ?)",
                                 (NOW.isoformat(), NOW.isoformat() if marked else None)).lastrowid
            self.c.execute("INSERT INTO mock_items(mock_id, pos, question_id, topic_id, marks, score, confidence)"
                           " VALUES(?, 1, ?, 1, 1, ?, ?)", (mid, qid, score, confidence))
        self.c.commit()
        return qid

    def test_flags(self):
        self.assertEqual(stats(self.c), {})
        easy = self.marked([1, 1, 1])
        hard = self.marked([0, 0, 0.2])
        fine = self.marked([1, 1])
        s = stats(self.c)
        self.assertEqual((s[easy].mean, s[easy].flags), (1.0, ["too easy"]))
        self.assertEqual(s[hard].flags, ["too hard"])
        self.assertEqual((s[fine].attempts, s[fine].flags), (2, []))

    def test_suspect(self):
        suspect = self.marked([0], trust="unverified", confidence=0.9)
        trusted = self.marked([0], trust="source", confidence=0.9)
        unsure = self.marked([0], trust="checked", confidence=0.7)
        half = self.marked([0.5], trust="checked", confidence=0.9)
        s = stats(self.c)
        self.assertEqual(s[suspect].flags, ["suspect"])
        for qid in (trusted, unsure, half):
            self.assertEqual(s[qid].flags, [])

    def test_to_check_and_unmarked(self):
        easy = self.marked([1, 1, 1])
        suspect = self.marked([0], trust="unverified", confidence=0.9)
        gone = self.marked([1, 1, 1], trust="checked")
        retire(self.c, gone)
        self.assertEqual([q.id for q, _ in to_check(self.c)], [suspect, easy])
        unmarked = self.marked([1, 1, 1], trust="checked", marked=False)
        self.assertNotIn(unmarked, stats(self.c))
