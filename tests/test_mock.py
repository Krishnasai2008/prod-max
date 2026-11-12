import random
import unittest
from collections import Counter
from datetime import date, datetime, timedelta

from pm import mock
from pm.bank import add_paper, add_question
from pm.db import connect
from pm.study import add_topic, readiness

NOW = datetime(2026, 11, 9, 10, 0)


class MockCase(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)
        self.refs = 0

    def topics(self, exam=None):
        for name, weight in (("a", 2), ("b", 1), ("c", 1)):
            add_topic(self.c, name, course="os", weight=weight, exam_date=exam)

    def q(self, topic, trust="source", kind="open", expected=None, marks=1, answer=None, **kw):
        self.refs += 1
        return add_question(self.c, origin="manual", ref=f"r{self.refs}", prompt=f"question {self.refs}\nmore",
                            now=NOW, trust=trust, topic_id=topic, kind=kind, expected=expected, marks=marks,
                            answer=answer, **kw)

    def fill(self, *per_topic):
        for topic, count in enumerate(per_topic, 1):
            for _ in range(count):
                self.q(topic)

    def picked(self, mock_id):
        return Counter(i.topic_id for i in mock.items(self.c, mock_id))


class TestBuild(MockCase):
    def test_seats(self):
        self.topics()
        self.fill(10, 10, 10)
        self.assertEqual(self.picked(mock.build(self.c, "os", NOW, random.Random(0), n=8)), {1: 4, 2: 2, 3: 2})
        self.assertEqual(self.picked(mock.build(self.c, "os", NOW, random.Random(0), n=10)), {1: 5, 2: 3, 3: 2})

    def test_short_topics(self):
        self.topics()
        self.fill(1, 10, 10)
        self.assertEqual(self.picked(mock.build(self.c, "os", NOW, random.Random(0), n=8)), {1: 1, 2: 4, 3: 3})

    def test_small_and_empty_pools(self):
        self.topics()
        for msg, kw in (("a test has 1-100 questions", {"n": 0}), ("a test has 1-100 questions", {"n": 101}),
                        ("a test lasts 1-600 minutes", {"minutes": 601})):
            with self.assertRaisesRegex(ValueError, f"^{msg}$"):
                mock.build(self.c, "os", NOW, random.Random(0), **kw)
        with self.assertRaisesRegex(ValueError, "^no questions for os yet"):
            mock.build(self.c, "os", NOW, random.Random(0))
        self.fill(2, 1)
        self.assertEqual(len(mock.items(self.c, mock.build(self.c, "os", NOW, random.Random(0)))), 3)

    def test_preference(self):
        self.topics()
        self.q(2, trust="unverified")
        good = self.q(2, trust="source")
        one = mock.build(self.c, "os", NOW, random.Random(0), n=1)
        self.assertEqual([i.question_id for i in mock.items(self.c, one)], [good])
        mock.start(self.c, one, NOW)
        mock.finish(self.c, one, NOW)
        other = self.q(2, trust="source")
        two = mock.build(self.c, "os", NOW, random.Random(0), n=1)
        self.assertEqual([i.question_id for i in mock.items(self.c, two)], [other])

    def test_seeded(self):
        self.topics()
        self.fill(5, 5, 5)
        first = mock.build(self.c, "os", NOW, random.Random(0), n=6)
        second = mock.build(self.c, "os", NOW, random.Random(0), n=6)
        order = lambda m: [i.question_id for i in mock.items(self.c, m)]  # noqa: E731
        self.assertEqual(order(first), order(second))

    def test_paper_mode(self):
        self.topics()
        paper = add_paper(self.c, "os", "2025 midsem", NOW, minutes=90)
        ids = [add_question(self.c, origin="paper", ref=f"1/Q{k}", prompt=f"2025 midsem Q{k}", now=NOW,
                            trust="source", topic_id=1, marks=2, paper_id=paper) for k in range(4)]
        m = mock.build(self.c, None, NOW, random.Random(0), paper_id=paper)
        self.assertEqual([i.question_id for i in mock.items(self.c, m)], ids)
        self.assertEqual((mock.get(self.c, m).title, mock.get(self.c, m).minutes), ("2025 midsem", 90))
        bare = add_paper(self.c, "os", "quiz", NOW)
        add_question(self.c, origin="paper", ref="2/Q1", prompt="quiz Q1", now=NOW, trust="source", topic_id=1,
                     marks=6, paper_id=bare)
        self.assertEqual(mock.get(self.c, mock.build(self.c, None, NOW, random.Random(0), paper_id=bare)).minutes, 9)
        empty = add_paper(self.c, "os", "empty", NOW)
        with self.assertRaisesRegex(ValueError, "^that paper has no questions yet"):
            mock.build(self.c, None, NOW, random.Random(0), paper_id=empty)

    def test_predicted(self):
        self.topics(exam=date(2026, 11, 20))
        self.fill(1)
        m = mock.build(self.c, "os", NOW, random.Random(0))
        self.assertEqual(mock.get(self.c, m).predicted, readiness(self.c, "os", NOW))
        add_topic(self.c, "x", course="db")
        add_question(self.c, origin="manual", ref="db1", prompt="p", now=NOW, trust="source", topic_id=4)
        self.assertIsNone(mock.get(self.c, mock.build(self.c, "db", NOW, random.Random(0))).predicted)


