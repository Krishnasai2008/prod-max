import re
import unittest

from pm import grade
from pm.generators import make
from pm.generators.cpu import finish_order, schedule, waits


def same0(*bursts):
    return [(f"P{i}", 0, b) for i, b in enumerate(bursts, 1)]


def mean(procs, policy, q=None):
    w = waits(procs, schedule(procs, policy, q))
    return sum(w.values()) / len(w)


def parsed(text):
    procs = [(m[1], int(m[2]), int(m[3])) for m in re.finditer(r"\| (P\d) \| (\d+) \| (\d+) \|", text)]
    q = re.search(r"quantum (\d+)", text)
    return procs, int(q[1]) if q else None


def policy_of(text):
    m = re.search(r"under (FCFS|SJF|SRTF|round robin)", text)[1]
    return "rr" if m == "round robin" else m.lower()


def segments(text):
    return [(m[1], int(m[2]), int(m[3])) for m in re.finditer(r"(P\d) (\d+)–(\d+)", text)]


class TestSchedule(unittest.TestCase):
    def test_fcfs(self):
        procs = same0(24, 3, 3)
        self.assertEqual(waits(procs, schedule(procs, "fcfs")), {"P1": 0, "P2": 24, "P3": 27})
        self.assertEqual(mean(procs, "fcfs"), 17)

    def test_sjf(self):
        procs = same0(6, 8, 7, 3)
        self.assertEqual(mean(procs, "sjf"), 7)
        self.assertEqual(finish_order(schedule(procs, "sjf")), ["P4", "P1", "P3", "P2"])

    def test_rr(self):
        procs = same0(24, 3, 3)
        self.assertEqual(waits(procs, schedule(procs, "rr", 4)), {"P1": 6, "P2": 4, "P3": 7})
        self.assertAlmostEqual(mean(procs, "rr", 4), 17 / 3)

    def test_srtf(self):
        procs = [("P1", 0, 8), ("P2", 1, 4), ("P3", 2, 9), ("P4", 3, 5)]
        gantt = schedule(procs, "srtf")
        self.assertEqual(mean(procs, "srtf"), 6.5)
        self.assertEqual(finish_order(gantt), ["P2", "P4", "P1", "P3"])
        self.assertEqual(sum(g[0] == "P1" for g in gantt), 2)
        self.assertEqual(mean(procs, "sjf"), 7.75)  # non-preemptive SJF on the same arrivals (Silberschatz)

    def test_idle(self):
        procs = [("P1", 0, 2), ("P2", 5, 1)]
        gantt = schedule(procs, "fcfs")
        self.assertEqual(gantt, [("P1", 0, 2), ("P2", 5, 6)])
        self.assertEqual(waits(procs, gantt), {"P1": 0, "P2": 0})

    def test_srtf_equal_newcomer_does_not_preempt(self):
        procs = [("P1", 0, 4), ("P2", 1, 3)]
        self.assertEqual(schedule(procs, "srtf"), [("P1", 0, 4), ("P2", 4, 7)])

    def test_rr_arrival_joins_before_preempted(self):
        procs = [("P1", 0, 4), ("P2", 2, 2)]
        self.assertEqual(schedule(procs, "rr", 2), [("P1", 0, 2), ("P2", 2, 4), ("P1", 4, 6)])

    def test_rr_needs_quantum(self):
        with self.assertRaises(ValueError):
            schedule(same0(1), "rr")

    def test_sequence_formats(self):
        procs = same0(6, 8, 7, 3)
        key = {"value": finish_order(schedule(procs, "sjf"))}
        for answer in ("p4, p1 → p3 → p2", "P4 P1 P3 P2", "P4, P1, P3, P2", "p4 -> p1 -> p3 -> p2"):
            self.assertTrue(grade.check("sequence", key, answer), answer)
        self.assertFalse(grade.check("sequence", key, "P1 P4 P3 P2"))


class TestDraw(unittest.TestCase):
    def test_keys_match_the_solver(self):
        for seed in range(50):
            for variant in ("avg_wait", "order"):
                p = make("cpu", seed, variant)
                procs, q = parsed(p.text)
                self.assertEqual(len(procs), 4)
                gantt = schedule(procs, policy_of(p.text), q)
                if variant == "avg_wait":
                    self.assertIn("to 2 decimal places", p.text)
                    w = waits(procs, gantt)
                    self.assertLessEqual(abs(p.expected["value"] - sum(w.values()) / 4), 0.005)
                else:
                    self.assertEqual(p.expected["value"], finish_order(gantt))
                self.assertIn("Waiting time is completion minus arrival minus burst", p.text)

    def test_which(self):
        for seed in range(50):
            p = make("cpu", seed, "which")
            procs, _ = parsed(p.text)
            shown = segments(p.text.split("\n\n")[1])
            matches = [pol for pol in ("fcfs", "sjf", "srtf") if schedule(procs, pol) == shown]
            self.assertEqual(matches, [p.expected["value"].lower()])


if __name__ == "__main__":
    unittest.main()
