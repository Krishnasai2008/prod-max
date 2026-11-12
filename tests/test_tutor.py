import os
import random
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from pm import bank, evidence, generators, grade, practice, tutor
from pm.db import connect, set_setting
from pm.files import scan
from pm.study import add_item, add_topic, coverage, track_file

NOW = datetime(2026, 11, 9, 10, 0)
OLD = NOW - timedelta(minutes=1)


def fake_extract(path):
    return path.read_text() if path.suffix == ".txt" else ""


class TutorCase(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name).resolve()
        self.vm = add_topic(self.c, "virtual memory", course="os")
        self.paging = add_topic(self.c, "paging", course="os", exam_date=(NOW + timedelta(days=11)).date(),
                                needs=["virtual memory"])
        self.other = add_topic(self.c, "joins", course="db")

    def write(self, rel, text):
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        os.utime(path, (OLD.timestamp(), OLD.timestamp()))
        return path


class TestContext(TutorCase):
    def test_context(self):
        notes = self.write("paging.md", "# P\n## A\n## B\n## C\n## D\n")
        track_file(self.c, self.paging, notes)
        gone = self.write("gone.md", "# G\n")
        track_file(self.c, self.paging, gone)
        gone.unlink()
        add_item(self.c, self.paging, notes, "P#A", now=NOW)
        add_item(self.c, self.paging, notes, "P#B", now=NOW)
        evidence.add(self.c, source="lh-quiz", ref="c/1", ts=NOW, topic_id=self.paging, correct=False,
                     confidence=0.9, grader="code", facet="understanding", label=f"{notes}#A")
        evidence.add(self.c, source="lh-quiz", ref="c/2", ts=NOW, topic_id=self.other, correct=False,
                     confidence=0.9, grader="code", label="joins question")
        before = tutor.context(self.c, self.paging, NOW)
        self.assertIsNone(before["parts"]["application"])
        for i, right in enumerate((True, False)):
            evidence.add(self.c, source="practice", ref=f"p/{i}", ts=NOW, topic_id=self.paging, correct=right,
                         grader="code", facet="application")
        ctx = tutor.context(self.c, self.paging, NOW)
        self.assertEqual((ctx["topic"], ctx["course"], ctx["exam"], ctx["days"]), ("paging", "os", "2026-11-20", 11))
        self.assertEqual((ctx["covered"], ctx["total"]), coverage(self.c, self.paging))
        self.assertEqual(ctx["covered"], 2)
        self.assertIsInstance(ctx["parts"]["application"], float)
        self.assertIsInstance(ctx["mastery"], float)
        self.assertEqual(ctx["mistakes"], [{"label": "paging.md#A", "confidence": 0.9, "source": "lh-quiz"}])
        self.assertEqual(ctx["files"], [str(notes)])
        self.assertEqual(ctx["prerequisites"], [{"topic": "virtual memory", "mastery": 0.0}])
        self.assertEqual(ctx["practised"], {"attempts": 2, "right": 1})

    def test_no_exam(self):
        ctx = tutor.context(self.c, self.vm, NOW)
        self.assertEqual((ctx["exam"], ctx["days"], ctx["mistakes"], ctx["files"]), (None, None, [], []))
        with self.assertRaises(LookupError):
            tutor.context(self.c, 99, NOW)


class TestSearch(TutorCase):
    def setUp(self):
        super().setUp()
        self.inside = self.write("notes/docs/tlb.txt", "the TLB caches\n\npage table entries")
        self.outside = self.write("Downloads/bank.txt", "statement: TLB card 1234")
        set_setting(self.c, "watch", str(self.dir))
        scan(self.c, NOW, fake_extract)

    def test_only_notes(self):
        set_setting(self.c, "notes_dir", str(self.dir / "notes" / "docs"))
        hits = tutor.search(self.c, "TLB")
        self.assertEqual([h["path"] for h in hits], [str(self.inside)])
        self.assertEqual(hits[0]["name"], "tlb.txt")
        self.assertNotIn("\n", hits[0]["snippet"])

    def test_tracked_files(self):
        self.assertEqual(tutor.search(self.c, "TLB"), [])
        track_file(self.c, self.paging, self.outside)
        self.assertEqual([h["path"] for h in tutor.search(self.c, "TLB")], [str(self.outside)])

    def test_limit_and_bad_query(self):
        set_setting(self.c, "notes_dir", str(self.dir))
        self.assertEqual(len(tutor.search(self.c, "TLB")), 2)
        self.assertEqual(len(tutor.search(self.c, "TLB", limit=1)), 1)
        self.assertEqual(tutor.search(self.c, '"a" AND ('), [])
        self.assertEqual(tutor.search(self.c, "   "), [])


