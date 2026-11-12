import unittest
from datetime import date, timedelta

from pm.units import fmt_duration, parse_due, parse_duration


class TestUnits(unittest.TestCase):
    def test_parse_duration(self):
        for s, m in [("90m", 90), ("4h", 240), ("1h30m", 90), ("2.5h", 150)]:
            self.assertEqual(parse_duration(s), m)

    def test_parse_duration_rejects(self):
        for s in ["4", "2.5", "", "0m", "-1h", "abc", "3x", "20261120", "1001h", "9" * 400]:
            with self.assertRaises(ValueError):
                parse_duration(s)

    def test_fmt_duration(self):
        self.assertEqual([fmt_duration(m) for m in (45, 240, 90, 0)], ["45m", "4h", "1h30m", "0m"])

    def test_parse_due(self):
        today = date(2026, 11, 9)
        self.assertEqual(parse_due("2026-11-20", today), date(2026, 11, 20))
        self.assertEqual(parse_due("+3", today), date(2026, 11, 12))
        for word, day in [("fri", 13), ("Friday", 13), ("mon", 16), ("tue", 10), ("today", 9), ("tomorrow", 10)]:
            self.assertEqual(parse_due(word, today), date(2026, 11, day), word)  # the 9th is a Monday
        for bad in ["someday", "fr", "t"]:
            with self.assertRaises(ValueError):
                parse_due(bad, today)
        for far in ["0001-01-01", "9999-12-31", "+3661", "+" + "9" * 400]:
            with self.subTest(due=far), self.assertRaises(ValueError):
                parse_due(far, today)
        self.assertEqual(parse_due("+3660", today), today + timedelta(days=3660))
