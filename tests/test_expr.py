import unittest

from pm.expr import evaluate


class TestEvaluate(unittest.TestCase):
    def test_arithmetic(self):
        self.assertEqual(evaluate("60 / (mu - lam)", {"mu": 12, "lam": 8}), 15)
        self.assertEqual(evaluate("a // b + a % b", {"a": 7, "b": 2}), 4)
        self.assertEqual(evaluate("2 ** 10", {}), 1024)
        self.assertEqual(evaluate("max(a, 3) if a > 1 else 0", {"a": 5}), 5)
        self.assertIs(evaluate("1 < a <= 5 and not a == 4", {"a": 3}), True)
        self.assertEqual(evaluate("comb(5, 2) + factorial(4) + sqrt(16)", {}), 38)
        self.assertEqual(evaluate("-a + +2", {"a": 1}), 1)

    def test_short_circuit(self):
        self.assertIs(evaluate("b > 0 and a / b > 1", {"a": 1, "b": 0}), False)
        self.assertEqual(evaluate("0 if b == 0 else a / b", {"a": 1, "b": 0}), 0)

    def test_refused(self):
        for source in ("__import__('os')", "a.__class__", "a[0]", "'x' * 3", "lambda: 1", "[1, 2]",
                       "open('f')", "x + 1", "1 / 0", "9 ** 9 ** 9", "2 ** 65", "factorial(25)",
                       "1e16 * 10", "a = 1", "1" * 301, "", "(1).real", "(-8) ** 0.5", "comb(61, 2)",
                       "min(a=1)", "log(0)", "f'{a}'", "log(2, 1)"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                evaluate(source, {"a": 1})

    def test_names_are_checked(self):
        for names in ({"a": "x"}, {"a": 1e20}, {"a": True}):
            with self.subTest(names=names), self.assertRaises(ValueError):
                evaluate("a", names)

    def test_messages(self):
        with self.assertRaisesRegex(ValueError, "attribute access"):
            evaluate("a.__class__", {"a": 1})
        with self.assertRaisesRegex(ValueError, "unknown function 'open'|a string"):
            evaluate("open('f')", {})
        with self.assertRaisesRegex(ValueError, "unknown name 'x'"):
            evaluate("x + 1", {})
        with self.assertRaisesRegex(ValueError, "division by zero"):
            evaluate("1 / 0", {})
        with self.assertRaisesRegex(ValueError, "that power is too large"):
            evaluate("9 ** 9 ** 9", {})
        with self.assertRaisesRegex(ValueError, "that number is too large"):
            evaluate("factorial(25)", {})
        with self.assertRaisesRegex(ValueError, "too long"):
            evaluate("1" * 301, {})


if __name__ == "__main__":
    unittest.main()
