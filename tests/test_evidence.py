import unittest
from datetime import datetime, timedelta
from pathlib import Path

from pm.db import connect
from pm.evidence import Rate, Row, add, misses, rate, rows, value
from pm.study import add_item, add_topic, record_review

NOW = datetime(2026, 11, 9, 10, 0)


def row(**kw) -> Row:
    base = dict(source="practice", ref="r", topic_id=1, ts=NOW, correct=None, score=None,
                confidence=None, dont_know=False, seconds=None, grader="code", facet=None, label="")
    base.update(kw)
    return Row(**base)


class TestEvidence(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)
        add_topic(self.c, "paging", course="os")
        add_item(self.c, 1, Path("/nowhere/os.md"), "TLB", now=NOW)

    def add(self, **kw):
        args = dict(source="practice", ref="g/1", ts=NOW, grader="code", topic_id=1, correct=True,
                    confidence=0.8, facet="application", label="x")
        args.update(kw)
        return add(self.c, **args)

    def test_add_is_idempotent(self):
        self.assertTrue(self.add())
        self.assertFalse(self.add())
        self.assertEqual(self.c.execute("SELECT count(*) FROM evidence").fetchone()[0], 1)

    def test_add_refuses_bad_values(self):
        cases = [(dict(source="review"), "unknown evidence source 'review'"),
                 (dict(grader="me"), "grader must be code, self or llm"),
                 (dict(facet="luck"), "facet must be memory, understanding or application"),
                 (dict(score=1.5), "score must be 0-1"),
                 (dict(confidence=-0.1), "confidence must be 0-1"),
                 (dict(seconds=-1), "seconds can't be negative"),
                 (dict(ref=""), "evidence needs a ref")]
        for kw, message in cases:
            with self.subTest(kw=kw), self.assertRaises(ValueError) as e:
                self.add(**kw)
            self.assertEqual(str(e.exception), message)
        with self.assertRaises(LookupError) as e:
            self.add(topic_id=99)
        self.assertEqual(str(e.exception), "no topic #99")

    def test_label_is_cut(self):
        self.add(label="a" * 300)
        self.assertEqual(len(rows(self.c, source="practice")[0].label), 200)

    def test_reviews_come_through_the_view(self):
        record_review(self.c, 1, 3, 0.7, NOW)
        [r] = rows(self.c)
        self.assertEqual((r.source, r.facet, r.grader, r.correct, r.confidence, r.topic_id),
                         ("review", "memory", "self", True, 0.7, 1))
        self.assertEqual(r.label, "/nowhere/os.md#TLB")

    def test_answered_spots_come_through_the_view(self):
        insert = ("INSERT INTO spots(item_id, original, mutated, line, created, answered, picked, confidence)"
                  " VALUES(1, 'a', 'b', 3, ?, ?, ?, ?)")
        self.c.execute(insert, (NOW.isoformat(), NOW.isoformat(), 2, 0.9))
        self.c.execute(insert, (NOW.isoformat(), None, None, None))
        [r] = rows(self.c)
        self.assertEqual((r.source, r.correct, r.facet, r.grader), ("spot", False, "understanding", "code"))

    def test_filters(self):
        record_review(self.c, 1, 3, 0.7, NOW)
        self.add()
        self.add(ref="g/2", topic_id=None, facet="understanding")
        self.assertEqual([r.ref for r in rows(self.c, facet="application")], ["g/1"])
        self.assertEqual([r.source for r in rows(self.c, source="review")], ["review"])
        self.assertEqual({r.ref for r in rows(self.c, topic_id=1)}, {"1", "g/1"})

    def test_value(self):
        self.assertEqual(value(row(score=0.5)), 0.5)
        self.assertEqual(value(row(correct=True)), 1.0)
        self.assertEqual(value(row(dont_know=True)), 0.0)
        self.assertIsNone(value(row()))

    def test_rate(self):
        self.assertIsNone(rate([], NOW))
        self.assertEqual(rate([row(correct=True)], NOW), Rate(1.0, 0.2, 1))
        r = rate([row(correct=True), row(correct=False, ts=NOW - timedelta(days=30))], NOW)
        self.assertAlmostEqual(r.value, 2 / 3)
        self.assertAlmostEqual(r.strength, 0.3)
        self.assertEqual(r.n, 2)
        self.assertEqual(rate([row(correct=True, ts=NOW + timedelta(days=10))], NOW), Rate(1.0, 0.2, 1))
        self.assertEqual(rate([row(correct=True), row()], NOW), Rate(1.0, 0.2, 1))
        self.assertEqual(rate([row(correct=True)] * 6, NOW).strength, 1.0)

    def test_misses(self):
        record_review(self.c, 1, 1, 0.9, NOW - timedelta(days=2))  # confident and wrong
        record_review(self.c, 1, 1, 0.5, NOW - timedelta(days=1))  # wrong, not confident
        record_review(self.c, 1, 3, 0.9, NOW)                      # confident and right
        self.add(ref="half", correct=None, score=0.25, confidence=0.8, ts=NOW - timedelta(hours=1))
        found = misses(self.c)
        self.assertEqual([(r.source, r.ref) for r in found], [("practice", "half"), ("review", "1")])
        self.assertEqual(len(misses(self.c, limit=1)), 1)


class TestShortLabel(unittest.TestCase):
    def test_paths_lose_their_folders(self):
        from pm.evidence import short_label
        self.assertEqual(short_label("/home/me/os/notes.md#TLB"), "notes.md#TLB")
        self.assertEqual(short_label("~/os/notes.md"), "notes.md")
        self.assertEqual(short_label("What is a/b testing?"), "What is a/b testing?")
        self.assertEqual(short_label("/a/b.md#x/y"), "b.md#x/y")


if __name__ == "__main__":
    unittest.main()