class TestQuestions(TutorCase):
    def setUp(self):
        super().setUp()
        self.pdf = self.write("midsem.pdf", "%PDF")
        paper = bank.add_paper(self.c, "os", "2025 midsem", NOW, path=self.pdf)
        self.note_q = bank.add_question(self.c, origin="note", ref="n1", prompt="What is a TLB?", answer="a cache",
                                        now=NOW, trust="source", topic_id=self.paging, path=self.dir / "paging.md",
                                        locator="TLB")
        self.paper_q = bank.add_question(self.c, origin="paper", ref="p1", prompt="2025 midsem Q1", now=NOW,
                                         trust="source", topic_id=self.paging, kind="number",
                                         expected={"value": 12, "tol": 0}, marks=5, path=self.pdf, locator="p3",
                                         paper_id=paper)
        bank.add_question(self.c, origin="lh", ref="c/1", prompt="lh one", now=NOW, trust="unverified",
                          topic_id=self.paging)
        retired = bank.add_question(self.c, origin="paper", ref="p2", prompt="old", now=NOW, trust="source",
                                    topic_id=self.paging, paper_id=paper)
        bank.retire(self.c, retired, "bad")

    def test_exam_questions(self):
        qs = tutor.exam_questions(self.c, self.paging)
        self.assertEqual([q["prompt"] for q in qs], ["2025 midsem Q1", "What is a TLB?"])
        self.assertEqual(qs[0], {"prompt": "2025 midsem Q1", "answer": "12", "marks": 5, "from": "2025 midsem",
                                 "page": f"page 3 of {self.pdf}"})
        self.assertEqual((qs[1]["answer"], qs[1]["from"], qs[1]["page"]), ("a cache", "paging.md", None))
        self.assertEqual(len(tutor.exam_questions(self.c, self.paging, 1)), 1)

    def test_bank_problem_skips_pdf_pages(self):
        p = tutor.problem(self.c, self.paging, NOW, random.Random(0))
        self.assertEqual(p, {"source": "bank", "title": "paging.md", "text": "What is a TLB?", "key": "a cache",
                             "steps": ""})


class TestProblem(TutorCase):
    def test_generator(self):
        practice.link(self.c, self.paging, "paging")
        p = tutor.problem(self.c, self.paging, NOW, random.Random(7))
        again = practice.next_problem(self.c, NOW, random.Random(7), self.paging).problem
        self.assertEqual(p["source"], "generator")
        self.assertEqual((p["text"], p["key"], p["steps"]), (again.text, grade.show(again.kind, again.expected),
                                                             again.steps))
        self.assertEqual(self.c.execute("SELECT count(*) FROM evidence").fetchone()[0], 0)

    def test_nothing_verified(self):
        msg = "^no verified problem for paging yet$"
        with self.assertRaisesRegex(LookupError, msg):
            tutor.problem(self.c, self.paging, NOW, random.Random(0))
        bank.add_question(self.c, origin="lh", ref="c/1", prompt="unverified one", answer="x", now=NOW,
                          trust="unverified", topic_id=self.paging)
        pdf = self.write("a.pdf", "%PDF")
        bank.add_question(self.c, origin="manual", ref="m1", prompt="see the page", now=NOW, trust="source",
                          topic_id=self.paging, kind="number", expected={"value": 1, "tol": 0}, path=pdf, locator="p2")
        with self.assertRaisesRegex(LookupError, msg):
            tutor.problem(self.c, self.paging, NOW, random.Random(0))


if __name__ == "__main__":
    unittest.main()
