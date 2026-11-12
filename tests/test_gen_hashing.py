import re
import unittest

from pm import grade
from pm.generators import make
from pm.generators.hashing import insert_all


class TestInsert(unittest.TestCase):
    def test_linear(self):
        keys = [10, 22, 31, 4, 15, 28, 17, 88, 59]
        self.assertEqual(insert_all(keys, 11, "linear"), ([22, 88, None, None, 4, 15, 28, 17, 59, 31, 10], 16))

    def test_quadratic(self):
        table, probes = insert_all([10, 3, 17, 24], 7, "quadratic")
        self.assertEqual((table[3], table[4], table[0], table[5]), (10, 3, 17, 24))
        self.assertEqual(probes, 10)

    def test_full(self):
        with self.assertRaisesRegex(ValueError, "no free slot for 24"):
            insert_all([1, 2, 3, 24], 3, "linear")

    def test_sequence_answer(self):
        table, _ = insert_all([10, 22, 31, 4, 15, 28, 17, 88, 59], 11, "linear")
        key = {"value": ["-" if v is None else str(v) for v in table]}
        self.assertTrue(grade.check("sequence", key, "22, 88, -, -, 4, 15, 28, 17, 59, 31, 10"))
        self.assertFalse(grade.check("sequence", key, "22, 88, 4, 15, 28, 17, 59, 31, 10"))


class TestDraw(unittest.TestCase):
    def test_keys_match_the_solver(self):
        for seed in range(30):
            for variant in ("table", "probes"):
                p = make("hashing", seed, variant)
                m = re.search(r"Table size (\d+), h\(k\) = k mod \d+, (\w+) probing\. Insert in this order: ([\d, ]+)",
                              p.text)
                size = int(m[1])
                table, probes = insert_all([int(x) for x in m[3].split(", ")], size, m[2])
                if variant == "table":
                    self.assertEqual(len(p.expected["value"]), size)
                    self.assertEqual(p.expected["value"], ["-" if v is None else str(v) for v in table])
                else:
                    self.assertEqual(p.expected["value"], probes)
                self.assertIn("A probe is one slot looked at, the home slot included.", p.text)


if __name__ == "__main__":
    unittest.main()
