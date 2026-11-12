import unittest
from datetime import date, datetime, timedelta

from pm.bugs import MAX_DIFF, episodes, get_episode, record_run, runs, set_tags, summary
from pm.db import connect

T0 = datetime(2026, 11, 9, 10)
DIFF = "@@ -1 +1 @@\n-for (i = 0; i <= n; i++)\n+for (i = 0; i < n; i++)\n"


def fake(a, b):
    return f"diff {a} {b}"


class TestBugs(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)

    def fixed(self, cmd, start, diff=DIFF, code=1, cwd="/p"):
        record_run(self.c, cmd, cwd, start, 1.0, code, "a", None, lambda a, b: diff)
        return record_run(self.c, cmd, cwd, start + timedelta(minutes=10), 1.0, 0, "b", None,
                          lambda a, b: diff)

    def test_fails_then_success_is_a_fixed_episode(self):
        self.assertIsNone(record_run(self.c, "make", "/p", T0, 1.0, 1, "s1", None, fake))
        self.assertIsNone(record_run(self.c, "make", "/p", T0 + timedelta(minutes=10), 1.0, 2, "s2", None, fake))
        ep = record_run(self.c, "make", "/p", T0 + timedelta(minutes=25), 1.0, 0, "s3", None, fake)
        self.assertEqual((ep.status, ep.fails, ep.lost_s, ep.diff), ("fixed", 2, 25 * 60, "diff s2 s3"))

    def test_long_gap_counts_thirty_minutes(self):
        record_run(self.c, "make", "/p", T0, 1.0, 1, None, None)
        ep = record_run(self.c, "make", "/p", T0 + timedelta(hours=5), 1.0, 0, None, None)
        self.assertEqual((ep.lost_s, ep.diff), (30 * 60, None))

    def test_stale_episode_is_abandoned(self):
        record_run(self.c, "make", "/p", T0, 1.0, -11, "s1", None, fake)
        self.assertIsNone(record_run(self.c, "make", "/p", T0 + timedelta(days=3), 1.0, 0, "s2", None, fake))
        (ep,) = episodes(self.c)
        self.assertEqual((ep.status, ep.diff, ep.tags), ("abandoned", None, ["segfault"]))

    def test_success_without_episode(self):
        self.assertIsNone(record_run(self.c, "make", "/p", T0, 1.0, 0, "s1", None, fake))
        self.assertEqual(episodes(self.c), [])

    def test_different_cmd_or_cwd_are_separate(self):
        record_run(self.c, "make", "/p", T0, 1.0, 1, "a", None, fake)
        record_run(self.c, "make", "/q", T0, 1.0, 1, "a", None, fake)
        record_run(self.c, "test", "/p", T0, 1.0, 1, "a", None, fake)
        self.assertEqual(len(episodes(self.c)), 3)
        self.assertEqual({(ep.cmd, ep.cwd) for ep in episodes(self.c)},
                         {("make", "/p"), ("make", "/q"), ("test", "/p")})

    def test_long_diff_is_cut(self):
        record_run(self.c, "make", "/p", T0, 1.0, 1, "a", None, fake)
        ep = record_run(self.c, "make", "/p", T0 + timedelta(minutes=1), 1.0, 0, "b", None,
                        lambda a, b: "x" * (MAX_DIFF + 50))
        self.assertTrue(ep.diff.endswith("… (diff cut)"))
        self.assertEqual(len(ep.diff), MAX_DIFF + len("\n… (diff cut)"))

    def test_diff_is_tagged(self):
        self.assertEqual(self.fixed("make", T0).tags, ["off-by-one"])

    def test_set_tags(self):
        ep = self.fixed("make", T0)
        self.assertEqual(set_tags(self.c, ep.id, ["bounds", "off-by-one"]), ["bounds", "off-by-one"])
        self.assertEqual(get_episode(self.c, ep.id).tags, ["bounds", "off-by-one"])
        for tags in (["none"], ["none", "overflow"]):
            with self.subTest(tags=tags):
                with self.assertRaisesRegex(
                        ValueError, "'none' isn't a tag; pm bug ID none clears the tags"):
                    set_tags(self.c, ep.id, tags)
                self.assertEqual(get_episode(self.c, ep.id).tags, ["bounds", "off-by-one"])
        with self.assertRaises(ValueError):
            set_tags(self.c, ep.id, ["Bad Tag"])

    def test_get_episode_missing(self):
        with self.assertRaises(LookupError):
            get_episode(self.c, 99)

    def test_runs_are_in_time_order_with_codes(self):
        record_run(self.c, "make test", "/p", T0, 0.5, 2, "a", None, fake)
        record_run(self.c, "make test", "/p", T0 + timedelta(minutes=5), 0.7, 2, "b", None, fake)
        ep = record_run(self.c, "make test", "/p", T0 + timedelta(minutes=9), 1.2, 0, "c",
                        None, fake)
        got = runs(self.c, ep.id)
        self.assertEqual([r.code for r in got], [2, 2, 0])
        self.assertEqual([r.start for r in got],
                         [T0, T0 + timedelta(minutes=5), T0 + timedelta(minutes=9)])
        self.assertEqual([r.dur_s for r in got], [0.5, 0.7, 1.2])

    def test_runs_missing_episode(self):
        with self.assertRaises(LookupError):
            runs(self.c, 99)

    def test_episodes_filter_by_tag(self):
        one = self.fixed("make", T0)
        two = self.fixed("test", T0)
        set_tags(self.c, two.id, ["overflow"])
        self.assertEqual([ep.id for ep in episodes(self.c, 10, tag="off-by-one")], [one.id])
        self.assertEqual([ep.id for ep in episodes(self.c, 10, tag="overflow")], [two.id])
        self.assertEqual({ep.id for ep in episodes(self.c, 10)}, {one.id, two.id})

    def test_summary(self):
        self.fixed("a", T0)
        self.fixed("b", T0)
        self.fixed("c", T0)
        self.fixed("old", T0 - timedelta(days=8))
        record_run(self.c, "plain", "/p", T0, 1.0, 1, "a", None, lambda a, b: "x = 10")
        record_run(self.c, "plain", "/p", T0 + timedelta(minutes=10), 1.0, 0, "b", None,
                   lambda a, b: "x = 20")
        record_run(self.c, "open", "/p", T0, 1.0, 1, "a", None, fake)
        record_run(self.c, "gone", "/p", T0 - timedelta(days=3), 1.0, 1, "a", None, fake)
        record_run(self.c, "gone", "/p", T0, 1.0, 0, "b", None, fake)
        s = summary(self.c, date(2026, 11, 9))
        self.assertEqual((s.fixed, s.open, s.abandoned), (5, 1, 1))
        self.assertEqual(s.lost_s, 5 * 600)
        self.assertEqual(s.tags, [("off-by-one", 4)])
        self.assertEqual(s.untagged, 1)
        self.assertEqual(s.bursts, [("off-by-one", 3)])

    def test_burst_window_is_seven_days(self):
        for k, days_ago in enumerate((0, 3, 6)):
            self.fixed(f"cmd{k}", T0 - timedelta(days=days_ago))
        self.assertEqual(summary(self.c, date(2026, 11, 9)).bursts, [("off-by-one", 3)])
