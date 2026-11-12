import unittest
from datetime import datetime, timedelta

from pm.db import connect
from pm.energy import by_hour, suggest
from pm.tasks import add_task

DAY = datetime(2026, 11, 2)


class TestEnergy(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)
        add_task(self.c, "a", 60, now=DAY)
        self.day = 0

    def session(self, start: datetime, minutes: float, energy: int | None):
        end = start + timedelta(minutes=minutes)
        self.c.execute("INSERT INTO sessions(task_id, start, end, energy) VALUES(1, ?, ?, ?)",
                       (start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"), energy))
        self.c.commit()

    def hours(self, hour: int, count: int, energy: int, minutes: float = 60):
        for _ in range(count):  # one per day, so they never overlap
            self.session(DAY + timedelta(days=self.day, hours=hour), minutes, energy)
            self.day += 1

    def test_one_session_over_two_clock_hours(self):
        self.session(DAY.replace(hour=9), 90, 4)
        self.assertEqual(by_hour(self.c), {9: (4.0, 60), 10: (4.0, 30)})

    def test_the_hour_mean_is_weighted_by_minutes(self):
        self.session(DAY.replace(hour=9), 30, 2)
        self.session(DAY.replace(hour=9, minute=30), 30, 4)
        self.assertEqual(by_hour(self.c)[9], (3.0, 60))

    def test_across_midnight(self):
        self.session(DAY.replace(hour=23, minute=30), 60, 3)
        self.assertEqual(by_hour(self.c), {0: (3.0, 30), 23: (3.0, 30)})

    def test_unrated_and_long_sessions_are_left_out(self):
        self.session(DAY.replace(hour=1), 9 * 60, 5)
        self.session(DAY.replace(hour=12), 60, None)
        self.assertEqual(by_hour(self.c), {})

    def test_nine_rated_sessions_are_not_enough(self):
        self.hours(9, 9, 5)
        self.assertIsNone(suggest(self.c))

    def test_long_sessions_do_not_count_toward_the_minimum(self):
        self.hours(9, 9, 5)
        self.session(DAY + timedelta(days=40, hours=1), 9 * 60, 5)
        self.assertIsNone(suggest(self.c))

    def test_the_best_window_wins(self):
        for hour in (9, 10, 11):
            self.hours(hour, 2, 5)
        self.hours(15, 6, 2)
        self.assertEqual(suggest(self.c), "09-12")

    def test_equal_scores_go_to_the_earlier_window(self):
        self.hours(9, 6, 3)
        self.hours(15, 6, 3)
        self.assertEqual(suggest(self.c), "09-12")

    def test_equal_scores_then_more_minutes(self):
        self.hours(9, 6, 3)
        self.hours(15, 5, 3)
        self.hours(16, 3, 3)
        self.assertEqual(suggest(self.c), "15-18")

    def test_no_window_with_enough_minutes(self):
        self.hours(9, 10, 4, minutes=20)
        self.assertIsNone(suggest(self.c))