class TestTaking(MockCase):
    def setUp(self):
        super().setUp()
        self.topics()
        self.q(1, kind="number", expected={"value": 12, "tol": 0}, marks=2)
        self.q(1, kind="number", expected={"value": 12, "tol": 0}, marks=2)
        self.q(2, kind="choice", expected={"options": ["x", "y"], "correct": [2]}, marks=2)
        self.q(3, marks=5, answer="the model answer")
        self.q(3, marks=5, answer="another")
        paper = add_paper(self.c, "os", "set", NOW)
        self.c.execute("UPDATE questions SET origin='paper', paper_id=?", (paper,))
        self.c.commit()
        self.m = mock.build(self.c, None, NOW, random.Random(0), paper_id=paper)

    def take(self):
        mock.start(self.c, self.m, NOW)
        mock.save(self.c, self.m, 1, answer="12", confidence=0.8)
        mock.save(self.c, self.m, 2, answer="about 12", confidence=0.6)
        mock.save(self.c, self.m, 4, answer="a long answer")
        mock.save(self.c, self.m, 5, dont_know=True)

    def test_saving(self):
        with self.assertRaisesRegex(ValueError, "^start the test first$"):
            mock.save(self.c, self.m, 1, answer="1")
        self.assertEqual(mock.get(self.c, self.m).status, "ready")
        mock.start(self.c, self.m, NOW)
        mock.start(self.c, self.m, NOW + timedelta(hours=1))
        self.assertEqual(mock.get(self.c, self.m).started, NOW)
        self.assertEqual(mock.get(self.c, self.m).status, "running")
        mock.save(self.c, self.m, 1, answer="12", confidence=0.8)
        mock.save(self.c, self.m, 2, confidence=0.5)
        one, two = mock.items(self.c, self.m)[:2]
        self.assertEqual((one.answer, one.confidence, two.answer, two.confidence), ("12", 0.8, None, 0.5))
        mock.save(self.c, self.m, 1, dont_know=True)
        self.assertEqual((mock.items(self.c, self.m)[0].answer, mock.items(self.c, self.m)[0].dont_know), (None, True))
        with self.assertRaisesRegex(LookupError, "^no question 12 in test #1$"):
            mock.save(self.c, self.m, 12, answer="x")
        with self.assertRaisesRegex(ValueError, "^that answer is too long$"):
            mock.save(self.c, self.m, 1, answer="x" * 20_001)
        with self.assertRaisesRegex(ValueError, "^confidence must be 0-1$"):
            mock.save(self.c, self.m, 1, confidence=1.5)
        self.assertEqual(mock.in_progress(self.c), self.m)

    def test_finish_mark_result(self):
        with self.assertRaisesRegex(ValueError, "^start the test first$"):
            mock.finish(self.c, self.m, NOW)
        self.take()
        self.assertEqual(mock.finish(self.c, self.m, NOW + timedelta(minutes=27)), 1)
        self.assertEqual([i.score for i in mock.items(self.c, self.m)], [1.0, 0.0, 0.0, None, 0.0])
        self.assertEqual(mock.get(self.c, self.m).status, "to mark")
        self.assertIsNone(mock.in_progress(self.c))
        self.assertEqual(self.c.execute("SELECT count(*) FROM evidence").fetchone()[0], 0)
        self.assertEqual(mock.finish(self.c, self.m, NOW), 1)
        with self.assertRaisesRegex(ValueError, "^that test is finished$"):
            mock.save(self.c, self.m, 1, answer="1")
        with self.assertRaisesRegex(ValueError, "^pm marks that question itself$"):
            mock.mark(self.c, self.m, 1, 1, NOW)
        with self.assertRaisesRegex(ValueError, "^marks must be between 0 and 5$"):
            mock.mark(self.c, self.m, 4, 7, NOW)
        with self.assertRaisesRegex(ValueError, "^that test isn't marked yet$"):
            mock.result(self.c, self.m)
        self.assertEqual(mock.mark(self.c, self.m, 4, 3, NOW), 0)
        self.assertEqual(mock.get(self.c, self.m).status, "marked")
        rows = self.c.execute("SELECT ref, grader, facet, score, source FROM evidence ORDER BY id").fetchall()
        self.assertEqual([r["ref"] for r in rows], [f"{self.m}/{k}" for k in range(1, 6)])
        self.assertEqual([r["grader"] for r in rows], ["code", "code", "code", "self", "self"])
        self.assertEqual({r["facet"] for r in rows} | {r["source"] for r in rows}, {"application", "test"})
        self.assertAlmostEqual(rows[3]["score"], 0.6)
        with self.assertRaisesRegex(ValueError, "^that test is already marked$"):
            mock.mark(self.c, self.m, 4, 3, NOW)
        r = mock.result(self.c, self.m)
        self.assertEqual((r.got, r.total), (5.0, 16))
        self.assertEqual((sum(g for _, g, _ in r.by_topic), sum(t for _, _, t in r.by_topic)), (5.0, 16))
        self.assertEqual((r.unread, r.missed), ([2], [2, 3, 5]))
        self.assertEqual(r.over_min, 3)
        self.assertAlmostEqual(r.said, 0.7)
        again = mock.retry(self.c, self.m, NOW, random.Random(0))
        self.assertEqual(len(mock.items(self.c, again)), 3)
        self.assertTrue(mock.get(self.c, again).title.endswith(" (retry)"))

    def test_in_time_and_no_confidence(self):
        mock.start(self.c, self.m, NOW)
        mock.save(self.c, self.m, 4, answer="something")
        mock.finish(self.c, self.m, NOW + timedelta(minutes=5))
        mock.mark(self.c, self.m, 4, 5, NOW)
        r = mock.result(self.c, self.m)
        self.assertEqual((r.over_min, r.said), (0, None))

    def test_all_typed_is_marked_by_finish(self):
        self.c.execute("DELETE FROM mock_items WHERE pos > 3")
        self.c.commit()
        mock.start(self.c, self.m, NOW)
        self.assertEqual(mock.finish(self.c, self.m, NOW), 0)
        self.assertEqual(mock.get(self.c, self.m).status, "marked")
        with self.assertRaisesRegex(ValueError, "^nothing was missed in that test$"):
            self.c.execute("UPDATE mock_items SET score=1")
            mock.retry(self.c, self.m, NOW, random.Random(0))

    def test_view(self):
        mock.start(self.c, self.m, NOW)
        before = mock.view(self.c, self.m, 4)
        for key in ("key", "score", "readable", "auto"):
            self.assertNotIn(key, before)
        self.assertNotIn("the model answer", repr(before))
        self.assertEqual(mock.view(self.c, self.m, 3)["options"], ["x", "y"])
        self.take()
        mock.finish(self.c, self.m, NOW)
        after = mock.view(self.c, self.m, 4)
        self.assertEqual((after["key"], after["auto"]), ("the model answer", False))
        self.assertFalse(mock.view(self.c, self.m, 2)["readable"])
        self.assertEqual(mock.view(self.c, self.m, 1)["key"], "12")


