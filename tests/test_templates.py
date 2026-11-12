import dataclasses
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pm import generators, templates
from pm.generators import ids, make, register, unregister
from pm.templates import as_generator, check_file, fill, folder_of, parse, sync

EXAMPLE = '''id = "mm1-wait"
version = 1
title = "M/M/1 time in system"
text = "Jobs arrive at {lam} per hour and one server finishes {mu} per hour. What is the mean time a job spends in the system, in minutes?"
answer = "60 / (mu - lam)"
decimals = 2
steps = "W = 1 / (mu − lam) hours = 60 / ({mu} − {lam}) = {answer} minutes."
constraints = ["mu > lam", "(6000 / (mu - lam)) % 1 == 0"]

[params]
lam = { int = [2, 20] }
mu = { int = [3, 30] }

[original]
params = { lam = 8, mu = 12 }
answer = 15
'''


class TestParse(unittest.TestCase):
    def tearDown(self):
        unregister("t:mm1-wait")

    def test_example(self):
        t = parse(EXAMPLE)
        self.assertEqual(len(t.params), 2)
        self.assertEqual(as_generator(t).ID, "t:mm1-wait")

    def test_draws(self):
        register(as_generator(parse(EXAMPLE)))
        self.assertEqual(make("t:mm1-wait", 5), make("t:mm1-wait", 5))
        for seed in range(100):
            p = make("t:mm1-wait", seed)
            lam, mu = map(int, re.search(r"arrive at (\d+) per hour and one server finishes (\d+)", p.text).groups())
            self.assertGreater(mu, lam)
            self.assertEqual(p.expected["value"], round(60 / (mu - lam), 2))
            self.assertEqual(p.expected["tol"], 0.005)
            self.assertIn("Give the answer to 2 decimal places.", p.text)
            self.assertIn(f"{p.expected['value']:.2f} minutes", p.steps)

    def test_trust_check(self):
        with self.assertRaisesRegex(ValueError, r"doesn't reproduce its original answer: got 15(\.0)?, expected 16"):
            parse(EXAMPLE.replace("answer = 15", "answer = 16"))

    def test_needs_original(self):
        with self.assertRaisesRegex(ValueError, "a template needs the original problem it came from"):
            parse(EXAMPLE.split("[original]")[0])

    def test_original_breaks_constraint(self):
        with self.assertRaisesRegex(ValueError, "the original problem breaks the constraint 'mu > lam'"):
            parse(EXAMPLE.replace("{ lam = 8, mu = 12 }", "{ lam = 8, mu = 5 }"))

    def test_unsafe_answer(self):
        with mock.patch("os.system") as system:
            with self.assertRaises(ValueError):
                parse(EXAMPLE.replace('answer = "60 / (mu - lam)"', '''answer = "__import__('os').system('x')"'''))
            system.assert_not_called()
        for bad in ("9**9**9", "a.__class__"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "answer"):
                parse(EXAMPLE.replace('"60 / (mu - lam)"', f'"{bad}"'))

    def test_bad_fields(self):
        cases = {
            "id": EXAMPLE.replace('id = "mm1-wait"', 'id = "Bad Id"'),
            "decimals": EXAMPLE.replace("decimals = 2", "decimals = 9"),
            "'answer'": EXAMPLE.replace("lam = { int", "answer = { int = [1, 2] }\nlam = { int"),
            "params.mu": EXAMPLE.replace("mu = { int = [3, 30] }", "mu = { int = [5, 1] }"),
            "params": re.sub(r"\[params\].*?\n\n", "", EXAMPLE, flags=re.S),
            "params.lam": EXAMPLE.replace("lam = { int = [2, 20] }", "lam = { decimal = [0.21, 0.29, 1] }"),
            "original.params": EXAMPLE.replace("lam = 8, mu = 12", "lam = inf, mu = 12"),
        }
        for field, text in cases.items():
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, re.escape(field)):
                parse(text)

    def test_decimal_draws_stay_in_range(self):
        t = parse(EXAMPLE.replace("lam = { int = [2, 20] }", "lam = { decimal = [0.25, 0.35, 1] }")
                  .replace("constraints = [\"mu > lam\", \"(6000 / (mu - lam)) % 1 == 0\"]", "constraints = []")
                  .replace("lam = 8, mu = 12", "lam = 0.3, mu = 12").replace("answer = 15", "answer = 5.13"))
        rng = __import__("random").Random(0)
        self.assertEqual({templates._value(rng, t.params["lam"]) for _ in range(50)}, {0.3})

    def test_fill(self):
        self.assertEqual(fill("{lam} and {a.__class__} and {0} and {unknown}", {"lam": 8}),
                         "8 and {a.__class__} and {0} and {unknown}")

    def test_impossible_constraints(self):
        t = dataclasses.replace(parse(EXAMPLE), constraints=["mu < 0"])
        with self.assertRaisesRegex(ValueError, "found no good problem"):
            generators.build(as_generator(t), 1)

    def test_check_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "mm1.toml"
            path.write_text(EXAMPLE)
            self.assertTrue(check_file(path).startswith("ok: mm1-wait reproduces its original answer"))
            path.write_text(EXAMPLE.replace("answer = 15", "answer = 16"))
            with self.assertRaises(ValueError):
                check_file(path)
        self.assertNotIn("t:mm1-wait", ids())


class TestSync(unittest.TestCase):
    def test_memory_has_no_folder(self):
        self.assertIsNone(folder_of(sqlite3.connect(":memory:")))
        self.assertEqual(sync(sqlite3.connect(":memory:")), [])

    def test_sync(self):
        with tempfile.TemporaryDirectory() as d:
            conn = sqlite3.connect(Path(d) / "pm.db")
            folder = folder_of(conn)
            self.assertEqual(folder, Path(d) / "templates")
            folder.mkdir()
            (folder / "good.toml").write_text(EXAMPLE)
            (folder / "bad.toml").write_text(EXAMPLE.replace("answer = 15", "answer = 16"))
            errors = sync(conn)
            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0].startswith("bad.toml: "))
            self.assertIn("t:mm1-wait", ids())
            with mock.patch.object(templates.tomllib, "loads") as loads:
                self.assertEqual(sync(conn), errors)
                loads.assert_not_called()
            (folder / "good.toml").unlink()
            sync(conn)
            self.assertNotIn("t:mm1-wait", ids())
            conn.close()


if __name__ == "__main__":
    unittest.main()
