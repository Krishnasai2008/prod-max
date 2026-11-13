import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from http.client import InvalidURL
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

from pm.bugs import record_run
from pm.db import connect, set_setting
from pm.inbox import apply as apply_inbox
from pm.risk import TaskRisk
from pm.stats import (build, combined, fetch_inbox, notes_minutes, pull_site, push, request,
                      save_notes, save_spans, site_spans)
from pm.study import add_item, add_topic, record_review
from pm.tasks import add_task, done, log_time, open_tasks, start, stop

NOW = datetime(2026, 11, 9, 13, 0)


class TestStats(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)

    def test_empty_database(self):
        data = build(self.c, NOW, [], [], 0.0)
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["generated"], "2026-11-09T13:00:00")
        self.assertEqual(data["settings"], {"hours_per_day": 4.0, "peak": "09-12"})
        self.assertEqual(data["days"], {})
        self.assertEqual(data["time"], {"by_course": {}, "by_kind": {}, "by_energy": {}})
        self.assertEqual(data["estimates"], {"kinds": [], "history": []})
        self.assertEqual(data["deadlines"],
                         {"crunch": 0.0, "open": [], "on_time": 0, "late": 0, "recent": []})
        self.assertEqual(data["today"], {"cap_min": 240, "worked_min": 0, "plan": []})
        self.assertEqual(data["study"],
                         {"reviews": 0, "brier": None, "due_now": 0, "bins": [], "topics": [],
                          "held": 0, "due": []})
        self.assertEqual(data["bugs"],
                         {"fixed": 0, "open": 0, "abandoned": 0, "lost_min": 0,
                          "untagged": 0, "tags": [], "bursts": [], "recent": []})
        self.assertEqual(data["inbox_done"], [])
        json.dumps(data)

    def test_build_lists_acknowledged_inbox_entries(self):
        apply_inbox(self.c, [{"id": "a1", "op": "add", "title": "x", "est": "1h"}], NOW)
        data = build(self.c, NOW, [], [], 0.0)
        self.assertEqual(data["inbox_done"], [{"id": "a1"}])
        self.assertEqual(data["version"], 1)

    def test_session_days_and_peak(self):
        deep = add_task(self.c, "deep", 120, now=NOW, energy="deep")
        shallow = add_task(self.c, "shallow", 60, now=NOW, energy="shallow")
        start(self.c, deep, datetime(2026, 11, 8, 9, 30))
        stop(self.c, datetime(2026, 11, 8, 11, 0))
        start(self.c, shallow, datetime(2026, 11, 8, 14, 0))
        stop(self.c, datetime(2026, 11, 8, 14, 30))
        data = build(self.c, NOW, [], [], 0.0)
        self.assertEqual(data["days"]["2026-11-08"],
                         {"min": 120, "deep": 90, "peak": 90, "reviews": 0, "recalled": 0,
                          "fails": 0, "fixes": 0, "study": 120})

    def test_peak_window_overlap(self):
        t = add_task(self.c, "deep", 60, now=NOW)
        start(self.c, t, datetime(2026, 11, 8, 11, 30))
        stop(self.c, datetime(2026, 11, 8, 12, 30))
        day = build(self.c, NOW, [], [], 0.0)["days"]["2026-11-08"]
        self.assertEqual((day["deep"], day["peak"]), (60, 30))

    def test_peak_window_ending_at_midnight(self):
        set_setting(self.c, "peak", "21-24")
        t = add_task(self.c, "deep", 60, now=NOW)
        start(self.c, t, datetime(2026, 11, 8, 22, 30))
        stop(self.c, datetime(2026, 11, 8, 23, 30))
        day = build(self.c, NOW, [], [], 0.0)["days"]["2026-11-08"]
        self.assertEqual((day["deep"], day["peak"]), (60, 60))

    def test_running_session_counts_to_now(self):
        t = add_task(self.c, "deep", 60, now=datetime(2026, 11, 9, 12, 0))
        start(self.c, t, datetime(2026, 11, 9, 12, 0))
        data = build(self.c, NOW, [], [], 0.0)
        self.assertEqual(data["days"]["2026-11-09"]["min"], 60)

    def test_late_done_task(self):
        t = add_task(self.c, "late", 60, now=NOW, due=date(2026, 11, 5))
        log_time(self.c, t, 30, datetime(2026, 11, 6, 10, 0))
        done(self.c, t, datetime(2026, 11, 6, 12, 0))
        data = build(self.c, NOW, [], [], 0.0)
        self.assertEqual((data["deadlines"]["late"], data["deadlines"]["on_time"]), (1, 0))
        self.assertTrue(data["deadlines"]["recent"][0]["late"])

    def test_study_due_now_uses_the_new_item_cap(self):
        topic = add_topic(self.c, "paging", course="os")
        for i in range(12):
            add_item(self.c, topic, Path("/notes/os.md"), f"h{i}", now=NOW)
        data = build(self.c, NOW, [], [], 0.0)
        self.assertEqual(data["study"]["due_now"], 10)

    def test_study_and_code_days(self):
        topic = add_topic(self.c, "paging", course="os", exam_date=date(2026, 12, 1), weight=2)
        item = add_item(self.c, topic, Path("/notes/os.md"), None, now=NOW)
        record_review(self.c, item, 3, 0.8, datetime(2026, 11, 8, 10, 0))
        record_review(self.c, item, 1, 0.6, datetime(2026, 11, 8, 11, 0))
        record_run(self.c, "make", "/tmp/p", datetime(2026, 11, 8, 12, 0), 1.0, 2, None, None)
        record_run(self.c, "make", "/tmp/p", datetime(2026, 11, 8, 13, 0), 1.0, 0, None, None)
        data = build(self.c, NOW, [], [], 0.0)
        day = data["days"]["2026-11-08"]
        self.assertEqual((day["reviews"], day["recalled"], day["fails"], day["fixes"]), (2, 1, 1, 1))
        self.assertEqual(data["study"]["reviews"], 2)
        self.assertIsNotNone(data["study"]["brier"])
        self.assertEqual(len(data["study"]["bins"]), 2)
        t = data["study"]["topics"][0]
        self.assertEqual((t["course"], t["name"], t["exam"], t["weight"]),
                         ("os", "paging", "2026-12-01", 2.0))
        self.assertGreater(t["mastery"], 0)
        self.assertEqual((data["bugs"]["fixed"], data["bugs"]["open"]), (1, 0))

    def test_bug_prog_hides_paths(self):
        record_run(self.c, "/usr/bin/make -j4", "/home/u/proj", NOW, 1.0, 1, None, None)
        data = build(self.c, NOW, [], [], 0.0)
        self.assertEqual(data["bugs"]["recent"][0]["prog"], "make")
        text = json.dumps(data)
        self.assertNotIn("/home", text)
        self.assertNotIn("/usr", text)

    def test_empty_bug_command_has_no_prog(self):
        record_run(self.c, "", "/tmp/p", NOW, 1.0, 1, None, None)
        data = build(self.c, NOW, [], [], 0.0)
        self.assertEqual(data["bugs"]["recent"][0]["prog"], "")
        json.dumps(data)

    def test_open_deadlines_follow_risks(self):
        t = add_task(self.c, "OS lab 3", 120, now=NOW, course="os", due=date(2026, 11, 12))
        tasks = open_tasks(self.c, NOW)
        data = build(self.c, NOW, tasks, [TaskRisk(t, 0.4, date(2026, 11, 10), False)], 0.31)
        self.assertEqual(data["deadlines"]["crunch"], 0.31)
        self.assertEqual(data["deadlines"]["open"],
                         [{"title": "OS lab 3", "course": "os", "due": "2026-11-12",
                           "p_late": 0.4, "start_by": "2026-11-10", "behind": False}])

    def test_today_plan_and_worked_minutes(self):
        t = add_task(self.c, "OS lab 3", 240, now=NOW, course="os",
                     due=date(2026, 11, 12), energy="deep", first_step="open the handout")
        log_time(self.c, t, 45, NOW)
        data = build(self.c, NOW, open_tasks(self.c, NOW), [], 0.0)
        self.assertEqual(data["today"]["worked_min"], 45)
        entry = data["today"]["plan"][0]
        self.assertEqual(entry["id"], t)
        self.assertEqual(entry["title"], "OS lab 3")
        self.assertEqual(entry["course"], "os")
        self.assertGreater(entry["minutes"], 0)
        self.assertEqual(entry["energy"], "deep")
        self.assertEqual(entry["due"], "2026-11-12")
        self.assertFalse(entry["behind"])
        self.assertEqual(entry["first"], "open the handout")

    def test_today_plan_for_an_undated_task(self):
        t = add_task(self.c, "read notes", 30, now=NOW, energy="shallow")
        data = build(self.c, NOW, open_tasks(self.c, NOW), [], 0.0)
        entry = data["today"]["plan"][0]
        self.assertEqual(entry["id"], t)
        self.assertIsNone(entry["due"])
        self.assertFalse(entry["behind"])
        self.assertIsNone(entry["course"])
        self.assertIsNone(entry["first"])

    def test_study_due_items_carry_note_address_and_title(self):
        notes = tempfile.TemporaryDirectory()
        self.addCleanup(notes.cleanup)
        base = Path(notes.name)
        page = base / "os" / "paging.md"
        page.parent.mkdir()
        page.write_text("# Paging\n\n## TLB\n\nText.\n")
        set_setting(self.c, "notes_dir", str(base))
        topic = add_topic(self.c, "paging", course="os")
        heading = add_item(self.c, topic, page, "TLB", now=NOW)
        whole = add_item(self.c, topic, page, None, now=NOW)
        prompted = add_item(self.c, topic, page, None, now=NOW, prompt="what is a TLB?")
        lines = add_item(self.c, topic, page, "L3-5", now=NOW)
        paged = add_item(self.c, topic, page, "p2", now=NOW)
        data = build(self.c, NOW, [], [], 0.0)
        due = {item["id"]: item for item in data["study"]["due"]}
        self.assertEqual(due[heading], {"id": heading, "topic": "paging",
                                        "title": "TLB", "url": "/os/paging/#tlb"})
        self.assertEqual((due[whole]["title"], due[whole]["url"]),
                         ("paging", "/os/paging/"))
        self.assertEqual((due[prompted]["title"], due[prompted]["url"]),
                         ("what is a TLB?", "/os/paging/"))
        self.assertEqual((due[lines]["title"], due[lines]["url"]),
                         ("paging", "/os/paging/"))
        self.assertEqual((due[paged]["title"], due[paged]["url"]),
                         ("paging", "/os/paging/"))
        text = json.dumps(data)
        self.assertNotIn(str(base), text)
        self.assertNotIn(str(page), text)

    def test_study_due_hides_files_outside_notes_dir(self):
        notes = tempfile.TemporaryDirectory()
        self.addCleanup(notes.cleanup)
        set_setting(self.c, "notes_dir", notes.name)
        topic = add_topic(self.c, "paging", course="os")
        secret = Path("/tmp/elsewhere/secret-plan.md")
        item = add_item(self.c, topic, secret, None, now=NOW)
        data = build(self.c, NOW, [], [], 0.0)
        self.assertEqual(data["study"]["due"],
                         [{"id": item, "topic": "paging",
                           "title": f"item #{item}", "url": None}])
        text = json.dumps(data)
        self.assertNotIn("secret-plan", text)
        self.assertNotIn(str(secret), text)

    def test_study_due_lists_at_most_thirty_items(self):
        set_setting(self.c, "new_per_day", "30")
        topic = add_topic(self.c, "paging")
        for i in range(35):
            add_item(self.c, topic, Path(f"/notes/{i}.md"), f"h{i}", now=NOW)
        data = build(self.c, NOW, [], [], 0.0)
        self.assertEqual(len(data["study"]["due"]), 30)
        self.assertEqual(data["study"]["held"], 5)