class Version2:
    ID = "paging"
    VERSION = 2
    TITLE = "Page replacement"
    VARIANTS = ("count",)

    @staticmethod
    def draw(rng, variant):
        return "q", "number", {"value": 1, "tol": 0}, ""


class TestGenerated(MockCase):
    def setUp(self):
        super().setUp()
        from pm import practice
        self.practice = practice
        add_topic(self.c, "paging", course="os")

    def answer(self, mock_id, pos, right=True):
        from pm.generators import make
        from tests.test_practice import answer_for
        i = mock.items(self.c, mock_id)[pos - 1]
        p = make(i.gen.split("@")[0], i.seed, i.variant)
        mock.save(self.c, mock_id, pos, answer=answer_for(p) if right else "nonsense words", confidence=0.7)

    def test_only_generated(self):
        self.practice.link(self.c, 1, "paging")
        mid = mock.build(self.c, "os", NOW, random.Random(0), n=4)
        rows = mock.items(self.c, mid)
        self.assertEqual(len(rows), 4)
        for i in rows:
            self.assertEqual(i.gen, "paging@1")
            self.assertIsNotNone(i.seed)
            self.assertIsNotNone(i.variant)
            self.assertIsNone(i.question_id)

    def test_half_and_half(self):
        self.fill(10)
        self.practice.link(self.c, 1, "cpu")
        rows = mock.items(self.c, mock.build(self.c, "os", NOW, random.Random(0), n=6))
        self.assertEqual(sum(i.gen is not None for i in rows), 3)
        self.assertEqual(sum(i.question_id is not None for i in rows), 3)

    def test_generators_take_turns(self):
        self.practice.link(self.c, 1, "paging")
        self.practice.link(self.c, 1, "disk")
        rows = mock.items(self.c, mock.build(self.c, "os", NOW, random.Random(0), n=4))
        self.assertEqual({i.gen for i in rows}, {"paging@1", "disk@1"})

    def test_view_and_marking(self):
        self.practice.link(self.c, 1, "paging")
        mid = mock.build(self.c, "os", NOW, random.Random(0), n=2)
        mock.start(self.c, mid, NOW)
        before = mock.view(self.c, mid, 1)
        self.assertTrue(before["prompt"].startswith("Frames: "))
        self.assertEqual(before["trust"], "verified")
        self.assertFalse(before["void"])
        for hidden in ("key", "score", "steps"):
            self.assertNotIn(hidden, before)
        self.answer(mid, 1, right=True)
        self.answer(mid, 2, right=False)
        self.assertEqual(mock.finish(self.c, mid, NOW + timedelta(minutes=5)), 0)
        after = mock.view(self.c, mid, 1)
        self.assertIn("key", after)
        self.assertIn("Faults:", after["steps"])
        self.assertEqual([i.score for i in mock.items(self.c, mid)], [1.0, 0.0])
        self.assertEqual(mock.get(self.c, mid).status, "marked")
        rows = self.c.execute("SELECT grader FROM evidence WHERE source='test'").fetchall()
        self.assertEqual([r[0] for r in rows], ["code", "code"])
        with self.assertRaisesRegex(ValueError, "that test is already marked"):
            mock.mark(self.c, mid, 1, 1, NOW)

    def test_generated_question_is_not_marked_by_hand(self):
        self.fill(1)
        self.c.execute("UPDATE questions SET kind='open'")
        self.practice.link(self.c, 1, "paging")
        mid2 = mock.build(self.c, "os", NOW, random.Random(0), n=2)
        mock.start(self.c, mid2, NOW)
        bank_pos = next(i.pos for i in mock.items(self.c, mid2) if i.question_id)
        mock.save(self.c, mid2, bank_pos, answer="an essay")
        self.assertEqual(mock.finish(self.c, mid2, NOW), 1)
        gen_pos = next(i.pos for i in mock.items(self.c, mid2) if i.gen)
        with self.assertRaisesRegex(ValueError, "pm marks that question itself"):
            mock.mark(self.c, mid2, gen_pos, 1, NOW)

    def test_void(self):
        from pm import generators
        from pm.generators import paging
        self.addCleanup(generators.register, paging)
        self.fill(10)
        self.practice.link(self.c, 1, "paging")
        mid = mock.build(self.c, "os", NOW, random.Random(0), n=4)
        gen_pos = next(i.pos for i in mock.items(self.c, mid) if i.gen)
        mock.start(self.c, mid, NOW)
        generators.register(Version2)
        view = mock.view(self.c, mid, gen_pos)
        self.assertTrue(view["void"])
        self.assertEqual(view["prompt"], mock.VOID)
        waiting = mock.finish(self.c, mid, NOW + timedelta(minutes=5))
        for i in mock.items(self.c, mid):
            if i.question_id is not None and i.score is None:
                mock.mark(self.c, mid, i.pos, 1, NOW)
                waiting -= 1
        self.assertEqual(waiting, 0)
        self.assertEqual(mock.get(self.c, mid).status, "marked")
        void_marks = sum(i.marks for i in mock.items(self.c, mid) if i.gen)
        all_marks = sum(i.marks for i in mock.items(self.c, mid))
        self.assertEqual(mock.result(self.c, mid).total, all_marks - void_marks)
        refs = {r[0] for r in self.c.execute("SELECT ref FROM evidence WHERE source='test'")}
        self.assertNotIn(f"{mid}/{gen_pos}", refs)

    def test_retry_generated(self):
        self.practice.link(self.c, 1, "paging")
        mid = mock.build(self.c, "os", NOW, random.Random(0), n=1)
        mock.start(self.c, mid, NOW)
        self.answer(mid, 1, right=False)
        mock.finish(self.c, mid, NOW)
        old = mock.items(self.c, mid)[0]
        new = mock.items(self.c, mock.retry(self.c, mid, NOW, random.Random(1)))[0]
        self.assertEqual((new.gen, new.variant), (old.gen, old.variant))
        self.assertNotEqual(new.seed, old.seed)


