import subprocess
import sys
import unittest
from pathlib import Path

from pm import generators
from pm.generators import MAX_TRIES, ids, info, make, register, unregister


class Fake:
    ID = "fake"
    VERSION = 1
    TITLE = "Fake"
    VARIANTS = ("a",)

    def __init__(self, result=None):
        self.calls = 0
        self.result = result

    def draw(self, rng, variant):
        self.calls += 1
        return self.result


class TestRegistry(unittest.TestCase):
    def tearDown(self):
        unregister("fake")

    def test_ids_and_info(self):
        self.assertIn("paging", ids())
        with self.assertRaises(LookupError):
            info("nope")

    def test_same_seed_same_problem(self):
        self.assertEqual(make("paging", 7), make("paging", 7))
        self.assertEqual(make("paging", 7, make("paging", 7).variant), make("paging", 7))
        self.assertNotEqual(make("paging", 7), make("paging", 8))

    def test_unknown_variant(self):
        with self.assertRaisesRegex(ValueError, "paging has no variant 'nope'"):
            make("paging", 7, "nope")

    def test_gives_up_after_max_tries(self):
        fake = Fake()
        register(fake)
        with self.assertRaisesRegex(ValueError, "fake found no good problem for seed 1"):
            make("fake", 1)
        self.assertEqual(fake.calls, MAX_TRIES)

    def test_bad_key_is_an_error(self):
        register(Fake(("q", "number", {"value": "x"}, "")))
        with self.assertRaisesRegex(ValueError, "needs a value"):
            make("fake", 1)

    def test_stable_across_processes(self):
        code = "from pm.generators import make; print(make('paging', 7).text)"
        root = Path(generators.__file__).parents[2]
        out = [subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=root,
                              check=True).stdout for _ in range(2)]
        self.assertTrue(out[0].strip())
        self.assertEqual(out[0], out[1])


if __name__ == "__main__":
    unittest.main()
