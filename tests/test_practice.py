import random
import unittest
from datetime import date, datetime, timedelta

from pm import evidence, study
from pm.db import connect
from pm.generators import make
from pm.practice import Served, Verdict, link, linked, next_problem, submit, summary, unlink

NOW = datetime(2026, 11, 9, 10, 0)


def answer_for(p):
    e = p.expected
    if p.kind == "number":
        return f"{e['value']:g}"
    if p.kind == "token":
        return e["value"]
    if p.kind == "set":
        return ", ".join(e["value"])
    return ", ".join((e.get("accept") or [e["value"]])[0])


class PracticeCase(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.paging = study.add_topic(self.c, "paging", course="os")
        self.sched = study.add_topic(self.c, "sched", course="os")

    def submit(self, served, answer=None, at=NOW, **kw):
        p = served.problem
        args = dict(topic_id=served.topic_id, gen=p.gen, seed=p.seed, variant=p.variant,
                    answer=answer_for(p) if answer is None else answer, confidence=0.8, dont_know=False,
                    seconds=30, now=at)
        args.update(kw)
        return submit(self.c, **args)


class TestLinks(PracticeCase):
    def test_link(self):
        link(self.c, self.paging, "paging")
        self.assertEqual(linked(self.c), [(self.paging, "paging")])
        link(self.c, self.paging, "paging")
        self.assertEqual(linked(self.c), [(self.paging, "paging")])
        with self.assertRaisesRegex(LookupError, "no generator 'nope'"):
            link(self.c, self.paging, "nope")
        with self.assertRaises(LookupError):
            link(self.c, 99, "paging")
        unlink(self.c, self.paging, "paging")
        with self.assertRaisesRegex(LookupError, "paging isn't linked to that topic"):
            unlink(self.c, self.paging, "paging")


class TestNext(PracticeCase):
    def test_no_links(self):
        with self.assertRaisesRegex(ValueError, "no generators are linked to a topic yet"):
            next_problem(self.c, NOW, random.Random(0))
        with self.assertRaisesRegex(ValueError, "paging has no generators linked"):
            next_problem(self.c, NOW, random.Random(0), self.paging)

    def test_follows_rank(self):
        self.c.execute("UPDATE topics SET exam_date=? WHERE id=?", (date(2026, 11, 30).isoformat(), self.paging))
        self.c.execute("UPDATE topics SET exam_date=? WHERE id=?", (date(2026, 11, 12).isoformat(), self.sched))
        self.c.commit()
        link(self.c, self.paging, "paging")
        link(self.c, self.sched, "cpu")
        first = study.rank(self.c, NOW)[0].topic.id
        self.assertEqual(first, self.sched)
        self.assertEqual(next_problem(self.c, NOW, random.Random(0)).topic_id, first)

    def test_unranked_topic(self):
        link(self.c, self.sched, "cpu")
        self.assertEqual(next_problem(self.c, NOW, random.Random(0)).topic_id, self.sched)

    def test_oldest_generator_next(self):
        link(self.c, self.paging, "paging")
        link(self.c, self.paging, "disk")
        first = next_problem(self.c, NOW, random.Random(0))
        self.assertIn(first.problem.gen, ("paging", "disk"))
        self.submit(Served(self.paging, make("paging", 1)))
        self.assertEqual(next_problem(self.c, NOW, random.Random(2)).problem.gen, "disk")
        self.submit(Served(self.paging, make("disk", 1)), at=NOW + timedelta(minutes=5))
        self.assertEqual(next_problem(self.c, NOW, random.Random(3)).problem.gen, "paging")

    def test_seeded(self):
        link(self.c, self.paging, "paging")
        link(self.c, self.paging, "cpu")
        self.assertEqual(next_problem(self.c, NOW, random.Random(0)), next_problem(self.c, NOW, random.Random(0)))


class TestSubmit(PracticeCase):
    def test_right(self):
        verdict = self.submit(Served(self.paging, make("paging", 3)))
        self.assertIsInstance(verdict, Verdict)
        self.assertTrue(verdict.correct)
        self.assertTrue(verdict.readable)
        self.assertTrue(verdict.steps)
        rows = evidence.rows(self.c, source="practice")
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r.grader, r.facet, r.confidence), ("code", "application", 0.8))
        self.assertTrue(r.ref.startswith("paging@1/"))
        self.assertEqual(study.facets(self.c, self.paging, NOW).application.n, 1)

    def test_unreadable(self):
        verdict = self.submit(Served(self.paging, make("paging", 3, "count")), "six")
        self.assertEqual((verdict.correct, verdict.readable), (False, False))

    def test_dont_know(self):
        verdict = self.submit(Served(self.paging, make("paging", 3)), "", dont_know=True)
        self.assertFalse(verdict.correct)
        self.assertTrue(getattr(verdict, "key"))
        r = evidence.rows(self.c, source="practice")[0]
        self.assertTrue(r.dont_know)
        self.assertIsNone(r.confidence)
        self.assertFalse(r.correct)

    def test_unknown_generator(self):
        with self.assertRaisesRegex(ValueError, "no generator 'nope'"):
            submit(self.c, topic_id=self.paging, gen="nope", seed=1, variant="count", answer="1",
                   confidence=None, dont_know=False, seconds=None, now=NOW)
        with self.assertRaisesRegex(ValueError, "no variant"):
            submit(self.c, topic_id=self.paging, gen="paging", seed=1, variant="nope", answer="1",
                   confidence=None, dont_know=False, seconds=None, now=NOW)

    def test_summary(self):
        self.submit(Served(self.paging, make("paging", 3)))
        self.submit(Served(self.paging, make("paging", 4)), "nonsense", at=NOW + timedelta(minutes=1))
        self.submit(Served(self.paging, make("paging", 5)), at=NOW - timedelta(days=40))
        self.assertEqual(summary(self.c, NOW + timedelta(minutes=2)), [(self.paging, 2, 1)])


if __name__ == "__main__":
    unittest.main()