class TestRetryVariants(MockCase):
    def setUp(self):
        super().setUp()
        add_topic(self.c, "a", course="os")
        self.parent = self.q(1, kind="number", expected={"value": 12, "tol": 0})
        self.m = mock.build(self.c, "os", NOW, random.Random(0), n=1)
        mock.start(self.c, self.m, NOW)
        mock.save(self.c, self.m, 1, answer="3", confidence=0.5)
        mock.finish(self.c, self.m, NOW)

    def child(self, trust):
        return self.q(1, trust=trust, kind="number", expected={"value": 5, "tol": 0}, parent_id=self.parent)

    def retried(self):
        return mock.items(self.c, mock.retry(self.c, self.m, NOW, random.Random(0)))[0].question_id

    def test_no_child_repeats(self):
        self.assertEqual(self.retried(), self.parent)

    def test_checked_child_is_used(self):
        self.child("unverified")
        checked = self.child("checked")
        self.assertEqual(self.retried(), checked)

    def test_child_seen_longest_ago(self):
        first, second = self.child("checked"), self.child("checked")
        self.c.execute("INSERT INTO mocks(course, title, minutes, created, started, finished)"
                       " VALUES('os', 'old', 10, ?, ?, ?)", (NOW.isoformat(),) * 3)
        old = self.c.execute("SELECT max(id) FROM mocks").fetchone()[0]
        self.c.execute("INSERT INTO mock_items(mock_id, pos, question_id, topic_id, marks) VALUES(?, 1, ?, 1, 1)",
                       (old, first))
        self.c.commit()
        self.assertEqual(self.retried(), second)
