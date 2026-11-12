import unittest
from datetime import timedelta

from pm.risk import TaskRisk
from pm.today import plan_day
from tests.helpers import EXACT, TODAY, task


class TestToday(unittest.TestCase):
    def test_urgent_first_then_fill(self):
        a, b = task(1, 120, 5), task(2, 180, 2)
        risks = {1: TaskRisk(1, 0, TODAY + timedelta(days=4), False), 2: TaskRisk(2, 0, TODAY, False)}
        plan = plan_day([a, b], risks, EXACT, 240)
        self.assertEqual([(t.id, m) for t, m in plan], [(2, 180), (1, 60)])

    def test_deep_listed_before_shallow(self):
        s, d = task(1, 60, 1), task(2, 60, 3)
        s.energy = "shallow"
        plan = plan_day([s, d], {}, EXACT, 240)
        self.assertEqual([t.id for t, _ in plan], [2, 1])

    def test_empty(self):
        self.assertEqual(plan_day([], {}, EXACT, 240), [])


class TestDeadlineFirst(unittest.TestCase):
    def test_task_due_first_is_not_starved_by_bigger_task(self):
        lab, pset = task(2, 120, 1), task(1, 270, 2)   # pset's queue start_by is earlier, lab is due first
        risks = {1: TaskRisk(1, 0.2, TODAY - timedelta(days=2), True), 2: TaskRisk(2, 0.06, TODAY - timedelta(days=1), True)}
        plan = plan_day([pset, lab], risks, EXACT, 240)
        self.assertEqual([(t.id, m) for t, m in plan], [(2, 120), (1, 120)])
