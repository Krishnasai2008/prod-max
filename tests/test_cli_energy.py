import os
from datetime import datetime, timedelta
from unittest import mock

from pm.db import connect
from tests.helpers import CliCase

DAY = datetime(2026, 10, 1)


class TestCliEnergy(CliCase):
    def sessions(self, hour, count, energy):
        conn = connect(os.environ["PM_DB"])
        try:
            for k in range(count):
                start = DAY + timedelta(days=self.day + k, hours=hour)
                conn.execute("INSERT INTO sessions(task_id, start, end, energy) VALUES(1, ?, ?, ?)",
                             (start.isoformat(), (start + timedelta(hours=1)).isoformat(), energy))
            conn.commit()
        finally:
            conn.close()
        self.day += count

    def setUp(self):
        super().setUp()
        self.day = 0
        self.assertEqual(self.pm("add", "lab", "--est", "4h")[0], 0)

    def test_stop_with_energy(self):
        self.pm("start", "1")
        code, out = self.pm("stop", "--energy", "4", now="2026-11-09T10:40:00")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[-1], "energy 4")

    def test_a_bad_energy_keeps_the_timer(self):
        self.pm("start", "1")
        with self.assertRaises(SystemExit) as caught:
            self.pm("stop", "--energy", "9", now="2026-11-09T10:40:00")
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("▶", self.pm("ls")[1])

    def test_energy_with_nothing_rated(self):
        self.assertEqual(self.pm("energy"), (0, "no rated sessions yet (pm stop --energy 1-5)\n"))

    def test_a_suggestion_and_a_match(self):
        for hour in (9, 10, 11):
            self.sessions(hour, 2, 5)
        self.sessions(15, 6, 2)
        self.assertEqual(self.pm("set", "peak", "14-17")[0], 0)
        code, out = self.pm("energy")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0], "09-10  5.0  (2h)")
        self.assertEqual(lines[-1], "suggested peak 09-12 (now 14-17): pm set peak 09-12")
        self.assertEqual(self.pm("set", "peak", "09-12")[0], 0)
        self.assertEqual(self.pm("energy")[1].splitlines()[-1], "your peak setting matches (09-12)")

    def test_too_few_ratings(self):
        self.sessions(9, 3, 4)
        self.assertEqual(self.pm("energy")[1].splitlines()[-1], "not enough ratings yet for a suggestion")