class TestPush(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.netrc = Path(self.d.name) / "netrc"
        self.netrc.write_text("machine x.dev login u password p\n")
        os.chmod(self.netrc, 0o600)
        self.data = build(self.c, NOW, [], [], 0.0)

    def test_push_reports_an_invalid_url(self):
        with mock.patch("pm.stats.urlopen", side_effect=InvalidURL("bad port")):
            with self.assertRaisesRegex(ValueError, "push failed: bad port"):
                push(self.data, "https://x.dev", self.netrc)

    def test_push_reports_a_read_timeout(self):
        with mock.patch("pm.stats.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaisesRegex(ValueError, "push failed: timed out"):
                push(self.data, "https://x.dev", self.netrc)

    def test_push_is_a_put_to_api_pm(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b""
        with mock.patch("pm.stats.urlopen", return_value=response) as opener:
            sent = push(self.data, "https://x.dev/", self.netrc)
        sent_request = opener.call_args.args[0]
        self.assertEqual((sent_request.get_method(), sent_request.full_url),
                         ("PUT", "https://x.dev/api/pm"))
        self.assertEqual(sent, len(sent_request.data))

    def test_request_names_the_operation_in_its_error(self):
        with mock.patch("pm.stats.urlopen", side_effect=URLError("offline")):
            with self.assertRaisesRegex(ValueError, "notes failed: offline"):
                request("https://x.dev", "/api/x", self.netrc, what="notes")


class TestPullNotes(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.netrc = Path(self.d.name) / "netrc"
        self.netrc.write_text("machine x.dev login u password p\n")
        os.chmod(self.netrc, 0o600)

    def pull(self, body: bytes, url: str = "https://x.dev"):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = body
        with mock.patch("pm.stats.urlopen", return_value=response) as opener:
            result = pull_site(url, self.netrc)[0]
        return result, opener

    def test_sums_subjects_and_drops_days_under_a_minute(self):
        body = json.dumps({"study.time": json.dumps({
            "2026-11-09": {"os": 3_600_000, "math": 1_800_000},
            "2026-11-08": {"os": 20_000, "math": 10_000},
        })}).encode()
        result, opener = self.pull(body)
        self.assertEqual(result, {"2026-11-09": 90})
        sent_request = opener.call_args.args[0]
        self.assertEqual((sent_request.get_method(), sent_request.full_url),
                         ("GET", "https://x.dev/api/backup"))
        self.assertTrue(sent_request.get_header("Authorization").startswith("Basic "))

    def test_a_null_body_or_no_study_time_is_empty(self):
        self.assertEqual(self.pull(b"null")[0], {})
        self.assertEqual(self.pull(b'{"other": "x"}')[0], {})

    def test_rejects_unexpected_shapes(self):
        cases = [
            b"not json",
            b"[1]",
            b'"a string"',
            json.dumps({"study.time": 5}).encode(),
            json.dumps({"study.time": None}).encode(),
            json.dumps({"study.time": "not json"}).encode(),
            json.dumps({"study.time": "[]"}).encode(),
            json.dumps({"study.time": json.dumps({"2026-11-09": 5})}).encode(),
            json.dumps({"study.time": json.dumps({"2026-11-09": {"os": True}})}).encode(),
            json.dumps({"study.time": json.dumps({"2026-11-09": {"os": -1}})}).encode(),
            json.dumps({"study.time": json.dumps({"2026-11-09": {"os": "60"}})}).encode(),
            json.dumps({"study.time": json.dumps({"2026-11-09": {"os": float("nan")}})}).encode(),
        ]
        for body in cases:
            with self.subTest(body=body):
                with self.assertRaisesRegex(ValueError, "pull failed: unexpected backup shape"):
                    self.pull(body)

    def test_keeps_only_the_400_newest_days(self):
        start = date(2025, 1, 1)
        days = {(start + timedelta(days=n)).isoformat(): {"os": 60_000} for n in range(450)}
        body = json.dumps({"study.time": json.dumps(days)}).encode()
        result, _ = self.pull(body)
        self.assertEqual(len(result), 400)
        self.assertEqual(min(result), (start + timedelta(days=50)).isoformat())
        self.assertEqual(max(result), (start + timedelta(days=449)).isoformat())

    def test_http_401_mentions_netrc(self):
        error = HTTPError("https://x.dev/api/backup", 401, "Unauthorized", {}, None)
        with mock.patch("pm.stats.urlopen", side_effect=error):
            with self.assertRaisesRegex(ValueError, r"pull failed: HTTP 401 \(check ~/.netrc\)"):
                pull_site("https://x.dev", self.netrc)

    def test_network_error_uses_the_pull_prefix(self):
        with mock.patch("pm.stats.urlopen", side_effect=URLError("offline")):
            with self.assertRaisesRegex(ValueError, "pull failed: offline"):
                pull_site("https://x.dev", self.netrc)

    def test_a_plain_http_url_is_refused_before_the_network(self):
        with mock.patch("pm.stats.urlopen") as opener:
            with self.assertRaisesRegex(ValueError, "notes_url must start with https://"):
                pull_site("http://x.dev", self.netrc)
        opener.assert_not_called()


class TestFetchInbox(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.netrc = Path(self.d.name) / "netrc"
        self.netrc.write_text("machine x.dev login u password p\n")
        os.chmod(self.netrc, 0o600)

    def fetch(self, body: bytes):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = body
        with mock.patch("pm.stats.urlopen", return_value=response) as opener:
            result = fetch_inbox("https://x.dev", self.netrc)
        return result, opener

    def test_null_is_empty_and_items_come_back(self):
        self.assertEqual(self.fetch(b"null")[0], [])
        self.assertEqual(self.fetch(b'{"items": [{"id": "a"}]}')[0], [{"id": "a"}])
        self.assertEqual(self.fetch(b'{"items": []}')[0], [])

    def test_requests_the_inbox_route(self):
        _, opener = self.fetch(b"null")
        sent_request = opener.call_args.args[0]
        self.assertEqual((sent_request.get_method(), sent_request.full_url),
                         ("GET", "https://x.dev/api/pm-inbox"))
        self.assertTrue(sent_request.get_header("Authorization").startswith("Basic "))

    def test_rejects_unexpected_shapes(self):
        cases = [b"", b"not json", b"[1]", b'"a string"', b"5",
                 b'{"items": 5}', b'{"items": "x"}', b'{"other": []}']
        for body in cases:
            with self.subTest(body=body):
                with self.assertRaisesRegex(ValueError, "inbox failed: unexpected shape"):
                    self.fetch(body)

    def test_http_error_uses_the_inbox_prefix(self):
        error = HTTPError("https://x.dev/api/pm-inbox", 404, "Not Found", {}, None)
        with mock.patch("pm.stats.urlopen", side_effect=error):
            with self.assertRaisesRegex(ValueError, "inbox failed: HTTP 404"):
                fetch_inbox("https://x.dev", self.netrc)
        error.close()


class TestNotesMinutes(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)

    def test_round_trips(self):
        save_notes(self.c, {"2026-11-09": 90, "2026-11-08": 15})
        self.assertEqual(notes_minutes(self.c), {"2026-11-08": 15, "2026-11-09": 90})

    def test_missing_or_bad_values_are_empty(self):
        self.assertEqual(notes_minutes(self.c), {})
        for value in ("garbage", "[]", '"x"', '{"2026-11-09": "90"}',
                      '{"2026-11-09": -1}', '{"2026-11-09": true}', '{"2026-11-09": 1.5}'):
            with self.subTest(value=value):
                set_setting(self.c, "notes_time", value)
                self.assertEqual(notes_minutes(self.c), {})


class TestPullSite(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.netrc = Path(self.d.name) / "netrc"
        self.netrc.write_text("machine x.dev login u password p\n")
        os.chmod(self.netrc, 0o600)

    def pull(self, spans):
        backup = {"study.time": json.dumps({"2026-11-09": {"os": 3_600_000}})}
        if spans is not None:
            backup["study.spans"] = spans
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(backup).encode()
        with mock.patch("pm.stats.urlopen", return_value=response) as opener:
            result = pull_site("https://x.dev", self.netrc)
        self.assertEqual(opener.call_count, 1)  # one request for both
        return result

    def test_minutes_and_stretches_come_from_one_reply(self):
        spans = json.dumps({"2026-11-09": [[540, 600], [610, 615]], "2026-11-08": [[0, 1440]]})
        self.assertEqual(self.pull(spans), ({"2026-11-09": 60},
                                            {"2026-11-08": [[0, 1440]], "2026-11-09": [[540, 600], [610, 615]]}))

    def test_no_stretches_is_an_old_site(self):
        self.assertEqual(self.pull(None), ({"2026-11-09": 60}, {}))

    def test_bad_stretches_never_fail_the_pull(self):
        for spans in (5, ["x"], "not json", "[]", '"x"', json.dumps({"2026-11-09": "x"})):
            with self.subTest(spans=spans):
                self.assertEqual(self.pull(spans), ({"2026-11-09": 60}, {}))

    def test_a_number_too_long_to_read_or_a_week_date_is_not_a_stretch(self):
        self.assertEqual(self.pull('{"2026-11-09": [[0, ' + "9" * 5000 + "]]}"), ({"2026-11-09": 60}, {}))
        self.assertEqual(self.pull(json.dumps({"2026-W45-1": [[0, 5]], "20261109": [[0, 5]]})), ({"2026-11-09": 60}, {}))

    def test_a_bad_day_is_dropped_and_the_rest_kept(self):
        good = [[540, 600]]
        for bad in ([[600, 540]], [[5, 5]], [[-1, 10]], [[10, 1441]], [[1.5, 3]], [[True, 3]], [[1, 2, 3]],
                    [[100, 200], [150, 300]], [[i, i + 1] for i in range(0, 602, 2)], "x", [5]):
            with self.subTest(bad=bad):
                spans = json.dumps({"2026-11-09": good, "2026-11-08": bad, "nonsense": good})
                self.assertEqual(self.pull(spans)[1], {"2026-11-09": good})


class TestSiteClock(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)
        self.day = "2026-11-09"

    def work(self, begin: tuple[int, int], end: tuple[int, int] | None):
        task = add_task(self.c, "read", 600, now=NOW)
        start(self.c, task, datetime(2026, 11, 9, *begin))
        if end:
            stop(self.c, datetime(2026, 11, 9, *end))

    def site(self, minutes: int, spans=None):
        save_notes(self.c, {self.day: minutes})
        if spans is not None:
            save_spans(self.c, {self.day: spans})

    def test_nothing_is_empty(self):
        self.assertEqual(combined(self.c, NOW), {})

    def test_one_clock_alone(self):
        self.work((10, 0), (11, 0))
        self.assertEqual(combined(self.c, NOW), {self.day: 60})
        self.c.execute("DELETE FROM sessions")
        self.site(45, [[540, 585]])
        self.assertEqual(combined(self.c, NOW), {self.day: 45})

    def test_without_stretches_a_day_is_the_larger_clock(self):
        self.work((10, 0), (11, 0))
        self.site(90)
        self.assertEqual(combined(self.c, NOW), {self.day: 90})

    def test_time_apart_adds_up(self):
        self.work((10, 0), (11, 0))
        self.site(60, [[540, 600]])
        self.assertEqual(combined(self.c, NOW), {self.day: 120})

    def test_time_together_counts_once(self):
        self.work((10, 0), (11, 0))
        self.site(60, [[600, 660]])
        self.assertEqual(combined(self.c, NOW), {self.day: 60})

    def test_a_partial_overlap_counts_the_rest(self):
        self.work((10, 0), (11, 0))
        self.site(60, [[630, 690]])
        self.assertEqual(combined(self.c, NOW), {self.day: 90})

    def test_logged_time_over_a_session_never_takes_more_than_either_clock(self):
        self.work((10, 0), (11, 0))
        log_time(self.c, add_task(self.c, "more", 600, now=NOW), 180, NOW)  # 10:00-13:00, over the session
        self.site(30, [[600, 780]])  # stretches say 3h, the site's total says 30m
        self.assertEqual(combined(self.c, NOW), {self.day: 240})  # pm 240 + site 30 - overlap 30

    def test_site_time_the_stretches_do_not_cover_is_never_counted_twice(self):
        # the day the site starts recording: 3h on its clock, stretches for the last hour only
        self.work((8, 0), (9, 0))
        self.site(180, [[600, 660]])
        self.assertEqual(combined(self.c, NOW), {self.day: 180})  # the timer hour may sit inside the unrecorded 2h
        self.work((10, 0), (10, 30))
        self.assertEqual(combined(self.c, NOW), {self.day: 180})  # 90m of timer, at most 120 + 30 of it shared

    def test_a_session_past_midnight_meets_the_next_days_stretches(self):
        task = add_task(self.c, "late", 600, now=NOW)
        start(self.c, task, datetime(2026, 11, 8, 23, 0))
        stop(self.c, datetime(2026, 11, 9, 1, 0))
        self.assertEqual(combined(self.c, NOW), {"2026-11-08": 60, "2026-11-09": 60})  # cut at midnight
        save_notes(self.c, {"2026-11-08": 60, "2026-11-09": 60})  # the site clock ran over the same two hours
        save_spans(self.c, {"2026-11-08": [[1380, 1440]], "2026-11-09": [[0, 60]]})
        self.assertEqual(combined(self.c, NOW), {"2026-11-08": 60, "2026-11-09": 60})
        days = build(self.c, NOW, [], [], 0.0)["days"]
        self.assertEqual((days["2026-11-08"]["min"], days["2026-11-08"]["study"]), (120, 60))  # min: the timer, on its start day

    def test_logged_time_has_no_place_in_the_day_so_it_never_adds_to_site_time(self):
        self.site(60, [[540, 600]])  # read on the site 9:00-10:00
        log_time(self.c, add_task(self.c, "that reading", 600, now=NOW), 60, NOW)  # logged for the task at 13:00
        self.assertEqual(combined(self.c, NOW), {self.day: 60})
        self.work((10, 0), (11, 0))  # a timed hour apart from both still adds
        self.assertEqual(combined(self.c, NOW), {self.day: 120})

    def test_logged_time_alone_counts_in_full(self):
        log_time(self.c, add_task(self.c, "textbook", 600, now=NOW), 90, NOW)
        self.assertEqual(combined(self.c, NOW), {self.day: 90})

    def test_an_open_session_counts_up_to_now(self):
        self.work((12, 0), None)
        self.site(60, [[720, 780]])
        self.assertEqual(combined(self.c, NOW), {self.day: 60})

    def test_a_larger_learnharness_day_wins(self):
        self.work((10, 0), (11, 0))
        self.site(60, [[540, 600]])
        self.c.execute("INSERT INTO lh_days(chat_id, day, minutes) VALUES('chat_a', ?, 200)", (self.day,))
        self.assertEqual(combined(self.c, NOW), {self.day: 200})

    def test_stored_stretches_survive_a_pull_without_their_day(self):
        save_spans(self.c, {"2026-11-08": [[1, 2]], self.day: [[3, 4]]})
        save_spans(self.c, {self.day: [[5, 6]]})
        self.assertEqual(site_spans(self.c), {"2026-11-08": [[1, 2]], self.day: [[5, 6]]})

    def test_only_the_newest_400_days_of_stretches_are_kept(self):
        first = date(2025, 1, 1)
        save_spans(self.c, {(first + timedelta(days=i)).isoformat(): [[0, 1]] for i in range(401)})
        kept = site_spans(self.c)
        self.assertEqual(len(kept), 400)
        self.assertNotIn("2025-01-01", kept)

    def test_bad_stored_stretches_are_no_stretches(self):
        self.work((10, 0), (11, 0))
        save_notes(self.c, {self.day: 90})
        for value in ("garbage", "[]", '{"2026-11-09": [[5, 1]]}'):
            with self.subTest(value=value):
                set_setting(self.c, "notes_spans", value)
                self.assertEqual(site_spans(self.c), {})
                self.assertEqual(combined(self.c, NOW), {self.day: 90})

    def test_build_carries_the_combined_minutes(self):
        self.work((10, 0), (11, 0))
        self.site(60, [[540, 600]])
        save_notes(self.c, {self.day: 60, "2026-11-07": 30})
        days = build(self.c, NOW, [], [], 0.0)["days"]
        self.assertEqual((days[self.day]["min"], days[self.day]["study"]), (60, 120))
        self.assertEqual((days["2026-11-07"]["min"], days["2026-11-07"]["study"]), (0, 30))
