import sqlite3
import tempfile
import unittest
from datetime import date, datetime
from unittest import mock

from pm.db import connect
from pm.inbox import BUSY, SKIPPED, apply, done
from pm.tasks import add_task, done as finish_task, get_task

NOW = datetime(2026, 11, 10, 20)


class TestApply(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)

    def tasks(self):
        return self.c.execute("SELECT * FROM tasks ORDER BY id").fetchall()

    def acknowledged(self):
        return self.c.execute("SELECT id, error FROM inbox_applied ORDER BY rowid").fetchall()

    def last_end(self):
        row = self.c.execute("SELECT end FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
        return row["end"]

    def test_add_uses_the_entry_time_and_is_applied_once(self):
        entries = [{"id": "a1", "at": "2026-11-10T18:30:00", "op": "add",
                    "title": "OS lab 3", "est": "1h", "due": "+3"}]
        self.assertEqual(apply(self.c, entries, NOW), ["inbox: added #1 OS lab 3"])
        task = get_task(self.c, 1, NOW)
        self.assertEqual(task.est_min, 60)
        self.assertEqual(task.due, date(2026, 11, 13))
        self.assertEqual(done(self.c), [{"id": "a1"}])
        self.assertEqual(apply(self.c, entries, NOW), [])
        self.assertEqual(len(self.tasks()), 1)

    def test_add_strips_the_title_and_course(self):
        entry = {"id": "a2", "op": "add", "title": "  OS lab  ", "est": "30m",
                 "course": "  os  "}
        self.assertEqual(apply(self.c, [entry], NOW), ["inbox: added #1 OS lab"])
        task = get_task(self.c, 1, NOW)
        self.assertEqual((task.title, task.course), ("OS lab", "os"))

    def test_an_empty_course_or_due_becomes_none(self):
        entry = {"id": "a3", "op": "add", "title": "x", "est": "1h",
                 "course": "   ", "due": ""}
        apply(self.c, [entry], NOW)
        task = get_task(self.c, 1, NOW)
        self.assertIsNone(task.course)
        self.assertIsNone(task.due)

    def test_a_bad_est_is_acknowledged_with_its_error(self):
        entries = [{"id": "b1", "op": "add", "title": "x", "est": "soon"}]
        lines = apply(self.c, entries, NOW)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("inbox: add failed: bad duration"))
        self.assertEqual(self.tasks(), [])
        acked = done(self.c)
        self.assertEqual(acked[0]["id"], "b1")
        self.assertIn("bad duration", acked[0]["error"])
        self.assertEqual(apply(self.c, entries, NOW), [])

    def test_log_uses_the_entry_time_but_never_the_future(self):
        task = add_task(self.c, "t", 60, now=NOW)
        cases = [
            ("2026-11-08T18:30:00", datetime(2026, 11, 8, 18, 30)),
            ("2026-11-12T18:30:00", NOW),
            ("nonsense", NOW),
            (5, NOW),
        ]
        for i, (at, expected) in enumerate(cases):
            with self.subTest(at=at):
                entry = {"id": f"l{i}", "at": at, "op": "log", "task": task,
                         "duration": "45m"}
                self.assertEqual(apply(self.c, [entry], NOW),
                                 [f"inbox: logged 45m on #{task}"])
                self.assertEqual(self.last_end(), expected.isoformat(timespec="seconds"))

    def test_an_aware_at_is_converted_and_the_list_goes_on(self):
        task = add_task(self.c, "t", 60, now=NOW)
        expected = datetime.fromisoformat(
            "2026-11-10T13:00:00+00:00").astimezone().replace(tzinfo=None)
        entries = [
            {"id": "z1", "at": "2026-11-10T13:00:00+00:00", "op": "log",
             "task": task, "duration": "30m"},
            {"id": "z2", "at": "2026-11-10T13:00:00Z", "op": "log",
             "task": task, "duration": "30m"},
            {"id": "z3", "op": "add", "title": "after", "est": "1h"},
        ]
        self.assertEqual(apply(self.c, entries, NOW), [
            f"inbox: logged 30m on #{task}",
            f"inbox: logged 30m on #{task}",
            "inbox: added #2 after",
        ])
        ends = [row["end"] for row in self.c.execute("SELECT end FROM sessions ORDER BY id")]
        self.assertEqual(ends, [expected.isoformat(timespec="seconds")] * 2)

    def test_done_finishes_at_the_entry_time(self):
        task = add_task(self.c, "t", 60, now=NOW)
        entry = {"id": "d1", "at": "2026-11-10T18:30:00", "op": "done", "task": task}
        self.assertEqual(apply(self.c, [entry], NOW), [f"inbox: done #{task}"])
        self.assertEqual(get_task(self.c, task, NOW).done_at, datetime(2026, 11, 10, 18, 30))

    def test_done_on_a_finished_task_is_an_error_and_keeps_the_finish_time(self):
        task = add_task(self.c, "t", 60, now=NOW)
        finish_task(self.c, task, datetime(2026, 11, 9, 10))
        entry = {"id": "d2", "at": "2026-11-10T18:30:00", "op": "done", "task": task}
        lines = apply(self.c, [entry], NOW)
        self.assertEqual(lines, [f"inbox: done failed: #{task} is already done"])
        self.assertEqual(get_task(self.c, task, NOW).done_at, datetime(2026, 11, 9, 10))
        self.assertIn("already done", done(self.c)[0]["error"])

    def test_log_on_a_missing_task_is_an_error_row(self):
        lines = apply(self.c, [{"id": "l9", "op": "log", "task": 99, "duration": "1h"}], NOW)
        self.assertEqual(lines, ["inbox: log failed: no task #99"])
        self.assertEqual(done(self.c), [{"id": "l9", "error": "no task #99"}])

    def test_entries_without_a_usable_id_are_skipped_and_not_stored(self):
        entries = [
            {"id": "bad id!", "op": "add", "title": "x", "est": "1h"},
            {"op": "add", "title": "x", "est": "1h"},
            "x",
            {"id": "", "op": "add", "title": "x", "est": "1h"},
            {"id": "a" * 41, "op": "add", "title": "x", "est": "1h"},
            {"id": 5, "op": "add", "title": "x", "est": "1h"},
        ]
        self.assertEqual(apply(self.c, entries, NOW), [SKIPPED] * len(entries))
        self.assertEqual(self.acknowledged(), [])
        self.assertEqual(self.tasks(), [])

    def test_a_bad_entry_does_not_stop_the_ones_after_it(self):
        entries = [
            {"id": "bad1", "op": "add", "title": "x", "est": "soon"},
            {"id": "ok1", "op": "add", "title": "after", "est": "1h"},
        ]
        lines = apply(self.c, entries, NOW)
        self.assertTrue(lines[0].startswith("inbox: add failed: bad duration"))
        self.assertEqual(lines[1], "inbox: added #1 after")
        acked = done(self.c)
        self.assertEqual([row["id"] for row in acked], ["ok1", "bad1"])
        self.assertIn("bad duration", acked[1]["error"])

    def test_an_unknown_op_is_an_error_row(self):
        lines = apply(self.c, [{"id": "z9", "op": "format-disk"}], NOW)
        self.assertEqual(lines, ["inbox: format-disk failed: unknown op 'format-disk'"])
        self.assertEqual(done(self.c),
                         [{"id": "z9", "error": "unknown op 'format-disk'"}])

    def test_bad_types_are_error_rows_not_crashes(self):
        task = add_task(self.c, "t", 60, now=NOW)
        cases = [
            ({"op": "add", "title": 5, "est": "1h"}, "add"),
            ({"op": "add", "title": "x", "est": 60}, "add"),
            ({"op": "add", "title": "x", "est": "1h", "due": 5}, "add"),
            ({"op": "add", "title": "x", "est": "1h", "course": ["os"]}, "add"),
            ({"op": "log", "task": "3", "duration": "1h"}, "log"),
            ({"op": "log", "task": task, "duration": 60}, "log"),
            ({"op": "log", "task": True, "duration": "1h"}, "log"),
            ({"op": "done", "task": True}, "done"),
        ]
        for i, (entry, label) in enumerate(cases):
            with self.subTest(entry=entry):
                lines = apply(self.c, [{"id": f"t{i}", **entry}], NOW)
                self.assertEqual(len(lines), 1)
                self.assertTrue(lines[0].startswith(f"inbox: {label} failed:"))
        self.assertEqual(len(self.tasks()), 1)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
        self.assertEqual(len([row for row in self.acknowledged() if row["error"]]), len(cases))

    def test_titles_are_checked_after_strip(self):
        cases = ["", "   ", "x" * 201]
        for i, title in enumerate(cases):
            with self.subTest(title=title):
                lines = apply(self.c, [{"id": f"n{i}", "op": "add", "title": title,
                                        "est": "1h"}], NOW)
                self.assertEqual(lines,
                                 ["inbox: add failed: title must be 1-200 characters"])
        self.assertEqual(self.tasks(), [])

    def test_only_the_first_hundred_entries_are_looked_at(self):
        entries = [{"id": f"e{i}", "op": "add", "title": f"t{i}", "est": "1h"}
                   for i in range(150)]
        self.assertEqual(len(apply(self.c, entries, NOW)), 100)
        self.assertEqual(len(self.tasks()), 100)
        self.assertEqual(len(self.acknowledged()), 100)
        self.assertEqual(done(self.c, 2), [{"id": "e99"}, {"id": "e98"}])

    def test_a_library_failure_leaves_no_partial_change(self):
        def broken(conn, *args, **kwargs):
            conn.execute("INSERT INTO tasks(title, est_min, created)"
                         " VALUES('partial', 30, '2026-11-10T20:00:00')")
            raise ValueError("boom")

        with mock.patch("pm.inbox.add_task", side_effect=broken):
            lines = apply(self.c, [{"id": "f1", "op": "add", "title": "x", "est": "1h"}], NOW)
        self.assertEqual(lines, ["inbox: add failed: boom"])
        self.assertEqual(self.tasks(), [])
        self.assertEqual(done(self.c), [{"id": "f1", "error": "boom"}])

    def test_absurd_numbers_are_error_rows(self):
        task = add_task(self.c, "t", 60, now=NOW)
        cases = [
            ({"op": "add", "title": "x", "est": "9" * 400}, "add"),
            ({"op": "add", "title": "x", "est": "1h", "due": "+" + "9" * 400}, "add"),
            ({"op": "log", "task": 10 ** 30, "duration": "1h"}, "log"),
            ({"op": "log", "task": task, "duration": "9" * 400}, "log"),
        ]
        for i, (entry, label) in enumerate(cases):
            with self.subTest(entry=entry):
                lines = apply(self.c, [{"id": f"o{i}", **entry}], NOW)
                self.assertEqual(len(lines), 1)
                self.assertTrue(lines[0].startswith(f"inbox: {label} failed:"))
        self.assertEqual(len(self.tasks()), 1)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)

    def test_a_non_list_is_ignored(self):
        self.assertEqual(apply(self.c, None, NOW), [])
        self.assertEqual(self.acknowledged(), [])

    def test_a_huge_bad_field_gives_a_short_error(self):
        lines = apply(self.c, [{"id": "big", "op": "x" * 90_000}], NOW)
        self.assertLessEqual(len(done(self.c)[0]["error"]), 200)
        self.assertLess(len(lines[0]), 300)

    def test_a_locked_database_is_not_a_failure_and_is_retried(self):
        entries = [{"id": "a1", "op": "add", "title": "OS lab", "est": "1h"},
                   {"id": "a2", "op": "add", "title": "DB quiz", "est": "1h"}]
        with mock.patch("pm.inbox.add_task", side_effect=sqlite3.OperationalError("database is locked")):
            lines = apply(self.c, entries, NOW)
        self.assertEqual(lines, [BUSY])
        self.assertEqual(done(self.c), [])
        self.assertEqual(apply(self.c, entries, NOW), ["inbox: added #1 OS lab", "inbox: added #2 DB quiz"])


    def test_a_locked_database_on_the_first_write_is_busy_not_a_crash(self):
        with tempfile.TemporaryDirectory() as d:
            path = f"{d}/pm.db"
            conn, other = connect(path), connect(path)
            try:
                conn.execute("PRAGMA busy_timeout=0")
                other.execute("BEGIN IMMEDIATE")
                entries = [{"id": "a1", "op": "add", "title": "OS lab", "est": "1h"}]
                self.assertEqual(apply(conn, entries, NOW), [BUSY])
                other.rollback()
                self.assertEqual(apply(conn, entries, NOW), ["inbox: added #1 OS lab"])
            finally:
                conn.close()
                other.close()

    def test_a_long_course_is_an_error_row(self):
        lines = apply(self.c, [{"id": "c1", "op": "add", "title": "x", "est": "1h", "course": "c" * 81}], NOW)
        self.assertEqual(lines, ["inbox: add failed: course must be at most 80 characters"])
        self.assertEqual(self.tasks(), [])

    def test_a_date_typed_as_the_estimate_is_refused(self):
        lines = apply(self.c, [{"id": "d1", "op": "add", "title": "x", "est": "20261120"}], NOW)
        self.assertEqual(lines[0], "inbox: add failed: give a unit: 20261120m or 20261120h")
        self.assertEqual(self.tasks(), [])

    def test_an_entry_seen_again_comes_back_into_the_acknowledged_list(self):
        apply(self.c, [{"id": "old", "op": "add", "title": "x", "est": "1h"}], NOW)
        later = NOW.replace(hour=21)
        apply(self.c, [{"id": f"n{i}", "op": "done", "task": 99} for i in range(100)], later)
        self.assertNotIn({"id": "old"}, done(self.c))
        self.c.execute("DELETE FROM settings WHERE key='inbox_unpushed'")
        self.c.commit()
        self.assertEqual(apply(self.c, [{"id": "old", "op": "add", "title": "x", "est": "1h"}],
                               later.replace(minute=5)), ["inbox: acknowledged old again"])
        self.assertEqual(done(self.c)[0], {"id": "old"})
        self.assertEqual(len(self.tasks()), 1)
        self.assertEqual(self.unpushed(), "1")
        # once it is back among the newest 100, seeing it again changes nothing
        self.assertEqual(apply(self.c, [{"id": "old", "op": "add", "title": "x", "est": "1h"}],
                               later.replace(minute=10)), [])

    def unpushed(self):
        row = self.c.execute("SELECT value FROM settings WHERE key='inbox_unpushed'").fetchone()
        return row["value"] if row else None

    def test_every_applied_or_failed_entry_owes_a_push_in_the_same_commit(self):
        apply(self.c, [{"id": "a1", "op": "add", "title": "x", "est": "1h"}], NOW)
        self.assertEqual(self.unpushed(), "1")
        self.c.execute("DELETE FROM settings WHERE key='inbox_unpushed'")
        self.c.commit()
        apply(self.c, [{"id": "f1", "op": "add", "title": "x", "est": "soon"}], NOW)
        self.assertEqual(self.unpushed(), "1")
        with mock.patch("pm.inbox.add_task", side_effect=sqlite3.OperationalError("database is locked")):
            self.c.execute("DELETE FROM settings WHERE key='inbox_unpushed'")
            self.c.commit()
            self.assertEqual(apply(self.c, [{"id": "b1", "op": "add", "title": "x", "est": "1h"}], NOW), [BUSY])
        self.assertIsNone(self.unpushed())

    def test_an_ancient_entry_time_counts_as_now(self):
        apply(self.c, [{"id": "t1", "at": "0001-01-01T00:00:00", "op": "add",
                        "title": "x", "est": "1h", "due": "+1"}], NOW)
        self.assertEqual(get_task(self.c, 1, NOW).due, date(2026, 11, 11))
