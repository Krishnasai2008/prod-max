import re
import unittest

from pm.generators import make
from pm.generators.disk import NAMES, service

Q = [98, 183, 37, 122, 14, 124, 65, 67]


class TestService(unittest.TestCase):
    def test_textbook(self):
        self.assertEqual(service(Q, 53, "fcfs")[1], 640)
        self.assertEqual(service(Q, 53, "sstf"), ([65, 67, 37, 14, 98, 122, 124, 183], 236))
        self.assertEqual(service(Q, 53, "scan", up=False)[1], 236)
        self.assertEqual(service(Q, 53, "scan", up=True)[1], 331)
        self.assertEqual(service(Q, 53, "cscan", up=True)[1], 382)
        self.assertEqual(service(Q, 53, "look", up=False)[1], 208)
        self.assertEqual(service(Q, 53, "look", up=True)[1], 299)
        self.assertEqual(service(Q, 53, "clook", up=True)[1], 322)

    def test_sstf_tie_goes_low(self):
        self.assertEqual(service([60, 40], 50, "sstf")[0], [40, 60])

    def test_request_on_the_head(self):
        for policy in ("sstf", "scan", "cscan", "look", "clook"):
            for up in (True, False):
                order, total = service([50, 30, 70], 50, policy, up)
                self.assertEqual(order[0], 50, policy)
        self.assertEqual(service([50], 50, "sstf"), ([50], 0))

    def test_unknown_policy(self):
        with self.assertRaises(ValueError):
            service(Q, 53, "elevator")


class TestDraw(unittest.TestCase):
    def test_keys_match_the_solver(self):
        back = {v: k for k, v in NAMES.items()}
        for seed in range(50):
            for variant in ("movement", "order"):
                p = make("disk", seed, variant)
                m = re.search(r"Head at (\d+), moving toward (\d+)\. Queue: ([\d, ]+)", p.text)
                queue = [int(x) for x in m[3].split(", ")]
                policy = back[re.search(r"under (C-SCAN|C-LOOK|FCFS|SSTF|SCAN|LOOK)", p.text)[1]]
                order, total = service(queue, int(m[1]), policy, m[2] == "199")
                if variant == "movement":
                    self.assertEqual(p.expected["value"], total)
                else:
                    self.assertEqual(p.expected["value"], [str(c) for c in order])
                self.assertIn(f"Total head movement: {total}", p.steps)


if __name__ == "__main__":
    unittest.main()
