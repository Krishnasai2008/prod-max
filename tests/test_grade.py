import unittest
from fractions import Fraction

from pm.grade import check, clean, number, parse_expected, readable, show, tokens


class TestReading(unittest.TestCase):
    def test_clean_and_tokens(self):
        self.assertEqual(clean("  P2 →  P1 . "), "P2 → P1")
        self.assertEqual(tokens("P2, P1 -> p3;"), ["p2", "p1", "p3"])
        self.assertEqual(tokens(""), [])

    def test_number(self):
        self.assertEqual(number("6.25 ms"), Fraction(25, 4))
        self.assertEqual(number("6,250"), 6250)
        self.assertEqual(number("25/4"), Fraction(25, 4))
        self.assertEqual(number("−3"), -3)
        self.assertEqual(number("40%"), 40)
        self.assertEqual(number("12 m/s^2"), 12)
        for bad in ("about 6", "6,25", "1/0", "", "__import__('os')", "5 - 3", "1e9"):
            with self.subTest(bad=bad), self.assertRaises(ValueError) as e:
                number(bad)
            self.assertEqual(str(e.exception), f"couldn't read {bad!r} as a number")


class TestCheck(unittest.TestCase):
    def test_number(self):
        key = {"value": 6.25, "tol": 0.01}
        self.assertTrue(check("number", key, "6.26"))
        self.assertFalse(check("number", key, "6.27"))
        self.assertFalse(check("number", key, "six"))
        self.assertFalse(readable("number", key, "six"))
        self.assertTrue(readable("number", key, "6.27"))
        self.assertTrue(check("number", {"value": 17, "tol": 0}, "17.0"))

    def test_token(self):
        self.assertTrue(check("token", {"value": "LRU"}, " lru. "))
        self.assertFalse(check("token", {"value": "LRU"}, "FIFO"))
        self.assertFalse(check("token", {"value": "LRU"}, ""))

    def test_sequence(self):
        key = {"value": ["P2", "P1", "P3"]}
        self.assertTrue(check("sequence", key, "p2 → p1 → p3"))
        self.assertFalse(check("sequence", key, "P1 P2 P3"))
        two = {"accept": [["P1", "P3"], ["P3", "P1"]]}
        self.assertTrue(check("sequence", two, "P1 P3"))
        self.assertTrue(check("sequence", two, "P3, P1"))
        self.assertFalse(check("sequence", two, "P1"))

    def test_set(self):
        key = {"value": ["A", "C"]}
        self.assertTrue(check("set", key, "c, a"))
        self.assertFalse(check("set", key, "a"))
        self.assertFalse(check("set", key, "a c c"))

    def test_choice(self):
        key = {"options": ["x", "y", "z"], "correct": [2]}
        self.assertTrue(check("choice", key, "b"))
        self.assertTrue(check("choice", key, "2"))
        self.assertFalse(check("choice", key, "1,2"))
        self.assertFalse(check("choice", key, "q"))
        self.assertFalse(readable("choice", key, "q"))
        two = {"options": ["x", "y", "z"], "correct": [1, 3]}
        self.assertTrue(check("choice", two, "a c"))
        self.assertTrue(check("choice", two, "3,1"))

    def test_odd_input_is_wrong_not_an_error(self):
        for kind, key in (("number", {"value": 1, "tol": 0}), ("token", {"value": "x"}),
                          ("set", {"value": ["x"]}), ("choice", {"options": ["a", "b"], "correct": [1]})):
            self.assertFalse(check(kind, key, None))
            self.assertFalse(check(kind, key, "\x00 ;; →"))


class TestKeys(unittest.TestCase):
    def test_parse_expected(self):
        for kind, raw, message in [
            ("number", {"value": "6"}, "a number answer needs a value"),
            ("number", {"value": 6, "tol": -1}, "a number answer's tol must be 0 or more"),
            ("choice", {"options": ["a"], "correct": [1]}, "a choice answer needs 2-8 options"),
            ("choice", {"options": ["a", "b"], "correct": [3]}, "correct must name options 1-2"),
            ("essay", {}, "unknown answer kind 'essay'"),
            ("set", {"value": []}, "a set answer needs a value"),
            ("sequence", {"accept": [["a"], []]}, "a sequence answer needs a value"),
        ]:
            with self.subTest(kind=kind, raw=raw), self.assertRaises(ValueError) as e:
                parse_expected(kind, raw)
            self.assertEqual(str(e.exception), message)
        self.assertEqual(parse_expected("number", {"value": 12}), {"value": 12, "tol": 0})
        self.assertEqual(parse_expected("choice", {"options": ["a", "b"], "correct": [2, 2]}),
                         {"options": ["a", "b"], "correct": [2]})

    def test_show(self):
        self.assertEqual(show("number", {"value": 6.25, "tol": 0.01}), "6.25 (±0.01)")
        self.assertEqual(show("number", {"value": 6, "tol": 0}), "6")
        self.assertEqual(show("choice", {"options": ["x", "y"], "correct": [2]}), "B: y")
        self.assertTrue(show("sequence", {"accept": [["P1", "P3"], ["P3", "P1"]]})
                        .endswith("(one of 2 accepted orders)"))
        self.assertEqual(show("set", {"value": ["A", "C"]}), "{A, C}")
