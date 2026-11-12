import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta

from pm.db import connect
from pm.tasks import (add_task, done, drop_task, edit_task, finished_ratios, finished_tasks,
                      get_task, last_note, log_time, open_tasks, running_session, running_task_id,
                      rate_session, start, stop, unrated, worked_min, worked_on)

NOW = datetime(2026, 11, 9, 10, 0)


class TestTasks(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")

    def tearDown(self):
        self.c.close()

    def test_add_task_rejects_unknown_energy(self):
        with self.assertRaisesRegex(ValueError, "energy must be deep or shallow"):
            add_task(self.c, "a", 60, now=NOW, energy="medium")
        self.assertEqual(open_tasks(self.c, NOW), [])

    def test_start_stop_logs_minutes_and_note(self):
        t = add_task(self.c, "lab", 240, now=NOW)
        start(self.c, t, NOW)
        task, mins = stop(self.c, NOW + timedelta(minutes=45), note="halfway Q2")
        self.assertEqual((task.id, mins, task.logged_min), (t, 45, 45))
        self.assertEqual(last_note(self.c, t), "halfway Q2")

    def test_start_switches_running_task(self):
        a, b = add_task(self.c, "a", 60, now=NOW), add_task(self.c, "b", 60, now=NOW)
        start(self.c, a, NOW)
        start(self.c, b, NOW + timedelta(minutes=20))
        self.assertEqual(get_task(self.c, a, NOW + timedelta(minutes=30)).logged_min, 20)
        self.assertTrue(get_task(self.c, b, NOW + timedelta(minutes=30)).running)

    def test_stop_nothing_running(self):
        self.assertIsNone(stop(self.c, NOW))

    def test_stop_override_minutes(self):  # forgotten overnight timer
        t = add_task(self.c, "a", 60, now=NOW)
        start(self.c, t, NOW)
        _, mins = stop(self.c, NOW + timedelta(hours=14), minutes=120)
        self.assertEqual((mins, get_task(self.c, t, NOW).logged_min), (120, 120))

    def test_start_done_task_errors(self):
        t = add_task(self.c, "a", 60, now=NOW)
        done(self.c, t, NOW)
        with self.assertRaises(ValueError):
            start(self.c, t, NOW)
        with self.assertRaises(LookupError):
            start(self.c, 99, NOW)

    def test_start_dropped_task_errors(self):
        t = add_task(self.c, "a", 60, now=NOW)
        drop_task(self.c, t, NOW)
        with self.assertRaisesRegex(ValueError, "#1 is already done"):
            start(self.c, t, NOW)
        self.assertIsNone(running_task_id(self.c))

    def test_log_time_and_done_refuse_a_finished_task(self):
        t = add_task(self.c, "a", 60, now=NOW)
        log_time(self.c, t, 10, NOW)
        done(self.c, t, NOW)
        with self.assertRaisesRegex(ValueError, "#1 is already done"):
            log_time(self.c, t, 30, NOW)
        with self.assertRaisesRegex(ValueError, "#1 is already done"):
            done(self.c, t, NOW + timedelta(minutes=1))
        finished = get_task(self.c, t, NOW)
        self.assertEqual(finished.logged_min, 10)
        self.assertEqual(finished.done_at, NOW)

    def test_log_time_and_done_refuse_a_dropped_task(self):
        t = add_task(self.c, "a", 60, now=NOW)
        drop_task(self.c, t, NOW)
        with self.assertRaisesRegex(ValueError, "#1 is already done"):
            log_time(self.c, t, 30, NOW)
        with self.assertRaisesRegex(ValueError, "#1 is already done"):
            done(self.c, t, NOW)
        dropped = get_task(self.c, t, NOW)
        self.assertEqual(dropped.logged_min, 0)
        self.assertEqual(dropped.done_at, NOW)

    def test_done_closes_session_and_ratio(self):
        t = add_task(self.c, "a", 60, now=NOW, kind="lab")
        start(self.c, t, NOW)
        done(self.c, t, NOW + timedelta(minutes=90))
        self.assertEqual(open_tasks(self.c, NOW), [])
        self.assertEqual(finished_ratios(self.c), [("lab", 1.5)])

    def test_log_time_and_running_counts(self):
        t = add_task(self.c, "a", 60, now=NOW)
        log_time(self.c, t, 30, NOW)
        start(self.c, t, NOW)
        self.assertEqual(open_tasks(self.c, NOW + timedelta(minutes=10))[0].logged_min, 40)

    def test_finished_tasks_order_and_ratios(self):
        a = add_task(self.c, "a", 60, now=NOW, kind="lab")
        b = add_task(self.c, "b", 120, now=NOW, kind="lab")
        log_time(self.c, a, 30, NOW)
        log_time(self.c, b, 180, NOW)
        done(self.c, b, NOW + timedelta(hours=1))
        done(self.c, a, NOW + timedelta(hours=2))
        self.assertEqual([t.id for t in finished_tasks(self.c)], [b, a])
        self.assertEqual(finished_ratios(self.c), [("lab", 1.5), ("lab", 0.5)])

    def test_running_task_id(self):
        self.assertIsNone(running_task_id(self.c))
        t = add_task(self.c, "a", 60, now=NOW)
        start(self.c, t, NOW)
        self.assertEqual(running_task_id(self.c), t)
        stop(self.c, NOW + timedelta(minutes=10))
        self.assertIsNone(running_task_id(self.c))

    def test_running_session_returns_task_and_start(self):
        self.assertIsNone(running_session(self.c))
        t = add_task(self.c, "a", 60, now=NOW)
        start(self.c, t, NOW)
        self.assertEqual(running_session(self.c), (t, NOW))
        stop(self.c, NOW + timedelta(minutes=10))
        self.assertIsNone(running_session(self.c))

    def test_worked_on(self):
        t = add_task(self.c, "a", 60, now=NOW)
        start(self.c, t, NOW + timedelta(days=2))
        stop(self.c, NOW + timedelta(days=2, minutes=30))
        self.assertTrue(worked_on(self.c, t, NOW.date() + timedelta(days=2)))
        self.assertFalse(worked_on(self.c, t, NOW.date() + timedelta(days=3)))
        self.assertFalse(worked_on(self.c, t, NOW.date()))

    def test_worked_on_counts_an_overnight_session(self):
        t = add_task(self.c, "a", 60, now=NOW)
        start(self.c, t, datetime(2026, 11, 8, 23, 30))
        stop(self.c, datetime(2026, 11, 9, 0, 30))
        self.assertTrue(worked_on(self.c, t, NOW.date() - timedelta(days=1)))
        self.assertTrue(worked_on(self.c, t, NOW.date()))
        self.assertFalse(worked_on(self.c, t, NOW.date() + timedelta(days=1)))


class TestStartRace(unittest.TestCase):
    def test_concurrent_starts_leave_exactly_one_open_session(self):
        with tempfile.TemporaryDirectory() as d:
            path = f"{d}/pm.db"
            c = connect(path)
            try:
                a = add_task(c, "a", 60, now=NOW)
                b = add_task(c, "b", 60, now=NOW)
                barrier = threading.Barrier(2)
                errors = []

                def run(task_id):
                    conn = connect(path)
                    try:
                        barrier.wait()
                        for _ in range(25):
                            start(conn, task_id, NOW)
                    except Exception as e:
                        errors.append(e)
                    finally:
                        conn.close()

                threads = [threading.Thread(target=run, args=(task,)) for task in (a, b)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                self.assertEqual(errors, [])
                row = c.execute("SELECT count(*) AS n FROM sessions WHERE end IS NULL").fetchone()
                self.assertEqual(row["n"], 1)
            finally:
                c.close()


class TestEditTask(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")

    def tearDown(self):
        self.c.close()

    def test_edit_changes_given_fields_and_leaves_the_rest(self):
        t = add_task(self.c, "old", 60, now=NOW, course="os", kind="lab", first_step="open it")
        task = edit_task(self.c, t, NOW, title="new", due=date(2026, 11, 12))
        self.assertEqual((task.title, task.due), ("new", date(2026, 11, 12)))
        self.assertEqual((task.course, task.kind, task.first_step), ("os", "lab", "open it"))

    def test_edit_clear_due(self):
        t = add_task(self.c, "a", 60, now=NOW, due=date(2026, 11, 12))
        self.assertIsNone(edit_task(self.c, t, NOW, clear=("due",)).due)

    def test_edit_estimate_is_locked_once_time_is_logged(self):
        t = add_task(self.c, "a", 60, now=NOW)
        self.assertEqual(edit_task(self.c, t, NOW, est_min=90).est_min, 90)
        log_time(self.c, t, 30, NOW)
        with self.assertRaisesRegex(ValueError, "locked"):
            edit_task(self.c, t, NOW, est_min=120)
        task = edit_task(self.c, t, NOW, est_min=90, title="x")
        self.assertEqual((task.est_min, task.title), (90, "x"))

    def test_edit_rejects_a_non_positive_estimate(self):
        t = add_task(self.c, "a", 60, now=NOW)
        with self.assertRaisesRegex(ValueError, "estimate must be positive"):
            edit_task(self.c, t, NOW, est_min=0)
        with self.assertRaisesRegex(ValueError, "estimate must be positive"):
            edit_task(self.c, t, NOW, est_min=-5)
        self.assertEqual(get_task(self.c, t, NOW).est_min, 60)

    def test_edit_rejects_a_blank_kind(self):
        t = add_task(self.c, "a", 60, now=NOW)
        with self.assertRaisesRegex(ValueError, "kind can't be empty"):
            edit_task(self.c, t, NOW, kind="  ")
        with self.assertRaisesRegex(ValueError, "kind can't be empty"):
            edit_task(self.c, t, NOW, kind="")
        self.assertEqual(get_task(self.c, t, NOW).kind, "task")

    def test_edit_errors(self):
        t = add_task(self.c, "a", 60, now=NOW)
        with self.assertRaisesRegex(LookupError, "no task #7"):
            edit_task(self.c, 7, NOW, title="x")

        done(self.c, t, NOW)
        with self.assertRaisesRegex(ValueError, "#1 is already done"):
            edit_task(self.c, t, NOW, title="  ")

        t2 = add_task(self.c, "b", 60, now=NOW)
        with self.assertRaisesRegex(ValueError, "title can't be empty"):
            edit_task(self.c, t2, NOW, title="   ", energy="medium")
        with self.assertRaisesRegex(ValueError, "energy must be deep or shallow"):
            edit_task(self.c, t2, NOW, energy="medium")

        log_time(self.c, t2, 10, NOW)
        with self.assertRaisesRegex(ValueError, "the estimate is locked once time is logged"):
            edit_task(self.c, t2, NOW, est_min=90, clear=("kind",))
        with self.assertRaisesRegex(ValueError, "can't clear 'kind'"):
            edit_task(self.c, t2, NOW, clear=("kind",))
        with self.assertRaisesRegex(ValueError, "nothing to change"):
            edit_task(self.c, t2, NOW)

    def test_drop_ends_a_running_session(self):
        t = add_task(self.c, "a", 60, now=NOW)
        start(self.c, t, NOW)
        task = drop_task(self.c, t, NOW + timedelta(minutes=25))
        self.assertFalse(task.running)
        self.assertEqual(task.done_at, NOW + timedelta(minutes=25))
        self.assertTrue(task.dropped)
        self.assertEqual(task.logged_min, 25)
        self.assertEqual(open_tasks(self.c, NOW + timedelta(minutes=25)), [])
        row = self.c.execute("SELECT end FROM sessions WHERE task_id=?", (t,)).fetchone()
        self.assertEqual(row["end"], "2026-11-09T10:25:00")

    def test_drop_errors(self):
        with self.assertRaisesRegex(LookupError, "no task #7"):
            drop_task(self.c, 7, NOW)
        t = add_task(self.c, "a", 60, now=NOW)
        drop_task(self.c, t, NOW)
        with self.assertRaisesRegex(ValueError, "#1 is already done"):
            drop_task(self.c, t, NOW)
        t2 = add_task(self.c, "b", 60, now=NOW)
        done(self.c, t2, NOW)
        with self.assertRaisesRegex(ValueError, "#2 is already done"):
            drop_task(self.c, t2, NOW)

    def test_dropped_task_is_not_finished(self):
        t = add_task(self.c, "a", 60, now=NOW)
        log_time(self.c, t, 60, NOW)
        drop_task(self.c, t, NOW)
        self.assertEqual(finished_tasks(self.c), [])
        self.assertEqual(finished_ratios(self.c), [])

    def test_worked_min_counts_sessions_that_start_on_the_day(self):
        t = add_task(self.c, "a", 60, now=NOW)
        log_time(self.c, t, 45, datetime(2026, 11, 9, 9, 45))
        log_time(self.c, t, 30, datetime(2026, 11, 8, 12, 0))
        start(self.c, t, datetime(2026, 11, 9, 9, 50))
        self.assertEqual(worked_min(self.c, date(2026, 11, 9), NOW), 55)
        self.assertEqual(worked_min(self.c, date(2026, 11, 8), NOW), 30)


class TestStopOverride(unittest.TestCase):
    def test_override_longer_than_elapsed_is_rejected(self):
        c = connect(":memory:")
        self.addCleanup(c.close)
        t = add_task(c, "a", 60, now=NOW)
        start(c, t, NOW)
        with self.assertRaises(ValueError):
            stop(c, NOW + timedelta(minutes=30), minutes=120)
        self.assertTrue(get_task(c, t, NOW + timedelta(minutes=30)).running)  # session left open


class TestEnergyRating(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)
        add_task(self.c, "a", 60, now=NOW)
        start(self.c, 1, NOW)

    def energy(self):
        return self.c.execute("SELECT energy FROM sessions ORDER BY id DESC").fetchone()[0]

    def test_stop_stores_the_energy(self):
        stop(self.c, NOW + timedelta(minutes=40), energy=4)
        self.assertEqual(self.energy(), 4)
        self.assertFalse(unrated(self.c, NOW + timedelta(minutes=41)))

    def test_a_bad_energy_writes_nothing_and_keeps_the_timer(self):
        for bad in (6, 0, True, "4"):
            with self.subTest(energy=bad), self.assertRaisesRegex(ValueError, "^energy must be 1-5$"):
                stop(self.c, NOW + timedelta(minutes=40), energy=bad)
        self.assertEqual(running_task_id(self.c), 1)

    def test_rate_after_a_plain_stop(self):
        stop(self.c, NOW + timedelta(minutes=40))
        later = NOW + timedelta(minutes=50)
        self.assertTrue(unrated(self.c, later))
        with self.assertRaisesRegex(ValueError, "^energy must be 1-5$"):
            rate_session(self.c, 9, later)
        rate_session(self.c, 3, later)
        self.assertEqual(self.energy(), 3)
        with self.assertRaisesRegex(ValueError, "^nothing to rate$"):
            rate_session(self.c, 3, later)

    def test_the_window_closes_after_30_minutes(self):
        stop(self.c, NOW + timedelta(minutes=40))
        self.assertTrue(unrated(self.c, NOW + timedelta(minutes=70)))
        self.assertFalse(unrated(self.c, NOW + timedelta(minutes=71)))
        with self.assertRaisesRegex(ValueError, "^nothing to rate$"):
            rate_session(self.c, 3, NOW + timedelta(minutes=71))

    def test_nothing_ended_means_nothing_to_rate(self):
        self.assertFalse(unrated(self.c, NOW))
