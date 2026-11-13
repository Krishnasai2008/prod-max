import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import urlsplit

from pm import lh
from pm.db import connect, set_setting
from pm.stats import notes_minutes, site_spans
from pm.watch import tick

NOW = datetime(2026, 11, 9, 10, 0)
OLD = NOW - timedelta(minutes=1)
BACKUP = json.dumps({"study.time": json.dumps({"2026-11-09": {"os": 5_400_000}})}).encode()


class FakeSite:
    def __init__(self):
        self.requests = []
        self.sent = []
        self.bodies = {"/api/backup": b"null", "/api/pm-inbox": b"null", "/api/pm": b""}
        self.errors = {}

    def __call__(self, request, timeout=20):
        path = urlsplit(request.full_url).path
        self.requests.append((request.get_method(), path))
        self.sent.append((request.get_method(), path, request.data))
        if path in self.errors:
            raise self.errors[path]
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = self.bodies.get(path, b"")
        return response


class TestTick(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.root = Path(self.d.name)
        self.c = connect(":memory:")
        set_setting(self.c, "watch", str(self.root))
        notes = self.root / "notes.txt"
        notes.write_text("the TLB caches pages")
        os.utime(notes, (OLD.timestamp(), OLD.timestamp()))
        self.netrc = self.root / "netrc"
        self.netrc.write_text("machine x.dev login u password p\n")
        os.chmod(self.netrc, 0o600)
        self.site = FakeSite()
        send_patch = mock.patch("pm.watch.send")
        urlopen_patch = mock.patch("pm.stats.urlopen", side_effect=self.site)
        self.send = send_patch.start()
        urlopen_patch.start()
        self.lh_dir = mock.patch("pm.watch.lh.data_dir", return_value=None)
        self.lh_dir.start()
        self.addCleanup(self.lh_dir.stop)
        self.addCleanup(send_patch.stop)
        self.addCleanup(urlopen_patch.stop)
        self.addCleanup(self.c.close)
        self.addCleanup(self.d.cleanup)

    def tick(self, now, last):
        return tick(self.c, now, last, self.netrc)

    def test_no_learnharness_no_sync(self):
        with mock.patch("pm.watch.lh.sync") as sync:
            self.tick(NOW, None)
        sync.assert_not_called()

    def test_learnharness_sync_lines(self):
        self.lh_dir.stop()
        lh_lines = lambda lines: [x for x in lines if x.startswith("learnharness:")]
        with mock.patch("pm.watch.lh.data_dir", return_value=self.root):
            with mock.patch("pm.watch.lh.sync", return_value=lh.Sync(sessions=1, answers=2)):
                lines, last = self.tick(NOW, None)
            self.assertEqual(lh_lines(lines), ["learnharness: 1 sessions, 2 answers, 0 outcomes, 0 questions, 0 cards"])
            with mock.patch("pm.watch.lh.sync", return_value=lh.Sync()):
                self.assertEqual(lh_lines(self.tick(NOW, last)[0]), [])
            skipped = lh.Sync(skipped=["chat_v2.json: newer LearnHarness format (version 2)"])
            with mock.patch("pm.watch.lh.sync", return_value=skipped):
                self.assertEqual(lh_lines(self.tick(NOW, last)[0]),
                                 ["learnharness: chat_v2.json: newer LearnHarness format (version 2)"])
                self.assertEqual(lh_lines(self.tick(NOW, last)[0]), [])
            with mock.patch("pm.watch.lh.sync", side_effect=ValueError("x")), \
                    mock.patch("pm.watch.refresh_files") as refresh:
                lines, _ = self.tick(NOW + timedelta(hours=2), last)
            self.assertIn("learnharness: x", lines)
            refresh.assert_called_once()
        self.lh_dir.start()

    def test_agent_off_by_default(self):
        with mock.patch("pm.watch.agent.plan") as plan, mock.patch("pm.watch.agent.run") as run:
            self.tick(NOW, None)
        plan.assert_not_called()
        run.assert_not_called()

    def test_agent_needs_llm_cmd(self):
        set_setting(self.c, "agent_daily_calls", "5")
        agent_lines = lambda lines: [x for x in lines if x.startswith("agent:")]  # noqa: E731
        lines, last = self.tick(NOW, None)
        self.assertEqual(agent_lines(lines), ["agent: set llm_cmd first"])
        self.assertEqual(agent_lines(self.tick(NOW + timedelta(hours=2), last)[0]), [])
        self.assertEqual(agent_lines(self.tick(NOW + timedelta(days=1), last)[0]), ["agent: set llm_cmd first"])

    def test_agent_runs_hourly(self):
        set_setting(self.c, "agent_daily_calls", "5")
        set_setting(self.c, "llm_cmd", "my-llm")
        with mock.patch("pm.watch.agent.plan") as plan, \
                mock.patch("pm.watch.agent.run", return_value=["ping #1: ping: ok"]) as run:
            lines, last = self.tick(NOW, None)
            self.assertIn("agent: ping #1: ping: ok", lines)
            self.tick(NOW + timedelta(seconds=10), last)
        self.assertEqual((plan.call_count, run.call_count), (1, 1))
        with mock.patch("pm.watch.agent.plan", side_effect=ValueError("x")):
            (self.root / "new.txt").write_text("more")
            os.utime(self.root / "new.txt", (OLD.timestamp(), OLD.timestamp()))
            lines, after = self.tick(NOW + timedelta(hours=2), last)
        self.assertIn("agent: x", lines)
        self.assertTrue(any(line.startswith("indexed 1") for line in lines))
        self.assertEqual(after, NOW + timedelta(hours=2))

    def test_first_tick_indexes_and_runs_hourly(self):
        lines, last = self.tick(NOW, None)
        self.assertTrue(any("indexed 1, updated 0, removed 0" in line for line in lines))
        self.assertEqual(last, NOW)
        self.send.assert_called_once_with([])

    def test_second_tick_is_quiet_until_the_next_hour(self):
        _, last = self.tick(NOW, None)
        lines, same = self.tick(NOW + timedelta(seconds=10), last)
        self.assertEqual(lines, [])
        self.assertEqual(same, last)
        self.assertEqual(self.send.call_count, 1)
        _, the_hour = self.tick(NOW + timedelta(minutes=61), same)
        self.assertEqual(the_hour, NOW + timedelta(minutes=61))
        self.assertEqual(self.send.call_count, 2)

    def test_hourly_tick_recounts_topic_files(self):
        with mock.patch("pm.watch.refresh_files") as refresh:
            _, last = self.tick(NOW, None)
            self.tick(NOW + timedelta(minutes=5), last)
        refresh.assert_called_once_with(self.c)

    def test_push_failure_is_one_log_line(self):
        set_setting(self.c, "notes_url", "https://x.dev")
        self.site.errors["/api/pm"] = HTTPError("https://x.dev/api/pm", 500,
                                                "Server Error", {}, None)
        lines, _ = self.tick(NOW, None)
        self.assertEqual(sum("push failed: HTTP 500" in line for line in lines), 1)

    def test_no_notes_url_makes_no_requests(self):
        self.tick(NOW, None)
        self.assertEqual(self.site.requests, [])

    def test_hourly_tick_pulls_the_study_clock_then_pushes(self):
        set_setting(self.c, "notes_url", "https://x.dev")
        self.site.bodies["/api/backup"] = BACKUP
        lines, _ = self.tick(NOW, None)
        self.assertEqual(notes_minutes(self.c), {"2026-11-09": 90})
        self.assertEqual(self.site.requests, [("GET", "/api/pm-inbox"), ("GET", "/api/backup"),
                                              ("PUT", "/api/pm")])
        self.assertIn("pushed 1 KB", lines)
        self.assertFalse(any(line.startswith("pull failed:") for line in lines))

    def test_hourly_tick_syncs_the_scoreboard_before_the_push(self):
        set_setting(self.c, "notes_url", "https://x.dev")
        set_setting(self.c, "versus_url", "https://x.dev")
        card = {"version": 1, "generated": "2026-11-09T09:00:00", "days": {"2026-11-08": {"min": 30}}}
        self.site.bodies["/api/versus"] = json.dumps({"you": "u", "cards": {"u": card, "sam": card}}).encode()
        lines, last = self.tick(NOW, None)
        self.assertEqual(self.site.requests, [("GET", "/api/pm-inbox"), ("GET", "/api/backup"), ("PUT", "/api/versus"),
                                              ("GET", "/api/versus"), ("PUT", "/api/pm")])
        self.assertIn("versus: 2 players", lines)
        sent = json.loads(self.site.sent[2][2])
        self.assertEqual((sent["version"], sent["generated"]), (1, "2026-11-09T10:00:00"))
        pushed = json.loads(self.site.sent[-1][2])
        self.assertEqual(pushed["versus"]["players"], ["sam", "u"])
        self.assertEqual(pushed["versus"]["you"], "u")
        self.tick(NOW + timedelta(seconds=10), last)
        self.assertEqual(len(self.site.requests), 5)

    def test_the_scoreboard_can_live_on_another_site_and_needs_no_notes_site(self):
        set_setting(self.c, "versus_url", "https://x.dev")
        self.site.bodies["/api/versus"] = b'{"you": null, "cards": {}}'
        lines, _ = self.tick(NOW, None)
        self.assertEqual(self.site.requests, [("PUT", "/api/versus"), ("GET", "/api/versus")])
        self.assertIn("versus: 0 players", lines)

    def test_a_scoreboard_failure_is_one_log_line_and_the_push_still_runs(self):
        set_setting(self.c, "notes_url", "https://x.dev")
        set_setting(self.c, "versus_url", "https://x.dev")
        for body, line in ((b"null", "versus failed: the scoreboard's reply is not a set of cards"),
                           (b"<html>", "versus failed: the scoreboard's reply is not JSON")):
            with self.subTest(body=body):
                self.site.bodies["/api/versus"] = body
                lines, _ = self.tick(NOW, None)
                self.assertEqual([x for x in lines if x.startswith("versus")], [line])
                self.assertIn("pushed 1 KB", lines)
                self.assertIsNone(json.loads(self.site.sent[-1][2])["versus"])
        self.site.errors["/api/versus"] = HTTPError("https://x.dev/api/versus", 401, "no", {}, None)
        lines, _ = self.tick(NOW, None)
        self.assertEqual(sum(x.startswith("versus failed: HTTP 401") for x in lines), 1)
        self.assertIn("pushed 1 KB", lines)

    def test_without_versus_url_the_scoreboard_is_never_asked(self):
        set_setting(self.c, "notes_url", "https://x.dev")
        self.tick(NOW, None)
        self.assertNotIn("/api/versus", [path for _, path in self.site.requests])
        self.assertIsNone(json.loads(self.site.sent[-1][2])["versus"])

    def test_a_quick_tick_does_not_pull_again(self):
        set_setting(self.c, "notes_url", "https://x.dev")
        _, last = self.tick(NOW, None)
        requests = list(self.site.requests)
        self.tick(NOW + timedelta(seconds=10), last)
        self.assertEqual(self.site.requests, requests)

    def test_the_study_clock_is_read_on_every_inbox_check_not_once_an_hour(self):
        set_setting(self.c, "notes_url", "https://x.dev")
        _, last = self.tick(NOW, None)
        self.site.bodies["/api/backup"] = json.dumps({
            "study.time": json.dumps({"2026-11-09": {"os": 5_400_000}}),
            "study.spans": json.dumps({"2026-11-09": [[540, 630]]})}).encode()
        before = len(self.site.requests)
        self.tick(NOW + timedelta(minutes=4), last)
        self.assertEqual(len(self.site.requests), before)
        self.tick(NOW + timedelta(minutes=6), last)
        self.assertEqual(self.site.requests[before:], [("GET", "/api/pm-inbox"), ("GET", "/api/backup")])
        self.assertEqual(notes_minutes(self.c), {"2026-11-09": 90})
        self.assertEqual(site_spans(self.c), {"2026-11-09": [[540, 630]]})

    def test_the_study_clock_is_still_read_when_the_inbox_fails(self):
        set_setting(self.c, "notes_url", "https://x.dev")
        self.site.bodies["/api/backup"] = BACKUP
        self.site.errors["/api/pm-inbox"] = HTTPError("https://x.dev/api/pm-inbox", 404, "Not Found", {}, None)
        lines, _ = self.tick(NOW, None)
        self.assertEqual(sum("inbox failed: HTTP 404" in line for line in lines), 1)
        self.assertEqual(notes_minutes(self.c), {"2026-11-09": 90})

    def test_pull_failure_is_one_log_line_and_the_push_still_runs(self):
        set_setting(self.c, "notes_url", "https://x.dev")
        self.site.errors["/api/backup"] = HTTPError("https://x.dev/api/backup", 500,
                                                    "Server Error", {}, None)
        lines, _ = self.tick(NOW, None)
        self.assertEqual(sum("pull failed: HTTP 500" in line for line in lines), 1)
        self.assertIn(("PUT", "/api/pm"), self.site.requests)
        self.assertEqual(notes_minutes(self.c), {})

    def test_a_missing_netrc_entry_gets_the_pull_prefix_once(self):
        set_setting(self.c, "notes_url", "https://x.dev")
        self.netrc.write_text("machine other.dev login u password p\n")
        lines, _ = self.tick(NOW, None)
        pull_lines = [line for line in lines if line.startswith("pull failed:")]
        self.assertEqual(len(pull_lines), 1)
        self.assertTrue(pull_lines[0].startswith("pull failed: add 'machine x.dev"))
        self.assertTrue(any(line.startswith("push failed:") for line in lines))

    def test_backup_is_never_put(self):
        set_setting(self.c, "notes_url", "https://x.dev")
        self.site.bodies["/api/backup"] = BACKUP
        self.tick(NOW, None)
        self.tick(NOW + timedelta(minutes=61), NOW)
        self.assertEqual([method for method, path in self.site.requests
                          if path == "/api/backup"], ["GET", "GET"])

    def test_an_inbox_entry_is_applied_and_pushed_once_in_the_same_tick(self):
        set_setting(self.c, "notes_url", "https://x.dev")
        self.site.bodies["/api/pm-inbox"] = json.dumps({"items": [
            {"id": "a1", "at": "2026-11-09T09:00:00", "op": "add",
             "title": "OS lab 3", "est": "1h"}]}).encode()
        lines, _ = self.tick(NOW, None)
        self.assertIn("inbox: added #1 OS lab 3", lines)
        self.assertIn("pushed 1 KB", lines)
        puts = [body for method, path, body in self.site.sent
                if (method, path) == ("PUT", "/api/pm")]
        self.assertEqual(len(puts), 1)
        self.assertEqual(json.loads(puts[0])["inbox_done"], [{"id": "a1"}])

    def test_a_failed_push_after_applying_is_retried_at_the_next_inbox_check(self):
        set_setting(self.c, "notes_url", "https://x.dev")
        self.site.bodies["/api/pm-inbox"] = json.dumps({"items": [
            {"id": "a1", "op": "add", "title": "OS lab 3", "est": "1h"}]}).encode()
        self.site.errors["/api/pm"] = HTTPError("https://x.dev/api/pm", 503, "Busy", {}, None)
        _, last = self.tick(NOW, None)
        before = len(self.site.requests)
        lines, _ = self.tick(NOW + timedelta(seconds=10), last)  # not every tick: the site may be down for hours
        self.assertEqual((lines, len(self.site.requests)), ([], before))
        del self.site.errors["/api/pm"]
        lines, _ = self.tick(NOW + timedelta(minutes=5), last)
        self.assertIn("pushed 1 KB", lines)
        self.assertNotIn("inbox: added #2 OS lab 3", lines)
        lines, _ = self.tick(NOW + timedelta(minutes=10), last)
        self.assertNotIn("pushed 1 KB", lines)

    def test_a_busy_database_does_not_push(self):
        set_setting(self.c, "notes_url", "https://x.dev")
        _, last = self.tick(NOW, None)
        with mock.patch("pm.watch.apply_inbox", return_value=["inbox: the database is busy; the rest waits"
                                                              " for the next check"]):
            lines, _ = self.tick(NOW + timedelta(minutes=5), last)
        self.assertNotIn("pushed 1 KB", lines)

    def test_the_inbox_is_checked_every_five_minutes(self):
        set_setting(self.c, "notes_url", "https://x.dev")
        _, last = self.tick(NOW, None)
        self.assertEqual(sum(path == "/api/pm-inbox" for _, path in self.site.requests), 1)
        self.tick(NOW + timedelta(minutes=2), last)
        self.assertEqual(sum(path == "/api/pm-inbox" for _, path in self.site.requests), 1)
        self.tick(NOW + timedelta(minutes=5), last)
        self.assertEqual(sum(path == "/api/pm-inbox" for _, path in self.site.requests), 2)

    def test_a_missing_inbox_route_is_one_line_and_retried_after_five_minutes(self):
        set_setting(self.c, "notes_url", "https://x.dev")
        self.site.errors["/api/pm-inbox"] = HTTPError(
            "https://x.dev/api/pm-inbox", 404, "Not Found", {}, None)
        lines, last = self.tick(NOW, None)
        self.assertEqual(sum("inbox failed: HTTP 404" in line for line in lines), 1)
        self.assertIn("pushed 1 KB", lines)
        self.tick(NOW + timedelta(seconds=10), last)
        self.assertEqual(sum(path == "/api/pm-inbox" for _, path in self.site.requests), 1)
        self.tick(NOW + timedelta(minutes=5), last)
        self.assertEqual(sum(path == "/api/pm-inbox" for _, path in self.site.requests), 2)


class TestLoop(unittest.TestCase):
    def test_a_failing_tick_does_not_end_the_daemon(self):
        from pm import watch
        ticks = [RuntimeError("odd file"), KeyboardInterrupt()]

        def failing(conn, now, last_hourly, netrc_path):
            raise ticks.pop(0)

        with mock.patch("pm.watch.tick", side_effect=failing), mock.patch("pm.watch.time.sleep"), \
                mock.patch("builtins.print") as printed:
            self.assertEqual(watch.loop(":memory:"), 0)
        printed.assert_called_once_with("tick failed: RuntimeError: odd file", flush=True)
        self.assertEqual(ticks, [])

    def test_a_clock_set_back_counts_as_due(self):
        c = connect(":memory:")
        self.addCleanup(c.close)
        with mock.patch("pm.watch.send"), mock.patch("pm.watch.refresh_files") as hourly:
            tick(c, NOW, NOW + timedelta(hours=3))
        hourly.assert_called_once()
