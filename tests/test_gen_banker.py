import re
import unittest

from pm import grade
from pm.generators import make
from pm.generators.banker import need, request, safe_orders


def rows(text):
    return [[int(c) for c in r] for r in text.split()]


ALLOC = rows("010 200 302 211 002")
MAX = rows("753 322 902 222 433")
AVAIL = [3, 3, 2]


def parsed(text):
    alloc_part, max_part = text.split("Max:")
    grab = lambda part: [[int(x) for x in m[1].split(" | ")]  # noqa: E731
                         for m in re.finditer(r"\| P\d \| ([\d | ]+?) \|\n", part + "\n")]
    avail = [int(x) for x in re.search(r"Available: \(([\d, ]+)\)", text)[1].split(", ")]
    return grab(alloc_part), grab(max_part.split("Available")[0]), avail


class TestSolver(unittest.TestCase):
    def test_need(self):
        self.assertEqual(need(MAX, ALLOC), rows("743 122 600 011 431"))

    def test_safe_orders(self):
        orders = safe_orders(ALLOC, need(MAX, ALLOC), AVAIL)
        self.assertIn([1, 3, 4, 2, 0], orders)
        self.assertIn([1, 3, 4, 0, 2], orders)
        self.assertFalse([o for o in orders if o[0] in (0, 2, 4)])

    def test_requests(self):
        self.assertEqual(request(ALLOC, MAX, AVAIL, 1, [1, 0, 2]), "grant")
        self.assertEqual(request(ALLOC, MAX, AVAIL, 4, [3, 3, 0]), "unsafe")
        self.assertEqual(request(ALLOC, MAX, AVAIL, 0, [0, 2, 0]), "grant")
        self.assertEqual(request(ALLOC, MAX, AVAIL, 1, [2, 0, 0]), "exceeds need")
        self.assertEqual(request(ALLOC, MAX, AVAIL, 0, [4, 0, 0]), "wait")

    def test_after_granting(self):
        alloc = rows("010 302 302 211 002")
        self.assertEqual(request(alloc, MAX, [2, 3, 0], 4, [3, 3, 0]), "wait")
        self.assertEqual(request(alloc, MAX, [2, 3, 0], 0, [0, 2, 0]), "unsafe")

    def test_deadlocked(self):
        self.assertEqual(safe_orders([[1, 0], [0, 1]], [[1, 1], [1, 1]], [0, 0]), [])


class TestDraw(unittest.TestCase):
    def test_safe_order(self):
        for seed in range(30):
            p = make("banker", seed, "safe_order")
            alloc, maximum, avail = parsed(p.text)
            orders = safe_orders(alloc, need(maximum, alloc), avail)
            self.assertEqual(p.expected["accept"], [[f"P{i}" for i in o] for o in orders])
            self.assertTrue(2 <= len(orders) <= 12)
            self.assertNotIn([0, 1, 2, 3], orders)
            for o in orders:
                self.assertTrue(grade.check("sequence", p.expected, ", ".join(f"P{i}" for i in o)))
            self.assertFalse(grade.check("sequence", p.expected, "P0 P1 P2 P3"))

    def test_request(self):
        seen = set()
        for seed in range(30):
            p = make("banker", seed, "request")
            alloc, maximum, avail = parsed(p.text)
            m = re.search(r"P(\d) requests \(([\d, ]+)\)", p.text)
            outcome = request(alloc, maximum, avail, int(m[1]), [int(x) for x in m[2].split(", ")])
            self.assertEqual(p.expected["value"], "grant" if outcome == "grant" else "deny")
            seen.add(p.expected["value"])
        self.assertEqual(seen, {"grant", "deny"})


if __name__ == "__main__":
    unittest.main()
