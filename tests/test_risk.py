import random
import unittest
from datetime import datetime, timedelta

from pm.calibrate import PRIOR
from pm.db import connect
from pm.risk import TaskRisk, forecast, simulate
from pm.tasks import add_task
from tests.helpers import EXACT, TODAY, task


class TestRisk(unittest.TestCase):
    def run_sim(self, tasks, cap=240):
        return simulate(tasks, EXACT, cap, TODAY, n=200, rng=random.Random(0))

    def test_queue_start_by(self):
        risks, crunch = self.run_sim([task(2, 240, 3), task(1, 240, 1)])
        self.assertEqual([r.task_id for r in risks], [1, 2])
        self.assertEqual([r.start_by for r in risks], [TODAY + timedelta(days=1), TODAY + timedelta(days=2)])
        self.assertEqual((risks[0].p_late, crunch), (0.0, 0.0))

    def test_overloaded_today(self):
        (r,), crunch = self.run_sim([task(1, 480, 0)])
        self.assertEqual((r.p_late, r.behind, crunch), (1.0, True, 1.0))

    def test_past_due_is_behind(self):
        (r,), _ = self.run_sim([task(1, 60, -2)])
        self.assertEqual((r.p_late, r.behind), (1.0, True))

    def test_logged_time_reduces_work(self):
        (r,), _ = self.run_sim([task(1, 480, 0, logged=300)])
        self.assertEqual(r.p_late, 0.0)

    def test_undated_ignored(self):
        self.assertEqual(self.run_sim([task(1, 60, None)]), ([], 0.0))

    def test_uncertain_prior_gives_partial_risk(self):
        (r,), _ = simulate([task(1, 200, 0)], {"*": PRIOR}, 240, TODAY, n=2000, rng=random.Random(0))
        self.assertTrue(0.2 < r.p_late < 0.9)


class TestFinishDates(unittest.TestCase):
    def test_exact_work_finishes_today_and_is_never_late(self):
        (r,), _ = simulate([task(1, 240, 3)], EXACT, 240, TODAY, n=200, rng=random.Random(0))
        self.assertEqual((r.p_late, r.finish_p50, r.finish_p95, r.late_days),
                         (0.0, TODAY, TODAY, 0.0))

    def test_exact_work_due_tomorrow_finishes_in_two_days_and_is_one_day_late(self):
        (r,), _ = simulate([task(1, 720, 1)], EXACT, 240, TODAY, n=200, rng=random.Random(0))
        self.assertEqual((r.p_late, r.finish_p50), (1.0, TODAY + timedelta(days=2)))
        self.assertEqual(r.late_days, 1.0)

    def test_late_days_averages_only_the_late_runs(self):
        (r,), _ = simulate([task(1, 200, 0)], {"*": PRIOR}, 240, TODAY, n=2000,
                           rng=random.Random(0))
        self.assertEqual(r.p_late, 0.6705)
        self.assertAlmostEqual(r.late_days, 1.559, places=3)

    def test_quantiles_agree_with_start_by_and_are_ordered(self):
        tasks = [task(1, 200, 0), task(2, 300, 2), task(3, 120, 5)]
        risks, _ = simulate(tasks, {"*": PRIOR}, 240, TODAY, n=2000, rng=random.Random(0))
        by_id = {t.id: t for t in tasks}
        for r in risks:
            t = by_id[r.task_id]
            self.assertLessEqual(r.finish_p50, r.finish_p95)
            self.assertEqual((r.finish_p95 - TODAY).days, (t.due - r.start_by).days)

    def test_new_fields_keep_positional_construction_working(self):
        r = TaskRisk(1, 0.5, TODAY, False)
        self.assertEqual((r.finish_p50, r.finish_p95, r.late_days), (None, None, 0.0))


class TestTinyRemainder(unittest.TestCase):
    def test_sub_minute_remainder_still_takes_today(self):
        (r,), _ = simulate([task(1, 4, 0, logged=4)], EXACT, 240, TODAY, n=50, rng=random.Random(0))
        self.assertEqual((r.start_by, r.behind), (TODAY, False))


class TestForecast(unittest.TestCase):
    def test_seeded_forecast_is_repeatable(self):
        conn = connect(":memory:")
        now = datetime(2026, 11, 9, 10, 0)
        add_task(conn, "lab", 240, now=now, due=TODAY + timedelta(days=3))
        first = forecast(conn, now, random.Random(0))
        second = forecast(conn, now, random.Random(0))
        self.assertEqual(first[3], second[3])
        self.assertEqual(first[2], second[2])
        conn.close()
