import re
import unittest

from pm.generators import make
from pm.generators.paging import run

BOOK = [int(x) for x in "7 0 1 2 0 3 0 4 2 3 0 3 2 1 2 0 1 7 0 1".split()]
BELADY = [int(x) for x in "1 2 3 4 1 2 5 1 2 3 4 5".split()]


def parsed(text):
    m = re.search(r"Frames: (\d+)\. Reference string: ([\d ]+)", text)
    return int(m[1]), [int(x) for x in m[2].split()]


def policy_of(text):
    return re.search(r"under (FIFO|LRU|OPT)", text)[1].lower()


class TestRun(unittest.TestCase):
    def test_textbook(self):
        self.assertEqual(run(BOOK, 3, "fifo")[0], 15)
        self.assertEqual(run(BOOK, 3, "lru")[0], 12)
        self.assertEqual(run(BOOK, 3, "opt")[0], 9)
        self.assertEqual(set(run(BOOK, 3, "lru")[1]), {0, 1, 7})

    def test_belady(self):
        self.assertEqual(run(BELADY, 3, "fifo")[0], 9)
        self.assertEqual(run(BELADY, 4, "fifo")[0], 10)

    def test_one_frame(self):
        for policy in ("fifo", "lru", "opt"):
            self.assertEqual(run([1, 1, 2, 1], 1, policy)[0], 3)

    def test_unknown_policy(self):
        with self.assertRaises(ValueError):
            run(BOOK, 3, "clock")


class TestDraw(unittest.TestCase):
    def test_keys_match_the_solver(self):
        for seed in range(50):
            for variant in ("count", "final"):
                p = make("paging", seed, variant)
                frames, refs = parsed(p.text)
                faults, final, _ = run(refs, frames, policy_of(p.text))
                if variant == "count":
                    self.assertEqual(p.expected["value"], faults)
                else:
                    self.assertEqual(sorted(p.expected["value"]), sorted(str(x) for x in final))
                self.assertIn("first load of each page counts as a fault", p.text)
                self.assertIn("Faults:", p.steps)

    def test_fewest(self):
        for seed in range(50):
            p = make("paging", seed, "fewest")
            frames, refs = parsed(p.text)
            fifo, lru = run(refs, frames, "fifo")[0], run(refs, frames, "lru")[0]
            self.assertEqual(p.expected["value"], "FIFO" if fifo < lru else "LRU")
            self.assertIn("Faults:", p.steps)


if __name__ == "__main__":
    unittest.main()
