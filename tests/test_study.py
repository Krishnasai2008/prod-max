import os
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

import fsrs

from pm.db import connect, set_setting
from pm.study import (SCHEDULER, Calibration, add_item, add_items, add_prereq, add_topic,
                      calibration, edit_topic, existing_locators, find_topic, gap, held,
                      mastery, new_cap, next_topic, preview, queue, rank, record_review, suspend,
                      topic_counts, utc)

NOW = datetime(2026, 11, 9, 10, 0)


class TestTopics(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")

    def test_add_find(self):
        t = add_topic(self.c, "BFS", course="algo", exam_date=date(2026, 12, 1), weight=2)
        got = find_topic(self.c, "BFS")
        self.assertEqual((got.id, got.exam_date, got.weight, got.course), (t, date(2026, 12, 1), 2.0, "algo"))

    def test_weights_must_be_positive_and_finite(self):
        for weight in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                add_topic(self.c, f"w{weight}", weight=weight)

    def test_blank_names_are_rejected_and_names_are_stripped(self):
        for blank in ("", "   ", "\t\n"):
            with self.subTest(blank=blank), \
                    self.assertRaisesRegex(ValueError, "topic name can't be blank"):
                add_topic(self.c, blank)
        topic_id = add_topic(self.c, "  BFS  ")
        self.assertEqual(find_topic(self.c, "BFS").id, topic_id)
        with self.assertRaisesRegex(ValueError, "already exists"):
            add_topic(self.c, "BFS ")

    def test_needs(self):
        g = add_topic(self.c, "Graphs", course="algo")
        add_topic(self.c, "BFS", course="algo", needs=["Graphs"])
        self.assertEqual(find_topic(self.c, "BFS").prereqs, [g])
        with self.assertRaises(LookupError):
            add_topic(self.c, "DFS", course="algo", needs=["Nope"])

    def test_ambiguous_and_duplicate(self):
        add_topic(self.c, "Intro", course="os"); add_topic(self.c, "Intro", course="algo")
        with self.assertRaises(ValueError):
            find_topic(self.c, "Intro")
        self.assertEqual(find_topic(self.c, "Intro", course="os").course, "os")
        with self.assertRaises(ValueError):
            add_topic(self.c, "Intro", course="os")

    def test_loops_rejected(self):
        a, b, c = (add_topic(self.c, n) for n in "abc")
        add_prereq(self.c, b, a); add_prereq(self.c, c, b)      # c needs b needs a
        for t, p in [(a, b), (a, c), (a, a)]:
            with self.assertRaises(ValueError):
                add_prereq(self.c, t, p)


class TestItems(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:"); self.t = add_topic(self.c, "BFS")
        self.i = add_item(self.c, self.t, Path("/n.md"), "BFS", now=NOW)

    def test_new_item_due_now(self):
        self.assertEqual([x.id for x in queue(self.c, NOW, 10**6)], [self.i])

    def test_good_review_reschedules(self):
        self.assertGreater(record_review(self.c, self.i, 3, 0.8, NOW), NOW)
        self.assertEqual(queue(self.c, NOW, 10**6), [])
        self.assertEqual(tuple(self.c.execute("SELECT recalled, confidence FROM reviews").fetchone()), (1, 0.8))

    def test_again_is_not_recalled(self):
        record_review(self.c, self.i, 1, 0.9, NOW)
        self.assertEqual(self.c.execute("SELECT recalled FROM reviews").fetchone()[0], 0)

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            record_review(self.c, self.i, 5, 0.5, NOW)
        with self.assertRaises(ValueError):
            record_review(self.c, self.i, 3, 1.5, NOW)
        with self.assertRaises(LookupError):
            record_review(self.c, 99, 3, 0.5, NOW)

    def test_mastery(self):
        self.assertEqual(mastery(self.c, add_topic(self.c, "empty"), NOW), 0.0)
        self.assertEqual(mastery(self.c, self.t, NOW), 0.0)          # never reviewed
        record_review(self.c, self.i, 3, 0.8, NOW); record_review(self.c, self.i, 3, 0.8, NOW + timedelta(minutes=10))
        self.assertTrue(0.9 < mastery(self.c, self.t, NOW + timedelta(days=1)) <= 1.0)


class TestAddItems(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)
        self.t = add_topic(self.c, "BFS")

    def test_adds_and_skips_existing_locators(self):
        path = Path("/n.md")
        self.assertEqual(add_items(self.c, self.t, path, ["TLB", "Example"], now=NOW), (2, 0))
        self.assertEqual(add_items(self.c, self.t, path, ["TLB", "Short"], now=NOW), (1, 1))
        self.assertEqual(len(queue(self.c, NOW, 10**6)), 3)

    def test_whole_file_items_are_unique_despite_a_null_locator(self):
        path = Path("/n.md")
        self.assertEqual(add_items(self.c, self.t, path, [None], now=NOW), (1, 0))
        self.assertEqual(add_items(self.c, self.t, path, [None], now=NOW), (0, 1))
        self.assertEqual(self.c.execute("SELECT count(*) FROM items").fetchone()[0], 1)

    def test_duplicate_locators_in_one_call_are_skipped(self):
        self.assertEqual(add_items(self.c, self.t, Path("/n.md"), [None, None], now=NOW), (1, 1))

    def test_existing_locators_counts_suspended_and_ignores_other_paths(self):
        path = Path("/n.md")
        add_items(self.c, self.t, path, ["TLB", None], now=NOW)
        suspended = self.c.execute("SELECT id FROM items WHERE locator='TLB'").fetchone()[0]
        suspend(self.c, suspended)
        add_items(self.c, self.t, Path("/other.md"), ["DFS"], now=NOW)
        self.assertEqual(existing_locators(self.c, path), {"TLB", None})

    def test_unknown_topic(self):
        with self.assertRaises(LookupError):
            add_items(self.c, 99, Path("/n.md"), [None], now=NOW)


class TestQueue(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)
        self.t = add_topic(self.c, "BFS")

    def new_items(self, n):
        return [add_item(self.c, self.t, Path("/n.md"), f"h{i}", now=NOW) for i in range(n)]

    def test_caps_new_items_and_counts_what_is_held(self):
        ids = self.new_items(15)
        self.assertEqual([x.id for x in queue(self.c, NOW, 10)], ids[:10])
        self.assertEqual(held(self.c, NOW, 10), 5)

    def test_reviews_today_lower_todays_allowance(self):
        ids = self.new_items(15)
        reviewed = ids[:4]
        for item in reviewed:
            record_review(self.c, item, 3, 0.5, NOW)
        got = [x.id for x in queue(self.c, NOW + timedelta(hours=1), 10)]
        self.assertEqual(got, reviewed + ids[4:10])

    def test_next_day_allows_a_fresh_batch_and_seen_items_come_first(self):
        ids = self.new_items(15)
        reviewed = ids[:4]
        for item in reviewed:
            record_review(self.c, item, 3, 0.5, NOW)
        got = [x.id for x in queue(self.c, NOW + timedelta(days=1), 10)]
        self.assertEqual(got, reviewed + ids[4:14])

    def test_seen_item_due_now_survives_an_exhausted_cap(self):
        seen = add_item(self.c, self.t, Path("/n.md"), "seen", now=NOW)
        new = add_item(self.c, self.t, Path("/n.md"), "new", now=NOW)
        record_review(self.c, seen, 3, 0.5, NOW)
        self.c.execute("UPDATE items SET due=? WHERE id=?", (utc(NOW).isoformat(), seen))
        self.c.commit()
        got = [x.id for x in queue(self.c, NOW, 1)]
        self.assertEqual(got, [seen])
        self.assertNotIn(new, got)

    def test_suspend_removes_an_item_and_can_be_undone(self):
        item = add_item(self.c, self.t, Path("/n.md"), None, now=NOW)
        suspend(self.c, item)
        self.assertEqual(queue(self.c, NOW, 10**6), [])
        self.assertEqual(queue(self.c, NOW, 10), [])
        suspend(self.c, item, False)
        self.assertEqual([x.id for x in queue(self.c, NOW, 10**6)], [item])
        with self.assertRaises(LookupError):
            suspend(self.c, 99)

    def test_mastery_ignores_suspended_items(self):
        reviewed = add_item(self.c, self.t, Path("/n.md"), "one", now=NOW)
        suspended = add_item(self.c, self.t, Path("/n.md"), "two", now=NOW)
        record_review(self.c, reviewed, 3, 0.8, NOW)
        suspend(self.c, suspended)
        later = NOW + timedelta(days=1)
        row = self.c.execute("SELECT card FROM items WHERE id=?", (reviewed,)).fetchone()
        expected = SCHEDULER.get_card_retrievability(fsrs.Card.from_json(row["card"]), utc(later))
        self.assertAlmostEqual(mastery(self.c, self.t, later), expected)

    def test_preview_matches_a_review_and_writes_nothing(self):
        item = add_item(self.c, self.t, Path("/n.md"), None, now=NOW)
        before = self.c.execute("SELECT card FROM items WHERE id=?", (item,)).fetchone()[0]
        intervals = preview(self.c, item, NOW)
        self.assertEqual(set(intervals), {1, 2, 3, 4})
        self.assertEqual(
            self.c.execute("SELECT card FROM items WHERE id=?", (item,)).fetchone()[0], before)
        self.assertLess(intervals[1], intervals[2])
        self.assertLess(intervals[2], intervals[3])
        self.assertLess(intervals[3], intervals[4])
        self.assertEqual(intervals[3], record_review(self.c, item, 3, 0.5, NOW))

    def test_new_cap_setting_with_a_fallback(self):
        self.assertEqual(new_cap(self.c), 10)
        set_setting(self.c, "new_per_day", "5")
        self.assertEqual(new_cap(self.c), 5)
        for bad in ("0", "201", "x"):
            set_setting(self.c, "new_per_day", bad)
            self.assertEqual(new_cap(self.c), 10)

    def test_gap(self):
        items = [add_item(self.c, self.t, Path("/n.md"), None, now=NOW) for _ in range(2)]
        record_review(self.c, items[0], 3, 0.9, NOW)
        record_review(self.c, items[1], 1, 0.9, NOW)
        self.assertAlmostEqual(gap(calibration(self.c)), 0.4, places=9)
        empty = connect(":memory:")
        self.addCleanup(empty.close)
        self.assertEqual(gap(calibration(empty)), 0.0)

    def test_edit_topic(self):
        topic = self.t
        got = edit_topic(self.c, topic, exam_date=date(2026, 12, 1), weight=2.0)
        self.assertEqual((got.exam_date, got.weight), (date(2026, 12, 1), 2.0))
        self.assertIsNone(edit_topic(self.c, topic, clear_exam=True).exam_date)
        with self.assertRaises(ValueError):
            edit_topic(self.c, topic)
        with self.assertRaisesRegex(ValueError, "weight must be a positive finite number"):
            edit_topic(self.c, topic, weight=0)
        with self.assertRaises(LookupError):
            edit_topic(self.c, 99, weight=2.0)

    def test_topic_counts_leave_out_suspended_and_include_empty_topics(self):
        items = [add_item(self.c, self.t, Path("/n.md"), f"h{i}", now=NOW) for i in range(3)]
        suspend(self.c, items[2])
        empty = add_topic(self.c, "empty")
        counts = topic_counts(self.c, NOW)
        self.assertEqual(counts[self.t], (2, 2))
        self.assertEqual(counts[empty], (0, 0))


class TestNext(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")

    def exam(self, days):
        return NOW.date() + timedelta(days=days)

    def test_urgency_and_exclusions(self):
        add_topic(self.c, "later", exam_date=self.exam(10)); add_topic(self.c, "soon", exam_date=self.exam(2))
        add_topic(self.c, "past", exam_date=self.exam(-1)); add_topic(self.c, "undated")
        picks = rank(self.c, NOW)
        self.assertEqual([(p.topic.name, round(p.score, 2)) for p in picks], [("soon", 0.5), ("later", 0.1)])

    def test_walks_to_weak_prereq(self):
        g = add_topic(self.c, "Graphs"); add_topic(self.c, "BFS", exam_date=self.exam(2), needs=["Graphs"])
        study, unblocks = next_topic(self.c, NOW)
        self.assertEqual((study.id, unblocks.name), (g, "BFS"))

    def test_mastered_prereq_is_skipped(self):
        g = add_topic(self.c, "Graphs"); add_topic(self.c, "BFS", exam_date=self.exam(2), needs=["Graphs"])
        i = add_item(self.c, g, Path("/n.md"), None, now=NOW)
        record_review(self.c, i, 3, 0.9, NOW); record_review(self.c, i, 3, 0.9, NOW + timedelta(minutes=10))
        study, unblocks = next_topic(self.c, NOW + timedelta(days=1))
        self.assertEqual((study.name, unblocks), ("BFS", None))

    def test_nothing_ranked(self):
        self.assertIsNone(next_topic(self.c, NOW))


class TestCalibration(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:"); t = add_topic(self.c, "x")
        self.items = [add_item(self.c, t, Path("/n.md"), None, now=NOW - timedelta(days=60)) for _ in range(3)]

    def test_empty(self):
        self.assertEqual(calibration(self.c), Calibration(0, 0.0, []))

    def test_brier_and_bins(self):
        for item, grade, conf in zip(self.items, (3, 1, 1), (0.9, 0.9, 0.1)):
            record_review(self.c, item, grade, conf, NOW)
        cal = calibration(self.c)
        self.assertEqual(cal.n, 3)
        self.assertAlmostEqual(cal.brier, (0.01 + 0.81 + 0.01) / 3)
        self.assertEqual([(lo, hi, n, round(m, 2), r) for lo, hi, n, m, r in cal.bins],
                         [(0, 20, 1, 0.1, 0.0), (80, 100, 2, 0.9, 0.5)])

    def test_since(self):
        record_review(self.c, self.items[0], 3, 0.5, NOW - timedelta(days=40))
        record_review(self.c, self.items[1], 3, 0.5, NOW)
        self.assertEqual(calibration(self.c, since=NOW - timedelta(days=30)).n, 1)


class AddItemsCards(unittest.TestCase):
    def test_each_bulk_item_gets_its_own_card(self):
        import json, tempfile
        from pathlib import Path
        from pm.db import connect
        from pm.study import add_items, add_topic
        c = connect(":memory:")
        t = add_topic(c, "paging")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "n.md"
            add_items(c, t, path, ["A", "B"], now=NOW)
        ids = [json.loads(r["card"])["card_id"] for r in c.execute("SELECT card FROM items")]
        self.assertEqual(len(set(ids)), 2)


from pm import evidence as ev  # noqa: E402
from pm.evidence import Rate  # noqa: E402
from pm.study import (blend, calibration_sources, coverage, facets, readiness,  # noqa: E402
                      refresh_files, track_file, untrack_file)

FIVE = "".join(f"# S{k}\na\nb\nc\n\n" for k in range(1, 6))


class FileCase(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)
        self.path = self.dir / "paging.md"
        self.path.write_text(FIVE)
        self.t = add_topic(self.c, "paging", course="os")

    def row(self):
        return self.c.execute("SELECT sections, mtime FROM topic_files WHERE path=?", (str(self.path),)).fetchone()


class TestCoverage(FileCase):
    def test_track_file(self):
        self.assertEqual(track_file(self.c, self.t, self.path), 5)
        self.assertEqual(tuple(self.row()), (5, self.path.stat().st_mtime))
        gone = self.dir / "gone.md"
        self.assertIsNone(track_file(self.c, self.t, gone))
        self.assertIsNone(self.c.execute("SELECT sections FROM topic_files WHERE path=?", (str(gone),)).fetchone()[0])

    def test_coverage(self):
        self.assertEqual(coverage(self.c, self.t), (0, 0))
        track_file(self.c, self.t, self.path)
        self.assertEqual(coverage(self.c, self.t), (0, 5))
        add_items(self.c, self.t, self.path, ["S1", "S2"], now=NOW)
        self.assertEqual(coverage(self.c, self.t), (2, 5))
        whole = add_item(self.c, self.t, self.path, None, now=NOW)
        self.assertEqual(coverage(self.c, self.t), (5, 5))
        suspend(self.c, whole)
        self.assertEqual(coverage(self.c, self.t), (2, 5))

    def test_missing_and_unreadable_files(self):
        gone = self.dir / "gone.md"
        add_item(self.c, self.t, gone, "A", now=NOW)
        add_item(self.c, self.t, gone, "B", now=NOW)
        self.assertEqual(coverage(self.c, self.t), (2, 2))
        other = add_topic(self.c, "tlb", course="os")
        track_file(self.c, other, self.dir / "nothing.md")
        self.assertEqual(coverage(self.c, other), (0, 1))

    def test_add_item_tracks_its_file(self):
        add_item(self.c, self.t, self.path, "S1", now=NOW)
        self.assertEqual(self.row()["sections"], 5)

    def test_refresh_files(self):
        add_items(self.c, self.t, self.path, ["S1", "S2"], now=NOW)
        self.assertEqual(refresh_files(self.c), 0)
        self.path.write_text(FIVE + "# S6\na\nb\nc\n")
        later = self.path.stat().st_mtime + 60
        os.utime(self.path, (later, later))
        self.assertEqual(refresh_files(self.c), 1)
        self.assertEqual(coverage(self.c, self.t), (2, 6))
        self.path.unlink()
        self.assertEqual(refresh_files(self.c), 0)
        self.assertEqual(coverage(self.c, self.t), (2, 6))

    def test_untrack_file(self):
        track_file(self.c, self.t, self.path)
        untrack_file(self.c, self.t, self.path)
        self.assertIsNone(self.row())
        with self.assertRaises(LookupError) as e:
            untrack_file(self.c, self.t, self.path)
        self.assertEqual(str(e.exception), "paging doesn't track that file")


class TestMastery(FileCase):
    def retrievability(self, topic):
        cards = [fsrs.Card.from_json(r[0]) for r in self.c.execute(
            "SELECT card FROM items WHERE topic_id=? AND suspended=0", (topic,))]
        return sum(SCHEDULER.get_card_retrievability(c, utc(NOW)) for c in cards) / len(cards)

    def test_blend(self):
        self.assertEqual(blend({}), 0.0)
        self.assertAlmostEqual(blend({"memory": Rate(0.9, 1.0, 5)}), 0.9)
        self.assertAlmostEqual(blend({"memory": Rate(0.9, 1.0, 5), "application": Rate(1.0, 0.2, 1)}), 0.92857, 5)
        self.assertAlmostEqual(blend({"memory": Rate(0.9, 1.0, 5), "application": Rate(0.0, 0.2, 1)}), 0.64286, 5)
        self.assertAlmostEqual(blend({"memory": Rate(0.5, 1.0, 5), "understanding": Rate(1.0, 1.0, 9),
                                      "application": Rate(0.5, 1.0, 9)}), 0.625)
        self.assertAlmostEqual(blend({"memory": None, "application": Rate(0.7, 0.4, 2)}), 0.7)

    def test_empty_topic(self):
        f = facets(self.c, self.t, NOW)
        self.assertEqual((f.memory, f.understanding, f.application, f.coverage), (None, None, None, 1.0))
        self.assertEqual(mastery(self.c, self.t, NOW), 0.0)

    def test_old_data_keeps_its_mastery(self):
        gone = self.dir / "gone.md"
        for loc, grade in (("A", 3), ("B", 1)):
            i = add_item(self.c, self.t, gone, loc, now=NOW - timedelta(days=3))
            record_review(self.c, i, grade, 0.5, NOW - timedelta(days=2))
        self.assertAlmostEqual(mastery(self.c, self.t, NOW), self.retrievability(self.t))

    def test_coverage_scales_mastery(self):
        for i in (add_item(self.c, self.t, self.path, s, now=NOW - timedelta(days=3)) for s in ("S1", "S2")):
            record_review(self.c, i, 3, 0.5, NOW - timedelta(days=2))
        self.assertAlmostEqual(mastery(self.c, self.t, NOW), 0.4 * self.retrievability(self.t))

    def test_practice_moves_mastery_gently(self):
        gone = self.dir / "gone.md"
        for k in range(5):
            i = add_item(self.c, self.t, gone, f"S{k}", now=NOW - timedelta(days=3))
            record_review(self.c, i, 3, 0.5, NOW - timedelta(days=2))
        base = mastery(self.c, self.t, NOW)
        ev.add(self.c, source="practice", ref="right", ts=NOW, grader="code", topic_id=self.t,
               correct=True, facet="application")
        self.assertGreaterEqual(mastery(self.c, self.t, NOW), base)
        self.c.execute("DELETE FROM evidence")
        ev.add(self.c, source="practice", ref="wrong", ts=NOW, grader="code", topic_id=self.t,
               correct=False, facet="application")
        lower = mastery(self.c, self.t, NOW)
        self.assertLess(lower, base)
        self.assertGreater(lower, 0)

    def test_suspended_items_leave_memory(self):
        gone = self.dir / "gone.md"
        add_item(self.c, self.t, gone, "A", now=NOW)
        suspend(self.c, add_item(self.c, self.t, gone, "B", now=NOW))
        self.assertEqual(facets(self.c, self.t, NOW).memory.n, 1)

    def test_readiness(self):
        other = add_topic(self.c, "tlb", course="os", exam_date=NOW.date() + timedelta(days=5), weight=3)
        edit_topic(self.c, self.t, exam_date=NOW.date() + timedelta(days=5))
        add_topic(self.c, "old", course="os", exam_date=NOW.date() - timedelta(days=1))
        gone = self.dir / "gone.md"
        for topic, grade in ((self.t, 3), (other, 1)):
            i = add_item(self.c, topic, gone, f"x{topic}", now=NOW - timedelta(days=3))
            record_review(self.c, i, grade, 0.5, NOW - timedelta(days=2))
        m1, m2 = mastery(self.c, self.t, NOW), mastery(self.c, other, NOW)
        self.assertAlmostEqual(readiness(self.c, "os", NOW), (m1 + 3 * m2) / 4)
        self.assertIsNone(readiness(self.c, "db", NOW))


class TestCalibrationSources(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:"); t = add_topic(self.c, "x")
        self.items = [add_item(self.c, t, Path("/n.md"), None, now=NOW - timedelta(days=60)) for _ in range(3)]
        for item, grade, conf in zip(self.items, (3, 1, 1), (0.9, 0.9, 0.1)):
            record_review(self.c, item, grade, conf, NOW)

    def add(self, ref, **kw):
        ev.add(self.c, source="practice", ref=ref, ts=NOW, topic_id=1, **{"grader": "self", **kw})

    def test_reviews_only_is_unchanged(self):
        cal = calibration(self.c)
        self.assertEqual(cal.n, 3)
        self.assertAlmostEqual(cal.brier, (0.01 + 0.81 + 0.01) / 3)
        self.assertEqual([(lo, hi, n, round(m, 2), r) for lo, hi, n, m, r in cal.bins],
                         [(0, 20, 1, 0.1, 0.0), (80, 100, 2, 0.9, 0.5)])

    def test_half_marks_and_what_is_left_out(self):
        self.add("half", score=0.5, confidence=0.9)
        cal = calibration(self.c)
        self.assertEqual(cal.n, 4)
        self.assertAlmostEqual(cal.brier * 4, 0.01 + 0.81 + 0.01 + 0.16)
        self.add("llm", correct=True, confidence=0.5, grader="llm")
        self.add("dk", dont_know=True, confidence=0.5)
        self.add("noconf", correct=True)
        self.assertEqual(calibration(self.c).n, 4)
        self.assertEqual(calibration(self.c, source="review").n, 3)
        self.assertEqual([name for name, _ in calibration_sources(self.c)], ["practice", "review"])
