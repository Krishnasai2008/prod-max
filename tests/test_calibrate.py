import math
import random
import unittest

from pm.calibrate import PRIOR, for_kind, median_ratio, posteriors, sample_ratio, update


class TestCalibrate(unittest.TestCase):
    def test_no_data_is_prior(self):
        self.assertEqual(update(PRIOR, []), PRIOR)
        self.assertEqual(posteriors([]), {"*": PRIOR})

    def test_learns_ratio(self):
        p = update(PRIOR, [math.log(2.0)] * 20)
        self.assertAlmostEqual(median_ratio(p), 2.0, delta=0.05)
        self.assertEqual(p.n, 20)

    def test_kind_needs_three(self):
        post = posteriors([("lab", 2.0)] * 2 + [("exam", 1.2)] * 5)
        self.assertIn("exam", post)
        self.assertNotIn("lab", post)
        self.assertIs(for_kind(post, "lab"), post["*"])

    def test_samples_clamped_and_centred(self):
        rng = random.Random(1)
        xs = sorted(sample_ratio(PRIOR, rng) for _ in range(2000))
        self.assertTrue(0.2 <= xs[0] and xs[-1] <= 10)
        tight = update(PRIOR, [math.log(2.0)] * 200)
        ys = sorted(sample_ratio(tight, rng) for _ in range(2000))
        self.assertAlmostEqual(ys[1000], 2.0, delta=0.1)


class TestExtremeDraw(unittest.TestCase):
    def test_tiny_chi2_does_not_overflow(self):
        class Rng:
            def gauss(self, mu, sigma): return 5.0
            def gammavariate(self, a, b): return 1e-300
        self.assertEqual(sample_ratio(PRIOR, Rng()), 10.0)
