import json
import os
import shutil
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from urllib.parse import parse_qs, quote, urlsplit

from pm import api, lh, stats
from pm.bugs import record_run, set_tags
from pm.db import DEFAULTS, connect, get_setting, set_setting
from pm.excerpt import Section
from pm.files import scan
from pm.stats import save_notes
from pm.study import add_item, add_topic
from pm.tasks import log_time, start

NOW = datetime(2026, 11, 9, 10, 0)


class ApiCase(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        api._CACHE.clear()

    def tearDown(self):
        self.c.close()
        api._CACHE.clear()

    def call(self, method, path, body=None, now=NOW):
        target = urlsplit(path)
        query = {key: values[-1] for key, values in parse_qs(target.query).items()}
        return api.handle(self.c, method, target.path, query, body or {}, now)

    def add(self, title="OS lab", est="4h", **body):
        code, data = self.call("POST", "/api/tasks", {"title": title, "est": est, **body})
        self.assertEqual(code, 200, data)
        return data["id"]

    def state(self, now=NOW):
        code, data = self.call("GET", "/api/state", now=now)
        self.assertEqual(code, 200, data)
        return data


class TestApi(ApiCase):
    def test_ping(self):
        self.assertEqual(self.call("GET", "/api/ping"), (200, {"pm": True}))

    def test_empty_state(self):
        body = self.state()
        self.assertEqual(set(body), {"now", "running", "tasks", "today", "crunch",
                                     "reviews_due", "new_per_day", "courses", "kinds",
                                     "llm", "spots", "exam", "lh", "tutor"})
        self.assertEqual(body["now"], "2026-11-09T10:00:00")
        self.assertIsNone(body["running"])
        self.assertEqual(body["tasks"], [])
        self.assertEqual(body["crunch"], 0.0)
        self.assertEqual(body["today"], {"cap_min": 240, "worked_min": 0, "peak": "09-12",
                                         "plan": [], "unrated": False, "peak_hint": None})
        self.assertEqual((body["llm"], body["spots"]), (False, 0))
        self.assertEqual((body["reviews_due"], body["new_per_day"]), (0, 10))
        self.assertEqual((body["courses"], body["kinds"]), ([], []))

    def test_reviews_due_respects_the_daily_cap_on_new_items(self):
        topic_id = add_topic(self.c, "BFS")
        for n in range(12):
            add_item(self.c, topic_id, Path("/n.md"), f"h{n}", now=NOW)
        self.assertEqual(self.state()["reviews_due"], 10)

    def test_add_task_and_state(self):
        code, data = self.call("POST", "/api/tasks",
                               {"title": "OS lab", "est": "4h", "due": "+3",
                                "course": "os", "kind": "lab", "first": "open it"})
        self.assertEqual((code, data), (200, {"id": 1}))
        body = self.state()
        [task] = body["tasks"]
        self.assertEqual(set(task), {"id", "title", "course", "kind", "est_min", "due", "energy",
                                     "first_step", "logged_min", "running", "note", "p_late",
                                     "start_by", "behind", "links"})
        self.assertEqual(task["links"], [])
        self.assertEqual(task["est_min"], 240)
        self.assertEqual(task["due"], "2026-11-12")
        self.assertEqual((task["course"], task["kind"], task["first_step"]), ("os", "lab", "open it"))
        self.assertEqual(task["energy"], "deep")
        self.assertIsInstance(task["p_late"], float)
        self.assertTrue(0 <= task["p_late"] <= 1)
        self.assertEqual((body["courses"], body["kinds"]), (["os"], ["lab"]))

    def test_courses_and_kinds_include_open_and_finished_tasks(self):
        task_id = self.add(course="os", kind="lab")
        self.add(title="db", est="1h", course="dbms", kind="hw")
        self.call("POST", f"/api/tasks/{task_id}/done")
        body = self.state()
        self.assertEqual((body["courses"], body["kinds"]), (["dbms", "os"], ["hw", "lab"]))

    def test_dropped_task_is_not_suggested_for_autocomplete(self):
        task_id = self.add(course="os", kind="lab")
        self.call("POST", f"/api/tasks/{task_id}/drop")
        body = self.state()
        self.assertEqual((body["courses"], body["kinds"]), ([], []))

    def test_state_leaves_no_transaction_open(self):
        self.add()
        self.state()
        self.assertFalse(self.c.in_transaction)

    def test_add_defaults(self):
        self.add(title="plain")
        [task] = self.state()["tasks"]
        self.assertEqual((task["kind"], task["energy"], task["due"], task["course"]),
                         ("task", "deep", None, None))
        self.assertIsNone(task["p_late"])
        self.assertIsNone(task["start_by"])
        self.assertIsNone(task["behind"])

    def test_add_errors(self):
        cases = [
            ({"title": "a"}, "give an estimate, like 90m or 2h"),
            ({"title": "a", "est": "soon"}, "bad duration"),
            ({"title": "  ", "est": "1h"}, "title must be 1-200 characters"),
            ({"title": "x" * 201, "est": "1h"}, "title must be 1-200 characters"),
            ({"title": 5, "est": "1h"}, "title must be 1-200 characters"),
            ({"title": "a", "est": "1h", "due": "someday"}, "bad date"),
            ({"title": "a", "est": "90"}, "give a unit: 90m or 90h"),
            ({"title": "a", "est": "1h", "kind": " "}, "kind can't be empty"),
            ({"title": "a", "est": "1h", "energy": "bad"}, "energy must be deep or shallow"),
        ]
        for body, message in cases:
            with self.subTest(body=body):
                code, data = self.call("POST", "/api/tasks", body)
                self.assertEqual(code, 400)
                self.assertIn(message, data["error"])
        self.assertEqual(self.state()["tasks"], [])

    def test_wrong_types_are_400_and_change_nothing(self):
        cases = [
            ("POST", "/api/tasks", {"title": "a", "est": 90}, "est must be text"),
            ("POST", "/api/tasks", {"title": "a", "est": "1h", "due": 3}, "due must be text"),
            ("POST", "/api/tasks", {"title": "a", "est": "1h", "course": 2}, "course must be text"),
            ("POST", "/api/tasks", {"title": "a", "est": "1h", "kind": 2}, "kind must be text"),
            ("POST", "/api/tasks", {"title": "a", "est": "1h", "energy": []}, "energy must be text"),
            ("POST", "/api/tasks", {"title": "a", "est": "1h", "first": {}}, "first must be text"),
            ("POST", "/api/stop", {"note": ["x"]}, "note must be text"),
            ("POST", "/api/stop", {"as": 2}, "as must be text"),
            ("POST", "/api/tasks/1/log", {"duration": 30}, "duration must be text"),
        ]
        for method, path, body, message in cases:
            with self.subTest(body=body):
                code, data = self.call(method, path, body)
                self.assertEqual(code, 400)
                self.assertEqual(data, {"error": message})
        self.assertEqual(self.state()["tasks"], [])

    def test_edit_title_is_never_served_from_the_cache(self):
        task_id = self.add(due="+3")
        self.state()
        self.assertEqual(self.call("POST", f"/api/tasks/{task_id}/edit", {"title": "new"}),
                         (200, {}))
        self.assertEqual(self.state()["tasks"][0]["title"], "new")

    def test_edit_energy_does_not_rerun_simulate(self):
        task_id = self.add(due="+3")
        self.state()
        with mock.patch("pm.api.simulate", wraps=api.simulate) as sim:
            self.assertEqual(self.call("POST", f"/api/tasks/{task_id}/edit",
                                       {"energy": "shallow"}), (200, {}))
            self.assertEqual(self.state()["tasks"][0]["energy"], "shallow")
            self.assertEqual(sim.call_count, 0)

    def test_edit_clears_due_and_locks_the_estimate(self):
        task_id = self.add(due="+3")
        self.assertEqual(self.call("POST", f"/api/tasks/{task_id}/edit", {"due": ""}), (200, {}))
        self.assertIsNone(self.state()["tasks"][0]["due"])
        self.call("POST", f"/api/tasks/{task_id}/log", {"duration": "30m"})
        code, data = self.call("POST", f"/api/tasks/{task_id}/edit", {"est": "5h"})
        self.assertEqual(code, 400)
        self.assertIn("locked", data["error"])

    def test_edit_clears_course_and_first_step(self):
        task_id = self.add(course="os", first="open it")
        self.assertEqual(self.call("POST", f"/api/tasks/{task_id}/edit",
                                   {"course": "", "first": ""}), (200, {}))
        [task] = self.state()["tasks"]
        self.assertEqual((task["course"], task["first_step"]), (None, None))

    def test_edit_rejects_a_blank_kind(self):
        task_id = self.add()
        self.assertEqual(self.call("POST", f"/api/tasks/{task_id}/edit", {"kind": " "}),
                         (400, {"error": "kind can't be empty"}))

    def test_start_then_state_shows_elapsed_and_worked(self):
        task_id = self.add()
        self.assertEqual(self.call("POST", f"/api/tasks/{task_id}/start"), (200, {}))
        body = self.state(NOW + timedelta(minutes=45))
        self.assertEqual(body["running"], {"task_id": task_id,
                                           "start": "2026-11-09T10:00:00",
                                           "elapsed_s": 2700})
        self.assertEqual(body["today"]["worked_min"], 45)
        self.assertTrue(body["tasks"][0]["running"])

    def test_stop_saves_note_and_a_second_stop_is_a_400(self):
        task_id = self.add()
        start(self.c, task_id, NOW)
        later = NOW + timedelta(minutes=45)
        self.assertEqual(self.call("POST", "/api/stop", {"note": "stuck on fork"}, later),
                         (200, {"task_id": task_id, "minutes": 45, "long": False}))
        self.assertEqual(self.state(later)["tasks"][0]["note"], "stuck on fork")
        self.assertEqual(self.call("POST", "/api/stop", now=later),
                         (400, {"error": "nothing running"}))

    def test_long_session_and_stop_as(self):
        task_id = self.add()
        start(self.c, task_id, NOW)
        seven = NOW + timedelta(hours=7)
        self.assertEqual(self.call("POST", "/api/stop", now=seven),
                         (200, {"task_id": task_id, "minutes": 420, "long": True}))
        self.assertEqual(self.state(seven)["tasks"][0]["logged_min"], 420)
        start(self.c, task_id, seven)
        code, data = self.call("POST", "/api/stop", {"as": "2h"}, seven + timedelta(hours=2))
        self.assertEqual((code, data), (200, {"task_id": task_id, "minutes": 120, "long": False}))
        self.assertEqual(self.state(seven + timedelta(hours=2))["tasks"][0]["logged_min"], 540)

    def test_log_duration(self):
        task_id = self.add(est="2h")
        self.assertEqual(self.call("POST", f"/api/tasks/{task_id}/log", {"duration": "30m"}),
                         (200, {}))
        self.assertEqual(self.state()["tasks"][0]["logged_min"], 30)

    def test_done_moves_the_task_to_finished_with_its_ratio(self):
        task_id = self.add(est="2h")
        self.call("POST", f"/api/tasks/{task_id}/log", {"duration": "30m"})
        self.assertEqual(self.call("POST", f"/api/tasks/{task_id}/done"), (200, {}))
        self.assertEqual(self.state()["tasks"], [])
        code, body = self.call("GET", "/api/finished")
        self.assertEqual(code, 200)
        [task] = body["tasks"]
        self.assertEqual((task["id"], task["ratio"], task["late"], task["logged_min"]),
                         (task_id, 0.25, None, 30))
        self.assertEqual(task["done"], "2026-11-09T10:00:00")

    def test_finished_is_newest_first_and_caps_at_ten(self):
        ids = []
        for n in range(12):
            task_id = self.add(title=f"t{n}", est="1h")
            ids.append(task_id)
            self.call("POST", f"/api/tasks/{task_id}/done", now=NOW + timedelta(minutes=n))
        tasks = self.call("GET", "/api/finished")[1]["tasks"]
        self.assertEqual([t["id"] for t in tasks], list(reversed(ids))[:10])
        self.assertIsNone(tasks[0]["ratio"])

    def test_finished_late(self):
        on_time = self.add(title="on time", est="1h", due="+1")
        self.call("POST", f"/api/tasks/{on_time}/done")
        late = self.add(title="late", est="1h", due="2026-11-09")
        self.call("POST", f"/api/tasks/{late}/done", now=NOW + timedelta(days=1))
        tasks = {t["id"]: t for t in self.call("GET", "/api/finished")[1]["tasks"]}
        self.assertIs(tasks[on_time]["late"], False)
        self.assertIs(tasks[late]["late"], True)

    def test_drop_leaves_the_state_and_is_not_finished(self):
        task_id = self.add()
        self.assertEqual(self.call("POST", f"/api/tasks/{task_id}/drop"), (200, {}))
        self.assertEqual(self.state()["tasks"], [])
        self.assertEqual(self.call("GET", "/api/finished"), (200, {"tasks": []}))

    def test_tasks_are_ordered_by_due_then_id(self):
        later = self.add(title="later", est="1h", due="+5")
        none = self.add(title="none", est="1h")
        soon = self.add(title="soon", est="1h", due="+1")
        self.assertEqual([t["id"] for t in self.state()["tasks"]], [soon, later, none])

    def test_route_errors(self):
        self.assertEqual(self.call("POST", "/api/tasks/99/start"),
                         (404, {"error": "no task #99"}))
        self.assertEqual(self.call("POST", "/api/tasks/x/start"),
                         (404, {"error": "no such route"}))
        self.assertEqual(self.call("GET", "/api/tasks"), (405, {"error": "use POST"}))
        self.assertEqual(self.call("POST", "/api/state"), (405, {"error": "use GET"}))
        self.assertEqual(self.call("GET", "/api/nope"), (404, {"error": "no such route"}))

    def test_state_caches_simulate_until_its_inputs_change(self):
        task_id = self.add(due="+3")
        with mock.patch("pm.api.simulate", wraps=api.simulate) as sim:
            self.state()
            self.state()
            self.assertEqual(sim.call_count, 1)
            log_time(self.c, task_id, 10, NOW)
            self.state()
            self.assertEqual(sim.call_count, 2)

    def test_state_is_json_serialisable(self):
        self.add(due="+3")
        self.call("POST", "/api/tasks/1/start")
        self.assertIsInstance(json.dumps(self.state(NOW + timedelta(minutes=5))), str)


class TestRiskApi(ApiCase):
    def risk(self, path="/api/risk"):
        code, data = self.call("GET", path)
        self.assertEqual(code, 200, data)
        return data

    def test_defaults_match_the_setting_and_state(self):
        self.add(due="+3", course="os")
        body = self.risk()
        self.assertEqual((body["today"], body["hours"], body["skip"], body["set_hours"]),
                         ("2026-11-09", 4.0, 0, 4.0))
        self.assertEqual(body["crunch"], body["base_crunch"])
        [task] = body["tasks"]
        self.assertEqual(set(task), {"id", "title", "course", "due", "p_late", "start_by",
                                     "behind", "finish_p50", "finish_p95", "late_days"})
        self.assertEqual((task["title"], task["course"], task["due"]),
                         ("OS lab", "os", "2026-11-12"))
        self.assertEqual(task["p_late"], self.state()["tasks"][0]["p_late"])
        self.assertEqual(body["start_queue_by"], task["start_by"])

    def test_fewer_hours_raise_crunch(self):
        self.add(due="+3")
        body = self.risk("/api/risk?hours=1")
        self.assertEqual(body["hours"], 1.0)
        self.assertGreaterEqual(body["crunch"], body["base_crunch"])

    def test_skip_moves_today_and_makes_the_task_late(self):
        self.add(due="+3")
        body = self.risk("/api/risk?skip=10")
        self.assertEqual((body["today"], body["skip"]), ("2026-11-19", 10))
        [task] = body["tasks"]
        self.assertEqual((task["p_late"], task["behind"]), (1.0, True))
        self.assertGreater(task["late_days"], 0)

    def test_hours_and_skip_boundaries_are_accepted(self):
        self.add(due="+3")
        for hours in ("0.1", "16"):
            with self.subTest(hours=hours):
                self.assertEqual(self.risk(f"/api/risk?hours={hours}")["hours"], float(hours))
        for skip in ("0", "60"):
            with self.subTest(skip=skip):
                self.assertEqual(self.risk(f"/api/risk?skip={skip}")["skip"], int(skip))

    def test_bad_hours_and_skip_are_400(self):
        cases = [
            ("hours=0", "hours must be between 0.1 and 16"),
            ("hours=abc", "hours must be between 0.1 and 16"),
            ("hours=17", "hours must be between 0.1 and 16"),
            ("hours=nan", "hours must be between 0.1 and 16"),
            ("hours=inf", "hours must be between 0.1 and 16"),
            ("skip=-1", "skip must be between 0 and 60"),
            ("skip=1.5", "skip must be between 0 and 60"),
            ("skip=abc", "skip must be between 0 and 60"),
            ("skip=61", "skip must be between 0 and 60"),
            (f"skip={quote('٣')}", "skip must be between 0 and 60"),
        ]
        for params, message in cases:
            with self.subTest(params=params):
                self.assertEqual(self.call("GET", f"/api/risk?{params}"),
                                 (400, {"error": message}))

    def test_what_if_never_writes_the_setting(self):
        self.add(due="+3")
        self.risk("/api/risk?hours=2&skip=4")
        self.assertEqual(get_setting(self.c, "hours_per_day", "4"), "4")
        self.assertEqual(self.call("GET", "/api/settings")[1]["values"]["hours_per_day"], "4")
        self.assertEqual(self.risk()["set_hours"], 4.0)

    def test_undated_tasks_are_counted_but_not_simulated(self):
        dated = self.add(due="+3")
        self.add(title="no due", est="1h")
        body = self.risk()
        self.assertEqual(body["undated"], 1)
        self.assertEqual([task["id"] for task in body["tasks"]], [dated])

    def test_no_dated_tasks(self):
        self.add(title="no due", est="1h")
        body = self.risk()
        self.assertEqual((body["tasks"], body["crunch"], body["start_queue_by"]),
                         ([], 0.0, None))
        self.assertEqual(body["undated"], 1)

    def test_cache_keeps_the_last_sixteen_forecasts(self):
        for skip in range(17):
            api._forecast(self.c, NOW, 240, skip)
            if skip == 0:
                first = next(iter(api._CACHE))
        self.assertEqual(len(api._CACHE), 16)
        self.assertNotIn(first, api._CACHE)


class TestStatsApi(ApiCase):
    def test_empty_stats(self):
        code, body = self.call("GET", "/api/stats")
        self.assertEqual(code, 200)
        self.assertEqual((body["version"], body["days"]), (1, {}))

    def test_stats_deadlines_match_state(self):
        self.add(due="+3")
        code, body = self.call("GET", "/api/stats")
        self.assertEqual(code, 200)
        [open_task] = body["deadlines"]["open"]
        self.assertEqual(open_task["p_late"], round(self.state()["tasks"][0]["p_late"], 3))

    def test_stats_carries_the_site_study_clock(self):
        save_notes(self.c, {"2026-11-09": 90})
        code, body = self.call("GET", "/api/stats")
        self.assertEqual(code, 200)
        self.assertEqual(body["notes"], {"2026-11-09": 90})
        self.assertEqual(body["version"], 1)

    def test_empty_stats_have_no_notes(self):
        code, body = self.call("GET", "/api/stats")
        self.assertEqual((code, body["notes"]), (200, {}))


BUG_DIFF = "@@ -1 +1 @@\n-for (i = 0; i <= n; i++)\n+for (i = 0; i < n; i++)\n"


class TestBugsApi(ApiCase):
    def record(self, cwd="/p", cmd="make test", start=NOW - timedelta(minutes=20), diff=BUG_DIFF):
        record_run(self.c, cmd, cwd, start, 1.0, 2, "a", None, lambda a, b: diff)
        record_run(self.c, cmd, cwd, start + timedelta(minutes=1), 2.5, 2, "b", None,
                   lambda a, b: diff)
        return record_run(self.c, cmd, cwd, start + timedelta(minutes=3), 1.0, 0, "c", None,
                          lambda a, b: diff)

    def test_empty_bugs(self):
        code, data = self.call("GET", "/api/bugs")
        self.assertEqual(code, 200)
        self.assertEqual(data["summary"], {
            "fixed": 0, "open": 0, "abandoned": 0, "lost_min": 0, "untagged": 0,
            "tags": [], "bursts": [],
        })
        self.assertEqual(data["episodes"], [])

    def test_bug_list_shape(self):
        ep = self.record()
        code, data = self.call("GET", "/api/bugs")
        self.assertEqual(code, 200)
        [row] = data["episodes"]
        self.assertEqual(row["id"], ep.id)
        self.assertEqual((row["cmd"], row["cwd"], row["status"]), ("make test", "/p", "fixed"))
        self.assertEqual(row["opened"], (NOW - timedelta(minutes=20)).isoformat(timespec="seconds"))
        self.assertEqual(row["closed"], (NOW - timedelta(minutes=17)).isoformat(timespec="seconds"))
        self.assertEqual((row["fails"], row["lost_min"]), (2, 3))
        self.assertEqual(row["tags"], ["off-by-one"])
        self.assertEqual(data["summary"]["fixed"], 1)
        self.assertEqual(data["summary"]["lost_min"], 3)

    def test_cwd_under_home_is_shown_with_a_tilde(self):
        with TemporaryDirectory() as d:
            home = Path(d)
            with mock.patch("pathlib.Path.home", return_value=home):
                self.record(cwd=str(home / "code"))
                code, data = self.call("GET", "/api/bugs")
        self.assertEqual(code, 200)
        self.assertEqual(data["episodes"][0]["cwd"], "~/code")

    def test_cwd_outside_home_is_kept_as_stored(self):
        with TemporaryDirectory() as d:
            (Path(d) / "real").mkdir()
            (Path(d) / "link").symlink_to(Path(d) / "real")
            with mock.patch("pathlib.Path.home", return_value=Path(d) / "home"):
                self.record(cwd=f"{d}/link")
                code, data = self.call("GET", "/api/bugs")
        self.assertEqual(data["episodes"][0]["cwd"], f"{d}/link")

    def test_open_episode_has_no_closed_time_and_lost_min_zero(self):
        record_run(self.c, "make", "/p", NOW - timedelta(minutes=5), 1.0, 1, "a", None, lambda a, b: b)
        code, data = self.call("GET", "/api/bugs")
        self.assertEqual(code, 200)
        [row] = data["episodes"]
        self.assertEqual((row["status"], row["closed"], row["lost_min"]), ("open", None, 0))

    def test_tag_filter_and_empty_tag_means_no_filter(self):
        one = self.record()
        two = self.record(cmd="pytest")
        set_tags(self.c, two.id, ["overflow"])
        code, data = self.call("GET", "/api/bugs?tag=off-by-one")
        self.assertEqual([ep["id"] for ep in data["episodes"]], [one.id])
        code, data = api.handle(self.c, "GET", "/api/bugs", {"tag": ""}, {}, NOW)
        self.assertEqual({ep["id"] for ep in data["episodes"]}, {one.id, two.id})

    def test_bug_detail_with_runs_and_diff(self):
        ep = self.record()
        code, data = self.call("GET", f"/api/bugs/{ep.id}")
        self.assertEqual(code, 200)
        self.assertEqual(data["diff"], BUG_DIFF)
        self.assertEqual([run["code"] for run in data["runs"]], [2, 2, 0])
        self.assertEqual([run["start"] for run in data["runs"]],
                         [(NOW - timedelta(minutes=20)).isoformat(timespec="seconds"),
                          (NOW - timedelta(minutes=19)).isoformat(timespec="seconds"),
                          (NOW - timedelta(minutes=17)).isoformat(timespec="seconds")])
        self.assertEqual([run["dur_s"] for run in data["runs"]], [1.0, 2.5, 1.0])

    def test_tag_edit_round_trip(self):
        ep = self.record()
        code, data = self.call("POST", f"/api/bugs/{ep.id}/tags", {"tags": ["Off By One"]})
        self.assertEqual(code, 400)
        self.assertIn("bad tag", data["error"])
        self.assertEqual(self.call("POST", f"/api/bugs/{ep.id}/tags",
                                   {"tags": ["overflow", "overflow"]}),
                         (200, {"tags": ["overflow"]}))
        self.assertEqual(self.call("POST", f"/api/bugs/{ep.id}/tags", {"tags": []}),
                         (200, {"tags": []}))
        self.assertEqual(self.call("POST", f"/api/bugs/{ep.id}/tags", {"tags": "x"}),
                         (400, {"error": "tags must be a list of names"}))

    def test_unknown_bug_is_404(self):
        self.assertEqual(self.call("GET", "/api/bugs/99"), (404, {"error": "no bug #99"}))
        self.assertEqual(self.call("POST", "/api/bugs/99/tags", {"tags": []}),
                         (404, {"error": "no bug #99"}))
        self.assertEqual(self.call("POST", "/api/bugs/99/tags", {"tags": "x"}),
                         (404, {"error": "no bug #99"}))
        self.assertEqual(self.call("GET", "/api/bugs/x"), (404, {"error": "no such route"}))

    def test_bug_route_methods(self):
        self.assertEqual(self.call("POST", "/api/bugs"), (405, {"error": "use GET"}))
        self.assertEqual(self.call("POST", "/api/bugs/1"), (405, {"error": "use GET"}))
        self.assertEqual(self.call("GET", "/api/bugs/1/tags"), (405, {"error": "use POST"}))


NOTES = """# Paging
intro line

## TLB
a
b
c

## Example
one
two
three

```
# not a heading
```

## Example
four
five
six

## Short
x
"""

QA = """### Q1
What is a TLB?

**Answer.** A cache of page-table entries.
"""


class TestSettings(ApiCase):
    def test_get_settings(self):
        code, data = self.call("GET", "/api/settings")
        self.assertEqual(code, 200)
        self.assertEqual(data["values"]["hours_per_day"], "4")
        self.assertEqual(set(data["values"]), set(DEFAULTS))
        self.assertEqual(data["db"], ":memory:")
        self.assertEqual(data["files"], 0)

    def test_settings_shows_the_file_with_a_tilde_and_counts_indexed_files(self):
        with TemporaryDirectory() as d:
            c = connect(Path(d) / "pm.db")
            self.addCleanup(c.close)
            c.execute("INSERT INTO files(path, mtime, size, indexed)"
                      " VALUES('/x', 1, 1, '2026-11-09T10:00:00')")
            c.commit()
            with mock.patch("pathlib.Path.home", return_value=Path(d)):
                code, data = api.handle(c, "GET", "/api/settings", {}, {}, NOW)
            self.assertEqual((code, data["db"], data["files"]), (200, "~/pm.db", 1))

    def test_post_settings_saves_and_the_state_sees_it(self):
        self.assertEqual(self.call("POST", "/api/settings",
                                   {"key": "peak", "value": "25-30"})[0], 400)
        self.assertEqual(self.call("GET", "/api/settings")[1]["values"]["peak"], "09-12")
        self.assertEqual(self.call("POST", "/api/settings",
                                   {"key": "peak", "value": "10-13"}), (200, {}))
        self.assertEqual(self.state()["today"]["peak"], "10-13")
        self.assertEqual(self.call("GET", "/api/settings")[1]["values"]["peak"], "10-13")

    def test_settings_errors_are_400_and_change_nothing(self):
        cases = [
            ({"key": "peak", "value": 5}, "setting key and value must be text"),
            ({"key": [], "value": "10-13"}, "setting key and value must be text"),
            ({"key": "peak"}, "setting key and value must be text"),
            ({}, "setting key and value must be text"),
            ({"key": "nope", "value": "1"}, "unknown setting 'nope'"),
            ({"key": "hours_per_day", "value": "abc"},
             "hours_per_day must be between 0.1 and 16"),
            ({"key": "hours_per_day", "value": "nan"},
             "hours_per_day must be between 0.1 and 16"),
            ({"key": "notes_url", "value": "http://x.dev"},
             "notes_url must be empty or https://your-site"),
            ({"key": "watch", "value": "Downloads"},
             "watch folders must be full paths like ~/Downloads"),
            ({"key": "watch_ignore", "value": "Downloads"},
             "watch_ignore folders must be full paths like ~/Downloads"),
            ({"key": "nudge_hours", "value": "22-08"}, "expected a range like 09-17"),
            ({"key": "course_codes", "value": "os"}, "course_codes must be name=CODE pairs"),
            ({"key": "new_per_day", "value": "0"}, "new_per_day must be between 1 and 200"),
        ]
        for body, message in cases:
            with self.subTest(body=body):
                code, data = self.call("POST", "/api/settings", body)
                self.assertEqual(code, 400)
                self.assertIn(message, data["error"])
        self.assertEqual(self.state()["today"]["peak"], "09-12")
        self.assertEqual(self.call("GET", "/api/settings")[1]["values"]["watch"], "~/Downloads")

    def test_settings_accepts_valid_values(self):
        for key, value in (("notes_url", ""), ("notes_url", "https://x.dev"),
                           ("watch", "/tmp:~/Downloads"), ("watch_ignore", "")):
            with self.subTest(key=key, value=value):
                self.assertEqual(self.call("POST", "/api/settings",
                                           {"key": key, "value": value}), (200, {}))
                self.assertEqual(self.call("GET", "/api/settings")[1]["values"][key], value)

    def test_settings_wrong_method_is_405(self):
        self.assertEqual(self.call("PUT", "/api/settings"),
                         (405, {"error": "use GET or POST"}))


class TestFilesApi(ApiCase):
    def setUp(self):
        super().setUp()
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        set_setting(self.c, "watch", str(self.root))

    def index(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        old = NOW - timedelta(minutes=1)
        os.utime(path, (old.timestamp(), old.timestamp()))
        scan(self.c, NOW)
        return path

    def file_id(self, name):
        return self.c.execute("SELECT id FROM files WHERE path=?",
                              (str(self.root / name),)).fetchone()["id"]

    def test_recent_files_and_total(self):
        self.index("a.txt", "alpha")
        self.index("b.txt", "beta")
        code, data = self.call("GET", "/api/files")
        self.assertEqual(code, 200)
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["courses"], [])
        self.assertEqual([hit["name"] for hit in data["hits"]], ["b.txt", "a.txt"])
        hit = data["hits"][0]
        self.assertEqual(set(hit), {"id", "path", "short", "name", "course", "snippet",
                                    "openable"})
        self.assertEqual(hit["snippet"], "")
        self.assertTrue(hit["openable"])
        self.assertEqual(hit["path"], str(self.root / "b.txt"))

    def test_non_openable_files_are_still_listed(self):
        self.index("tool.desktop", "not text")
        code, data = self.call("GET", "/api/files")
        self.assertEqual(code, 200)
        self.assertFalse(data["hits"][0]["openable"])

    def test_search_marks_the_snippet_and_reports_openable(self):
        self.index("paging.txt", "the paging and tlb")
        code, data = self.call("GET", "/api/files?q=paging")
        self.assertEqual(code, 200)
        [hit] = data["hits"]
        self.assertEqual(hit["name"], "paging.txt")
        self.assertTrue(hit["openable"])
        self.assertIn("\x02", hit["snippet"])
        self.assertNotIn("[", hit["snippet"])

    def test_a_whitespace_query_lists_recent_files(self):
        self.index("a.txt", "alpha")
        self.index("b.txt", "beta")
        for target in ("/api/files", "/api/files?q=", "/api/files?q=%20%20"):
            with self.subTest(target=target):
                code, data = self.call("GET", target)
                self.assertEqual(code, 200)
                self.assertEqual([hit["name"] for hit in data["hits"]], ["b.txt", "a.txt"])

    def test_course_filters_search_and_recent(self):
        self.index("a.txt", "alpha")
        self.index("b.txt", "beta")
        self.c.execute("UPDATE files SET course='os' WHERE path=?",
                       (str(self.root / "a.txt"),))
        self.c.commit()
        code, data = self.call("GET", "/api/files?course=os")
        self.assertEqual([hit["name"] for hit in data["hits"]], ["a.txt"])
        self.assertEqual(data["courses"], ["os"])
        code, data = self.call("GET", "/api/files?q=alpha&course=os")
        self.assertEqual([hit["name"] for hit in data["hits"]], ["a.txt"])
        code, data = self.call("GET", "/api/files?q=alpha&course=dbms")
        self.assertEqual((code, data["hits"]), (200, []))

    def test_short_path_uses_a_tilde(self):
        self.index("a.txt", "alpha")
        with mock.patch("pathlib.Path.home", return_value=self.root):
            code, data = self.call("GET", "/api/files")
        self.assertEqual(code, 200)
        self.assertEqual(data["hits"][0]["short"], "~/a.txt")

    def test_open_and_reveal_post_the_file_id(self):
        self.index("a.txt", "alpha")
        file_id = self.file_id("a.txt")
        with mock.patch("pm.api.open_file") as open_file, \
                mock.patch("pm.api.reveal") as reveal:
            self.assertEqual(self.call("POST", f"/api/files/{file_id}/open"), (200, {}))
            open_file.assert_called_once_with(self.c, file_id)
            self.assertEqual(self.call("POST", f"/api/files/{file_id}/reveal"), (200, {}))
            reveal.assert_called_once_with(self.c, file_id)

    def test_open_refuses_a_script(self):
        self.index("run.sh", "echo hi")
        file_id = self.file_id("run.sh")
        code, data = self.call("POST", f"/api/files/{file_id}/open")
        self.assertEqual(code, 400)
        self.assertIn("use show in folder", data["error"])

    def test_unknown_file_is_404(self):
        self.assertEqual(self.call("POST", "/api/files/99/open"),
                         (404, {"error": "no file #99"}))
        self.assertEqual(self.call("POST", "/api/files/99/reveal"),
                         (404, {"error": "no file #99"}))

    def test_file_route_methods_and_ids(self):
        self.assertEqual(self.call("POST", "/api/files"), (405, {"error": "use GET"}))
        self.assertEqual(self.call("GET", "/api/files/1/open"),
                         (405, {"error": "use POST"}))
        self.assertEqual(self.call("POST", "/api/files/x/open"),
                         (404, {"error": "no such route"}))
        self.assertEqual(self.call("POST", "/api/files/\u0661/open"),
                         (404, {"error": "no such route"}))
        self.assertEqual(self.call("POST", "/api/files/1/delete"),
                         (404, {"error": "no such route"}))


class StudyCase(ApiCase):
    def setUp(self):
        super().setUp()
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.notes = self.dir / "notes.md"
        self.notes.write_text(NOTES)
        self.qa = self.dir / "qa.md"
        self.qa.write_text(QA)
        self.pdf = self.dir / "a.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

    def topic(self, name="paging", **body):
        code, data = self.call("POST", "/api/topics", {"name": name, **body})
        self.assertEqual(code, 200, data)
        return data["id"]

    def add_study_items(self, topic_id, path, locators):
        code, data = self.call("POST", "/api/items",
                               {"topic_id": topic_id, "path": str(path),
                                "locators": locators})
        self.assertEqual(code, 200, data)
        return data

    def outline(self, path):
        code, data = self.call("GET", f"/api/outline?path={quote(str(path))}")
        self.assertEqual(code, 200, data)
        return data

    def study(self):
        code, data = self.call("GET", "/api/study")
        self.assertEqual(code, 200, data)
        return data

    def next_body(self):
        code, data = self.call("GET", "/api/review/next")
        self.assertEqual(code, 200, data)
        dumped = json.dumps(data)
        self.assertNotIn("cache of page-table", dumped)
        self.assertNotIn("a\\nb\\nc", dumped)
        return data


class TestStudyApi(StudyCase):
    def test_empty_study(self):
        body = self.study()
        self.assertEqual(body["topics"], [])
        self.assertIsNone(body["next"])
        self.assertEqual(body["calibration"],
                         {"n": 0, "brier": None, "gap": 0.0, "bins": [], "sources": []})
        self.assertEqual((body["readiness"], body["misses"]), ([], []))
        self.assertEqual(body["queue"], {"due": 0, "held": 0})

    def test_topics_with_prereqs_and_the_next_pick(self):
        first = self.topic("paging", course="os", exam="+20", weight=2)
        second = self.topic("virtual memory", course="os", exam="+5", weight=3,
                            needs=["paging"])
        body = self.study()
        one, two = body["topics"]
        self.assertEqual((one["id"], one["course"], one["name"]),
                         (first, "os", "paging"))
        self.assertEqual((one["exam"], one["weight"]), ("2026-11-29", 2))
        self.assertEqual(two["prereqs"], [first])
        self.assertEqual((two["items"], two["due"]), (0, 0))
        self.assertEqual(body["next"], {"topic_id": first, "unblocks_id": second})
        self.assertEqual([pick["topic_id"] for pick in body["ranking"]], [second, first])

    def test_per_topic_due_counts_the_capped_queue(self):
        first = self.topic("paging", course="os")
        second = self.topic("virtual memory", course="os")
        for n in range(8):
            add_item(self.c, first, self.notes, f"h{n}", now=NOW)
        for n in range(4):
            add_item(self.c, second, self.notes, f"g{n}", now=NOW)
        body = self.study()
        counts = {topic["id"]: (topic["items"], topic["due"]) for topic in body["topics"]}
        self.assertEqual(counts[first], (8, 8))
        self.assertEqual(counts[second], (4, 2))
        self.assertEqual(body["queue"], {"due": 10, "held": 2})

    def test_topic_type_errors(self):
        cases = [
            ({"name": 5}, "name must be text"),
            ({}, "name must be text"),
            ({"name": "   "}, "topic name can't be blank"),
            ({"name": "\t\n"}, "topic name can't be blank"),
            ({"name": "x", "course": 5}, "course must be text"),
            ({"name": "x", "exam": []}, "exam must be text"),
            ({"name": "x", "weight": True}, "weight must be a number"),
            ({"name": "x", "weight": "2"}, "weight must be a number"),
            ({"name": "x", "needs": "paging"}, "needs must be a list of names"),
            ({"name": "x", "needs": [1]}, "needs must be a list of names"),
        ]
        for body, message in cases:
            with self.subTest(body=body):
                self.assertEqual(self.call("POST", "/api/topics", body),
                                 (400, {"error": message}))
        self.assertEqual(self.study()["topics"], [])
        self.assertEqual(self.call("POST", "/api/topics", {"name": "  paging  "})[0], 200)
        self.assertEqual(self.study()["topics"][0]["name"], "paging")

    def test_edit_topic_clears_the_exam(self):
        topic_id = self.topic("paging", course="os", exam="+20", weight=2)
        self.assertEqual(self.call("POST", f"/api/topics/{topic_id}/edit",
                                   {"exam": "", "weight": 3}), (200, {}))
        [topic] = self.study()["topics"]
        self.assertIsNone(topic["exam"])
        self.assertEqual(topic["weight"], 3)
        self.assertEqual(self.call("POST", f"/api/topics/{topic_id}/edit",
                                   {"exam": "+3"}), (200, {}))
        self.assertEqual(self.study()["topics"][0]["exam"], "2026-11-12")
        self.assertEqual(self.call("POST", f"/api/topics/{topic_id}/edit",
                                   {"weight": True}),
                         (400, {"error": "weight must be a number"}))
        self.assertEqual(self.call("POST", "/api/topics/99/edit", {"exam": "+3"}),
                         (404, {"error": "no topic #99"}))

    def test_add_items_and_a_bad_locator_adds_nothing(self):
        topic_id = self.topic()
        self.assertEqual(self.add_study_items(topic_id, self.notes, ["TLB", "Example"]),
                         {"added": 2, "skipped": 0})
        code, data = self.call("POST", "/api/items",
                               {"topic_id": topic_id, "path": str(self.notes),
                                "locators": ["Nope"]})
        self.assertEqual((code, data), (400, {"error": "no heading 'Nope' in notes.md"}))
        self.assertEqual(self.study()["topics"][0]["items"], 2)

    def test_add_items_type_errors_add_nothing(self):
        topic_id = self.topic()
        bad = [
            ({"topic_id": topic_id, "path": 5, "locators": ["TLB"]}, "path must be text"),
            ({"topic_id": "1", "path": str(self.notes), "locators": ["TLB"]},
             "topic_id must be an integer"),
            ({"topic_id": True, "path": str(self.notes), "locators": ["TLB"]},
             "topic_id must be an integer"),
            ({"topic_id": topic_id, "path": str(self.notes), "locators": "TLB"},
             "locators must be a list of 1-500 sections"),
            ({"topic_id": topic_id, "path": str(self.notes), "locators": []},
             "locators must be a list of 1-500 sections"),
            ({"topic_id": topic_id, "path": str(self.notes), "locators": [1]},
             "locators must be a list of 1-500 sections"),
            ({"topic_id": topic_id, "path": str(self.notes), "locators": ["TLB"] * 501},
             "locators must be a list of 1-500 sections"),
            ({"topic_id": topic_id, "path": "notes.md", "locators": ["TLB"]},
             "give a full path"),
        ]
        for body, message in bad:
            with self.subTest(body=body):
                self.assertEqual(self.call("POST", "/api/items", body),
                                 (400, {"error": message}))
        self.assertEqual(self.study()["topics"][0]["items"], 0)

    def test_add_items_checks_pdf_pages_before_adding(self):
        topic_id = self.topic()
        pages = [Section(f"p{n}", f"page {n}", 1, 0, True, True) for n in (1, 2, 3)]
        with mock.patch("pm.api.outline", return_value=pages):
            code, data = self.call("POST", "/api/items",
                                   {"topic_id": topic_id, "path": str(self.pdf),
                                    "locators": ["p1", "p99"]})
            self.assertEqual((code, data), (400, {"error": "no page 99 in a.pdf"}))
            self.assertEqual(self.study()["topics"][0]["items"], 0)
            code, data = self.call("POST", "/api/items",
                                   {"topic_id": topic_id, "path": str(self.pdf),
                                    "locators": ["not-a-page"]})
            self.assertEqual((code, data),
                             (400, {"error": "no page not-a-page in a.pdf"}))
            self.assertEqual(self.study()["topics"][0]["items"], 0)
            self.assertEqual(self.call("POST", "/api/items",
                                       {"topic_id": topic_id, "path": str(self.pdf),
                                        "locators": ["p1"]}),
                             (200, {"added": 1, "skipped": 0}))
        gone = self.dir / "gone.pdf"
        self.assertEqual(self.call("POST", "/api/items",
                                   {"topic_id": topic_id, "path": str(gone),
                                    "locators": ["p1"]})[0], 400)

    def test_outline_sections_picks_and_existing(self):
        body = self.outline(self.notes)
        self.assertEqual(body["kind"], "markdown")
        self.assertEqual(body["path"], str(self.notes.resolve()))
        self.assertEqual([s["title"] for s in body["sections"]],
                         ["Paging", "TLB", "Example", "Example", "Short"])
        sections = {s["locator"]: s for s in body["sections"]}
        self.assertTrue(sections["TLB"]["picked"])
        self.assertFalse(sections["TLB"]["exists"])
        self.assertFalse(sections["Short"]["picked"])
        self.assertFalse(sections["Paging"]["leaf"])
        self.assertFalse(sections["Paging"]["pdf"])
        topic_id = self.topic()
        self.add_study_items(topic_id, self.notes, ["TLB"])
        dotted = self.dir / "sub" / ".." / "notes.md"
        sections = {s["locator"]: s for s in self.outline(dotted)["sections"]}
        self.assertTrue(sections["TLB"]["exists"])
        self.assertEqual(sections["TLB"]["topics"], [topic_id])  # greyed only for this topic
        self.assertEqual(sections["Short"]["topics"], [])
        self.assertEqual(self.add_study_items(topic_id, dotted, ["TLB"]),
                         {"added": 0, "skipped": 1})

    def test_outline_says_when_the_whole_file_is_already_an_item(self):
        topic_id = self.topic()
        plain = self.dir / "plain.txt"
        plain.write_text("a\nb\nc\n")
        self.assertIs(self.outline(plain)["whole_file_exists"], False)
        self.add_study_items(topic_id, plain, [None])
        self.assertIs(self.outline(plain)["whole_file_exists"], True)
        self.assertEqual(self.outline(plain)["whole_file_topics"], [topic_id])

    def test_outline_errors_are_400_not_500(self):
        self.assertEqual(self.call("GET", "/api/outline?path=notes.md"),
                         (400, {"error": "give a full path"}))
        self.assertEqual(self.call("GET", "/api/outline?path=5"),
                         (400, {"error": "give a full path"}))
        code, data = self.call("GET", "/api/outline?path=~nosuchuser_x/a.md")
        self.assertEqual(code, 400)
        self.assertIn("error", data)
        code, data = self.call("GET", f"/api/outline?path={quote(str(self.dir / 'gone.md'))}")
        self.assertEqual(code, 400)
        self.assertIn("no such file", data["error"])

    def test_paths_expand_the_home_folder(self):
        topic_id = self.topic()
        with mock.patch.dict(os.environ, {"HOME": str(self.dir)}):
            body = self.outline("~/notes.md")
            self.assertEqual(body["path"], str(self.notes.resolve()))
            self.add_study_items(topic_id, "~/notes.md", ["TLB"])
            item_id = self.next_body()["item"]["id"]
            code, data = self.call("GET", f"/api/items/{item_id}/excerpt")
        self.assertEqual(code, 200)
        self.assertEqual(data["path"], "~/notes.md")

    def test_next_item_carries_the_question_but_not_the_answer(self):
        topic_id = self.topic()
        self.add_study_items(topic_id, self.notes, ["TLB", "Example"])
        body = self.next_body()
        self.assertEqual((body["left"], body["held"]), (2, 0))
        self.assertEqual(body["item"]["title"], "notes.md › TLB")
        self.assertEqual(body["item"]["kind"], "markdown")
        self.assertIsNone(body["item"]["question"])
        self.assertNotIn("a\nb\nc", json.dumps(body))

    def test_next_uses_the_prompt_and_the_plain_file_name(self):
        topic_id = self.topic()
        add_item(self.c, topic_id, self.notes, None, now=NOW)
        body = self.next_body()
        self.assertEqual(body["item"]["title"], "notes.md")
        self.call("POST", f"/api/items/{body['item']['id']}/review",
                  {"grade": 3, "confidence": 50})
        add_item(self.c, topic_id, self.notes, "TLB", now=NOW, prompt="what is a TLB")
        body = self.next_body()
        self.assertEqual(body["item"]["title"], "what is a TLB")
        self.assertIsNone(body["item"]["question"])

    def test_excerpt_links_to_the_note_on_the_site(self):
        topic_id = self.topic()
        folder = self.dir / "os"
        folder.mkdir()
        paging = folder / "paging.md"
        paging.write_text("# Paging\n\n## TLB\n\n## Example\n")
        item_id = add_item(self.c, topic_id, paging, "TLB", now=NOW)
        set_setting(self.c, "notes_dir", str(self.dir))
        for notes_url in ("https://x.dev/", "https://x.dev"):
            with self.subTest(notes_url=notes_url):
                set_setting(self.c, "notes_url", notes_url)
                code, data = self.call("GET", f"/api/items/{item_id}/excerpt")
                self.assertEqual(code, 200)
                self.assertEqual(data["site"], "https://x.dev/os/paging/#tlb")
                self.assertNotIn(str(self.dir), data["site"])
                self.assertNotIn(".md", data["site"])
        set_setting(self.c, "notes_url", "")
        data = self.call("GET", f"/api/items/{item_id}/excerpt")[1]
        self.assertIsNone(data["site"])

    def test_excerpt_has_no_site_for_an_item_outside_the_notes_folder(self):
        topic_id = self.topic()
        item_id = add_item(self.c, topic_id, self.notes, "TLB", now=NOW)
        set_setting(self.c, "notes_url", "https://x.dev")
        (self.dir / "elsewhere").mkdir()
        set_setting(self.c, "notes_dir", str(self.dir / "elsewhere"))
        data = self.call("GET", f"/api/items/{item_id}/excerpt")[1]
        self.assertIsNone(data["site"])
        set_setting(self.c, "notes_dir", "")
        data = self.call("GET", f"/api/items/{item_id}/excerpt")[1]
        self.assertIsNone(data["site"])

    def test_question_bet_and_reveal_for_a_qa_note(self):
        topic_id = self.topic()
        self.add_study_items(topic_id, self.qa, ["Q1"])
        body = self.next_body()
        self.assertEqual(body["item"]["title"], "qa.md › Q1")
        self.assertEqual(body["item"]["question"], "What is a TLB?")
        self.assertNotIn("cache of page-table", json.dumps(body))
        code, data = self.call("GET", f"/api/items/{body['item']['id']}/excerpt")
        self.assertEqual(code, 200)
        self.assertEqual(data["kind"], "markdown")
        self.assertEqual(data["path"], str(self.qa.resolve()))
        self.assertEqual(data["locator"], "Q1")
        self.assertEqual(data["question"], "What is a TLB?")
        self.assertTrue(data["text"].startswith("**Answer.**"))
        self.assertIsNone(data["image"])
        self.assertEqual(set(data["intervals"]), {"1", "2", "3", "4"})
        for value in data["intervals"].values():
            datetime.fromisoformat(value)

    def test_review_grade_and_confidence_types(self):
        topic_id = self.topic()
        self.add_study_items(topic_id, self.notes, ["TLB"])
        item_id = self.next_body()["item"]["id"]
        bad = [
            ({"grade": 3}, "confidence must be 0-100"),
            ({"confidence": 50}, "grade must be 1-4"),
            ({"grade": 5, "confidence": 50}, "grade must be 1-4"),
            ({"grade": True, "confidence": 50}, "grade must be 1-4"),
            ({"grade": 3.0, "confidence": 50}, "grade must be 1-4"),
            ({"grade": "3", "confidence": 50}, "grade must be 1-4"),
            ({"grade": 3, "confidence": True}, "confidence must be 0-100"),
            ({"grade": 3, "confidence": 101}, "confidence must be 0-100"),
        ]
        for body, message in bad:
            with self.subTest(body=body):
                self.assertEqual(self.call("POST", f"/api/items/{item_id}/review", body),
                                 (400, {"error": message}))
        self.assertEqual(self.c.execute("SELECT count(*) FROM reviews").fetchone()[0], 0)
        code, data = self.call("POST", f"/api/items/{item_id}/review",
                               {"grade": 3, "confidence": 70})
        self.assertEqual(code, 200)
        self.assertIn("next_due", data)
        row = self.c.execute("SELECT grade, confidence FROM reviews").fetchone()
        self.assertEqual(row["grade"], 3)
        self.assertAlmostEqual(row["confidence"], 0.7)

    def test_a_missing_file_still_can_be_reviewed_and_suspended(self):
        topic_id = self.topic()
        self.add_study_items(topic_id, self.notes, ["TLB", "Example"])
        ids = [row["id"] for row in self.c.execute("SELECT id FROM items ORDER BY id")]
        self.notes.unlink()
        body = self.next_body()
        self.assertEqual(body["left"], 2)
        self.assertIsNone(body["item"]["question"])
        code, data = self.call("GET", f"/api/items/{ids[0]}/excerpt")
        self.assertEqual(code, 200)
        self.assertEqual(data["kind"], "missing")
        self.assertIn("no such file", data["error"])
        self.assertIsNone(data["text"])
        self.assertIsNone(data["image"])
        self.assertEqual(set(data["intervals"]), {"1", "2", "3", "4"})
        self.assertEqual(self.call("POST", f"/api/items/{ids[0]}/review",
                                   {"grade": 3, "confidence": 50})[0], 200)
        self.assertEqual(self.c.execute("SELECT count(*) FROM reviews").fetchone()[0], 1)
        self.assertEqual(self.call("POST", f"/api/items/{ids[1]}/suspend", {"on": True}),
                         (200, {}))
        self.assertEqual(self.study()["queue"], {"due": 0, "held": 0})

    def test_suspend_off_puts_the_item_back(self):
        topic_id = self.topic()
        self.add_study_items(topic_id, self.notes, ["TLB"])
        item_id = self.next_body()["item"]["id"]
        self.assertEqual(self.call("POST", f"/api/items/{item_id}/suspend",
                                   {"on": "no"}),
                         (400, {"error": "on must be true or false"}))
        self.call("POST", f"/api/items/{item_id}/suspend")
        self.assertIsNone(self.next_body()["item"])
        self.call("POST", f"/api/items/{item_id}/suspend", {"on": False})
        self.assertEqual(self.next_body()["item"]["id"], item_id)

    def test_pdf_excerpt_image_and_page_png(self):
        topic_id = self.topic()
        pages = [Section(f"p{n}", f"page {n}", 1, 0, True, True) for n in (1, 2, 3)]
        with mock.patch("pm.api.outline", return_value=pages):
            self.add_study_items(topic_id, self.pdf, ["p3"])
        item_id = self.next_body()["item"]["id"]
        with mock.patch("pm.api.shutil.which", return_value="/usr/bin/pdftoppm"), \
                mock.patch("pm.api.outline", return_value=pages):
            code, data = self.call("GET", f"/api/items/{item_id}/excerpt")
        self.assertEqual(code, 200)
        self.assertEqual(data["kind"], "pdf")
        self.assertEqual(data["image"],
                         f"/api/items/{item_id}/page.png?v={self.pdf.stat().st_mtime_ns}")
        self.assertIsNone(data["text"])
        self.assertIsNone(data["question"])
        with mock.patch("pm.api.shutil.which", return_value=None), \
                mock.patch("pm.api.excerpt", return_value="page text"):
            code, data = self.call("GET", f"/api/items/{item_id}/excerpt")
        self.assertEqual(code, 200)
        self.assertIsNone(data["image"])
        self.assertEqual(data["text"], "page text")
        with mock.patch("pm.api.page_png", return_value=b"\x89PNG"):
            self.assertEqual(self.call("GET", f"/api/items/{item_id}/page.png"),
                             (200, api.Raw("image/png", b"\x89PNG", 3600)))
        with mock.patch("pm.api.page_png", return_value=None):
            self.assertEqual(self.call("GET", f"/api/items/{item_id}/page.png"),
                             (404, {"error": "pdftoppm is not installed"}))

    def test_pdf_excerpt_checks_the_file_and_page_before_an_image_url(self):
        topic_id = self.topic()
        pages = [Section(f"p{n}", f"page {n}", 1, 0, True, True) for n in (1, 2, 3)]
        with mock.patch("pm.api.outline", return_value=pages):
            self.add_study_items(topic_id, self.pdf, ["p3"])
        item_id = self.next_body()["item"]["id"]
        over = add_item(self.c, topic_id, self.pdf, "p99", now=NOW)
        with mock.patch("pm.api.shutil.which", return_value="/usr/bin/pdftoppm"), \
                mock.patch("pm.api.outline", return_value=pages):
            code, data = self.call("GET", f"/api/items/{over}/excerpt")
            self.assertEqual((code, data["kind"], data["error"]),
                             (200, "missing", "no page 99 in a.pdf"))
            self.assertIsNone(data["image"])
        with mock.patch("pm.api.shutil.which", return_value="/usr/bin/pdftoppm"), \
                mock.patch("pm.api.outline", side_effect=ValueError("can't read a.pdf")):
            code, data = self.call("GET", f"/api/items/{item_id}/excerpt")
            self.assertEqual((code, data["kind"], data["error"]),
                             (200, "missing", "can't read a.pdf"))
        self.pdf.unlink()
        with mock.patch("pm.api.shutil.which", return_value="/usr/bin/pdftoppm"):
            code, data = self.call("GET", f"/api/items/{item_id}/excerpt")
            self.assertEqual((code, data["kind"], data["error"]),
                             (200, "missing", f"no such file: {self.pdf}"))
            self.assertIsNone(data["image"])

    def test_page_png_errors_for_markdown_and_missing_pdfs(self):
        topic_id = self.topic()
        self.add_study_items(topic_id, self.notes, ["TLB"])
        markdown_id = self.next_body()["item"]["id"]
        self.assertEqual(self.call("GET", f"/api/items/{markdown_id}/page.png"),
                         (404, {"error": "no such route"}))
        gone = self.dir / "gone.pdf"
        pdf_id = add_item(self.c, topic_id, gone, "p1", now=NOW)
        with mock.patch("pm.api.page_png",
                        side_effect=FileNotFoundError(f"no such file: {gone}")):
            self.assertEqual(self.call("GET", f"/api/items/{pdf_id}/page.png"),
                             (404, {"error": f"no such file: {gone}"}))

    def test_new_route_errors(self):
        self.assertEqual(self.call("GET", "/api/items/99/excerpt"),
                         (404, {"error": "no item #99"}))
        self.assertEqual(self.call("GET", "/api/items/x/excerpt"),
                         (404, {"error": "no such route"}))
        self.assertEqual(self.call("POST", "/api/items/99/review",
                                   {"grade": 3, "confidence": 50}),
                         (404, {"error": "no item #99"}))
        self.assertEqual(self.call("POST", "/api/study"), (405, {"error": "use GET"}))
        self.assertEqual(self.call("POST", "/api/review/next"),
                         (405, {"error": "use GET"}))
        self.assertEqual(self.call("POST", "/api/outline"),
                         (405, {"error": "use GET"}))
        self.assertEqual(self.call("GET", "/api/items"),
                         (405, {"error": "use POST"}))
        self.assertEqual(self.call("GET", "/api/topics"),
                         (405, {"error": "use POST"}))
        self.assertEqual(self.call("POST", "/api/items/1/excerpt"),
                         (405, {"error": "use GET"}))
        self.assertEqual(self.call("GET", "/api/items/1/review"),
                         (405, {"error": "use POST"}))
        self.assertEqual(self.call("GET", "/api/topics/1/edit"),
                         (405, {"error": "use POST"}))


if __name__ == "__main__":
    unittest.main()


class TestPhase10Api(ApiCase):
    def setUp(self):
        super().setUp()
        self.d = TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.dir = Path(self.d.name)

    def test_links_through_the_routes(self):
        task_id = self.add()
        pdf = self.dir / "lab3.pdf"
        pdf.write_bytes(b"%PDF")
        code, data = self.call("POST", f"/api/tasks/{task_id}/links", {"target": str(pdf)})
        self.assertEqual((code, data), (200, {"id": 1}))
        [link] = self.state()["tasks"][0]["links"]
        self.assertEqual((link["id"], link["kind"], link["target"]), (1, "file", str(pdf.resolve())))
        self.assertTrue(link["short"].endswith("lab3.pdf"))
        code, data = self.call("POST", f"/api/tasks/{task_id}/links", {"target": "notes.md"})
        self.assertEqual(code, 400)
        self.assertIn("give a full path", data["error"])
        self.assertEqual(self.call("POST", f"/api/tasks/{task_id}/links", {})[0], 400)
        with mock.patch("pm.api.open_link", return_value=(1, [])) as one:
            self.assertEqual(self.call("POST", f"/api/tasks/{task_id}/links/1/open"),
                             (200, {"opened": 1, "skipped": []}))
        one.assert_called_once_with(self.c, task_id, 1)
        self.assertEqual(self.call("POST", f"/api/tasks/{task_id}/links/1/drop"), (200, {}))
        self.assertEqual(self.state()["tasks"][0]["links"], [])
        self.assertEqual(self.call("POST", f"/api/tasks/{task_id}/links/1/drop")[0], 404)

    def test_start_opens_links_only_when_asked(self):
        task_id = self.add()
        with mock.patch("pm.api.open_links", return_value=(2, ["gone ~/x.pdf"])) as opener:
            self.assertEqual(self.call("POST", f"/api/tasks/{task_id}/start", {"open": True}),
                             (200, {"opened": 2, "skipped": ["gone ~/x.pdf"]}))
            opener.assert_called_once_with(self.c, task_id)
            self.assertTrue(self.state()["tasks"][0]["running"])
            self.assertEqual(self.call("POST", f"/api/tasks/{task_id}/start"), (200, {}))
            self.assertEqual(opener.call_count, 1)

    def test_a_failing_opener_never_undoes_the_start(self):
        task_id = self.add()
        with mock.patch("pm.api.open_links", side_effect=ValueError("xdg-open is not installed")):
            self.assertEqual(self.call("POST", f"/api/tasks/{task_id}/start", {"open": True})[0], 400)
        self.assertTrue(self.state()["tasks"][0]["running"])

    def test_energy_on_stop_and_afterwards(self):
        task_id = self.add()
        self.call("POST", f"/api/tasks/{task_id}/start")
        later = NOW + timedelta(minutes=40)
        code, data = self.call("POST", "/api/stop", {"energy": 9}, now=later)
        self.assertEqual((code, data), (400, {"error": "energy must be 1-5"}))
        self.assertTrue(self.state(later)["tasks"][0]["running"])
        self.assertEqual(self.call("POST", "/api/stop", {}, now=later)[0], 200)
        self.assertTrue(self.state(later)["today"]["unrated"])
        self.assertEqual(self.call("POST", "/api/energy", {"energy": 3}, now=later), (200, {}))
        self.assertFalse(self.state(later)["today"]["unrated"])
        self.assertEqual(self.call("POST", "/api/energy", {"energy": 3}, now=later),
                         (400, {"error": "nothing to rate"}))
        self.call("POST", f"/api/tasks/{task_id}/start", now=later)
        self.call("POST", "/api/stop", {"energy": 4}, now=later + timedelta(minutes=30))
        energies = [r[0] for r in self.c.execute("SELECT energy FROM sessions ORDER BY id")]
        self.assertEqual(energies, [3, 4])

    def test_llm_flag(self):
        self.assertFalse(self.state()["llm"])
        set_setting(self.c, "llm_cmd", "cat")
        self.assertTrue(self.state()["llm"])

    def spot_item(self):
        note = self.dir / "os.md"
        note.write_text("## TLB\none\ntwo secret\nthree\nfour\nfive\nsix\n")
        topic_id = add_topic(self.c, "paging", course="os")
        item_id = add_item(self.c, topic_id, note, "TLB", now=NOW)
        from pm.study import record_review
        record_review(self.c, item_id, 3, 0.8, NOW)
        return item_id

    @staticmethod
    def change_line_3(prompt):
        lines = prompt.split("<excerpt>\n")[1].split("\n</excerpt>")[0].split("\n")
        lines[2] = "three changed"
        return "\n".join(lines)

    def test_spot_cards_end_to_end(self):
        self.spot_item()
        with mock.patch("pm.api.ask", side_effect=lambda conn, prompt: self.change_line_3(prompt)):
            self.assertEqual(self.call("POST", "/api/spot/make", {"n": 1}),
                             (200, {"made": 1, "errors": []}))
        self.assertEqual(self.state()["spots"], 1)
        code, data = self.call("GET", "/api/spot/next")
        self.assertEqual(code, 200)
        self.assertEqual(data["left"], 1)
        self.assertEqual(data["spot"]["lines"][2], "three changed")
        self.assertEqual(data["spot"]["title"], "os.md › TLB")
        text = json.dumps(data)
        self.assertNotIn("two secret", text)
        self.assertNotIn('"line"', text)
        self.assertNotIn("original", text)
        self.assertEqual(self.call("POST", "/api/spots/1/answer", {"picked": 3})[0], 400)
        self.assertEqual(self.call("POST", "/api/spots/1/answer", {"picked": 3, "confidence": 0.8})[0], 400)
        code, data = self.call("POST", "/api/spots/1/answer", {"picked": 3, "confidence": 80})
        self.assertEqual((code, data), (200, {"correct": True, "line": 3, "was": "two secret",
                                              "shown": "three changed"}))
        self.assertEqual(self.c.execute("SELECT confidence FROM spots").fetchone()[0], 0.8)
        code, data = self.call("POST", "/api/spots/1/answer", {"picked": 3, "confidence": 80})
        self.assertEqual((code, data), (400, {"error": "that card is already answered"}))
        self.assertEqual(self.state()["spots"], 0)
        self.assertEqual(self.call("GET", "/api/spot/next"), (200, {"left": 0, "spot": None}))
        self.assertEqual(self.call("POST", "/api/spots/9/answer", {"picked": 1, "confidence": 5})[0], 404)

    def test_spot_make_needs_the_model_and_a_good_n(self):
        self.spot_item()
        self.assertEqual(self.call("POST", "/api/spot/make", {"n": 0})[0], 400)
        self.assertEqual(self.call("POST", "/api/spot/make", {"n": 11})[0], 400)
        code, data = self.call("POST", "/api/spot/make", {"n": 1})
        self.assertEqual(code, 400)
        self.assertTrue(data["error"].startswith("set llm_cmd first"), data)

    def test_spot_make_reports_a_bad_reply_per_item(self):
        item_id = self.spot_item()
        with mock.patch("pm.api.ask", return_value="nonsense"):
            code, data = self.call("POST", "/api/spot/make", {"n": 1})
        self.assertEqual(code, 200)
        self.assertEqual(data["made"], 0)
        self.assertTrue(data["errors"][0].startswith(f"#{item_id}: the model didn't change"), data)

    def test_new_post_routes_refuse_get(self):
        for path in ["/api/energy", "/api/spot/make", "/api/spots/1/answer", "/api/tasks/1/links",
                     "/api/tasks/1/links/2/drop", "/api/tasks/1/links/2/open"]:
            with self.subTest(path=path):
                self.assertEqual(self.call("GET", path)[0], 405)
        self.assertEqual(self.call("POST", "/api/spot/next")[0], 405)


class TestPhase11Api(StudyCase):
    def setUp(self):
        super().setUp()
        self.five = self.dir / "five.md"
        self.five.write_text("".join(f"# S{k}\na\nb\nc\n\n" for k in range(1, 6)))

    def test_facets_and_coverage(self):
        t = self.topic("paging", course="os")
        self.add_study_items(t, self.five, ["S1", "S2"])
        [topic] = self.study()["topics"]
        f = topic["facets"]
        self.assertEqual((f["covered"], f["total"], f["memory"]["n"]), (2, 5, 2))
        self.assertIsNone(f["understanding"])
        self.assertAlmostEqual(topic["mastery"], 0.4 * f["memory"]["value"])
        from pm.evidence import add
        add(self.c, source="practice", ref="p1", ts=NOW, grader="code", topic_id=t,
            correct=True, facet="application")
        self.assertEqual(self.study()["topics"][0]["facets"]["application"]["n"], 1)

    def test_readiness(self):
        self.topic("paging", course="os", exam="+5")
        ready = self.study()["readiness"]
        self.assertEqual([(r["course"], r["exam"], r["topics"]) for r in ready], [("os", "2026-11-14", 1)])

    def test_misses_and_calibration_sources(self):
        t = self.topic("paging", course="os")
        self.add_study_items(t, self.five, ["S1"])
        item = self.c.execute("SELECT id FROM items").fetchone()[0]
        code, data = self.call("POST", f"/api/items/{item}/review", {"grade": 1, "confidence": 90})
        self.assertEqual(code, 200, data)
        body = self.study()
        [miss] = body["misses"]
        self.assertEqual((miss["source"], miss["label"], miss["topic_id"]), ("review", "five.md#S1", t))
        self.assertEqual([s["source"] for s in body["calibration"]["sources"]], ["review"])

    def test_topic_file_routes(self):
        t = self.topic("paging", course="os")
        self.assertEqual(self.call("POST", f"/api/topics/{t}/files", {"path": str(self.five)}),
                         (200, {"sections": 5}))
        self.assertEqual(self.call("POST", f"/api/topics/{t}/files", {"path": "five.md"})[0], 400)
        self.assertEqual(self.call("POST", f"/api/topics/{t}/files", {"path": str(self.dir / "no.md")})[0], 400)
        self.assertEqual(self.call("POST", "/api/topics/99/files", {"path": str(self.five)})[0], 404)
        drop = f"/api/topics/{t}/files/drop"
        self.assertEqual(self.call("POST", drop, {"path": str(self.five)}), (200, {}))
        self.assertEqual(self.call("POST", drop, {"path": str(self.five)})[0], 404)
        self.assertEqual(self.call("GET", f"/api/topics/{t}/files")[0], 405)


class TestExamApi(StudyCase):
    def setUp(self):
        super().setUp()
        from pm.bank import add_question
        self.topic_id = self.topic("paging", course="os")
        add_question(self.c, origin="manual", ref="n", prompt="How many faults?", now=NOW, trust="source",
                     topic_id=self.topic_id, kind="number", expected={"value": 12, "tol": 0}, marks=2)
        add_question(self.c, origin="manual", ref="o", prompt="Explain the TLB", now=NOW, trust="source",
                     topic_id=self.topic_id, answer="SECRETKEY", marks=5)

    def new(self, **body):
        code, data = self.call("POST", "/api/mocks", {"course": "os", "n": 2, **body})
        self.assertEqual(code, 200, data)
        return data["id"]

    def test_empty_and_bank(self):
        self.c.execute("DELETE FROM questions")
        empty = self.call("GET", "/api/exam")[1]
        self.assertEqual((empty["papers"], empty["bank"], empty["mocks"], empty["open"]), ([], [], [], None))
        self.assertEqual(empty["courses"], ["os"])

    def test_bank_counts(self):
        [entry] = self.call("GET", "/api/exam")[1]["bank"]
        self.assertEqual((entry["topic"], entry["n"], entry["by_trust"]), ("paging", 2, {"source": 2}))

    def test_new_mock_errors(self):
        self.assertEqual(self.call("POST", "/api/mocks", {"course": "os", "n": 0})[0], 400)
        code, data = self.call("POST", "/api/mocks", {"course": "none"})
        self.assertEqual((code, data["error"]), (400, "no questions for none yet (pm q import, pm paper import, pm practice link)"))

    def test_the_key_stays_on_the_server_until_finish(self):
        m = self.new()
        self.assertIsNone(self.call("GET", f"/api/mocks/{m}")[1]["left_s"])
        self.assertEqual(self.call("POST", f"/api/mocks/{m}/items/1", {"answer": "x"})[0], 400)
        self.call("POST", f"/api/mocks/{m}/start")
        running = self.call("GET", f"/api/mocks/{m}")[1]
        text = json.dumps(running)
        for secret in ("SECRETKEY", '"key"', '"score"', '"readable"', '"auto"'):
            self.assertNotIn(secret, text)
        self.assertEqual(running["left_s"], running["minutes"] * 60)
        late = self.call("GET", f"/api/mocks/{m}", now=NOW + timedelta(hours=2))[1]
        self.assertLess(late["left_s"], 0)
        self.assertEqual(self.state()["exam"], {"open": m})
        number = next(i["pos"] for i in running["items"] if i["kind"] == "number")
        opened = next(i["pos"] for i in running["items"] if i["kind"] == "open")
        self.assertEqual(self.call("POST", f"/api/mocks/{m}/items/{number}",
                                   {"answer": "12", "confidence": 80, "seconds": 40}), (200, {}))
        self.assertEqual(self.c.execute("SELECT confidence FROM mock_items WHERE pos=?", (number,)).fetchone()[0], 0.8)
        self.assertEqual(self.call("POST", f"/api/mocks/{m}/items/{number}", {"confidence": 101})[0], 400)
        self.assertEqual(self.call("POST", f"/api/mocks/{m}/items/9", {"answer": "x"})[0], 404)
        self.call("POST", f"/api/mocks/{m}/items/{opened}", {"answer": "a cache"})
        self.assertEqual(self.call("POST", f"/api/mocks/{m}/finish"), (200, {"to_mark": 1}))
        self.assertIsNone(self.state()["exam"]["open"])
        self.assertIn('"key"', json.dumps(self.call("GET", f"/api/mocks/{m}")[1]))
        self.assertEqual(self.call("POST", f"/api/mocks/{m}/items/{opened}/mark", {"got": 9})[0], 400)
        self.assertEqual(self.call("POST", f"/api/mocks/{m}/items/{opened}/mark", {"got": 2}), (200, {"to_mark": 0}))
        self.assertEqual(self.c.execute("SELECT count(*) FROM evidence WHERE source='test'").fetchone()[0], 2)
        result = self.call("GET", f"/api/mocks/{m}")[1]["result"]
        self.assertAlmostEqual(result["pct"], 4 / 7)
        self.assertEqual(result["by_topic"][0]["topic"], "paging")
        code, data = self.call("POST", f"/api/mocks/{m}/retry")
        self.assertEqual(code, 200, data)

    def test_retry_with_nothing_missed(self):
        m = self.new()
        self.call("POST", f"/api/mocks/{m}/start")
        for item in self.call("GET", f"/api/mocks/{m}")[1]["items"]:
            self.call("POST", f"/api/mocks/{m}/items/{item['pos']}", {"answer": "12" if item["kind"] == "number" else "x"})
        self.call("POST", f"/api/mocks/{m}/finish")
        opened = next(i["pos"] for i in self.call("GET", f"/api/mocks/{m}")[1]["items"] if i["kind"] == "open")
        self.call("POST", f"/api/mocks/{m}/items/{opened}/mark", {"got": 5})
        self.assertEqual(self.call("POST", f"/api/mocks/{m}/retry")[0], 400)

    def test_question_page(self):
        from pm.bank import add_paper, add_question
        self.assertEqual(self.call("GET", "/api/questions/1/page.png")[0], 404)
        paper = add_paper(self.c, "os", "midsem", NOW, path=self.pdf)
        q = add_question(self.c, origin="paper", ref="1/Q1", prompt="midsem Q1", now=NOW, trust="source",
                         topic_id=self.topic_id, path=self.pdf, locator="p1", paper_id=paper)
        with mock.patch("pm.api.page_png", return_value=b"\x89PNG"):
            code, raw = self.call("GET", f"/api/questions/{q}/page.png")
        self.assertEqual((code, raw.content_type), (200, "image/png"))
        self.pdf.unlink()
        self.assertEqual(self.call("GET", f"/api/questions/{q}/page.png"), (404, {"error": "that file is gone"}))

    def test_retire_and_import(self):
        self.assertEqual(self.call("POST", "/api/questions/1/retire", {"reason": "wrong key"}), (200, {}))
        self.assertEqual(self.call("GET", "/api/exam")[1]["bank"][0]["n"], 1)
        self.assertEqual(self.call("POST", "/api/questions/import", {"path": str(self.qa), "topic_id": self.topic_id}),
                         (200, {"added": 1, "skipped": 0}))
        self.assertEqual(self.call("POST", "/api/questions/import", {"path": "qa.md", "topic_id": self.topic_id})[0], 400)


class TestPracticeApi(StudyCase):
    def setUp(self):
        super().setUp()
        self.topic_id = self.topic("paging", course="os")

    def test_overview_and_links(self):
        code, data = self.call("GET", "/api/practice")
        self.assertEqual(code, 200, data)
        self.assertEqual({g["id"] for g in data["generators"]} >= {"paging", "cpu", "disk", "banker", "hashing"}, True)
        self.assertEqual(data["errors"], [])
        self.assertEqual(self.call("POST", "/api/practice/link", {"topic_id": self.topic_id, "gen": "nope"})[0], 404)
        self.assertEqual(self.call("POST", "/api/practice/link", {"topic_id": self.topic_id, "gen": "paging"}),
                         (200, {}))
        topic = next(t for t in self.call("GET", "/api/practice")[1]["topics"] if t["id"] == self.topic_id)
        self.assertEqual((topic["gens"], topic["attempts"], topic["right"]), (["paging"], 0, 0))
        self.assertEqual(self.call("POST", "/api/practice/unlink", {"topic_id": self.topic_id, "gen": "paging"}),
                         (200, {}))
        self.assertEqual(self.call("POST", "/api/practice/unlink", {"topic_id": self.topic_id, "gen": "paging"})[0],
                         404)

    def test_next_has_no_key(self):
        self.assertEqual(self.call("GET", "/api/practice/next")[0], 400)
        self.call("POST", "/api/practice/link", {"topic_id": self.topic_id, "gen": "paging"})
        code, data = self.call("GET", "/api/practice/next")
        self.assertEqual(code, 200, data)
        self.assertTrue(data["text"].startswith("Frames: "))
        self.assertIsInstance(data["seed"], int)
        text = json.dumps(data)
        for hidden in ('"expected"', '"steps"', '"key"', "Faults:"):
            self.assertNotIn(hidden, text)
        self.assertEqual(self.call("GET", "/api/practice/next")[1]["seed"], data["seed"])
        self.assertEqual(self.call("GET", f"/api/practice/next?topic={self.topic_id}")[1]["seed"], data["seed"])
        self.assertEqual(self.call("GET", "/api/practice/next?topic=x")[0], 400)

    def test_answer(self):
        from pm.generators import make
        from tests.test_practice import answer_for
        self.call("POST", "/api/practice/link", {"topic_id": self.topic_id, "gen": "paging"})
        served = self.call("GET", "/api/practice/next")[1]
        problem = make(served["gen"], served["seed"], served["variant"])
        body = {"topic_id": self.topic_id, "gen": served["gen"], "seed": served["seed"],
                "variant": served["variant"], "answer": answer_for(problem), "confidence": 80, "seconds": 40}
        code, data = self.call("POST", "/api/practice/answer", body)
        self.assertEqual(code, 200, data)
        self.assertTrue(data["correct"])
        self.assertIn("Faults:", data["steps"])
        row = self.c.execute("SELECT confidence, grader, facet FROM evidence WHERE source='practice'").fetchone()
        self.assertEqual(tuple(row), (0.8, "code", "application"))
        self.assertEqual(self.call("POST", "/api/practice/answer", {**body, "gen": "nope"})[0], 400)
        self.assertEqual(self.call("POST", "/api/practice/answer", {**body, "variant": "nope"})[0], 400)
        self.assertEqual(self.call("POST", "/api/practice/answer", {**body, "confidence": 101})[0], 400)
        self.assertEqual(self.call("POST", "/api/practice/answer", {**body, "seconds": 90_000})[0], 400)
        self.assertEqual(self.call("POST", "/api/practice/answer", {**body, "topic_id": 99})[0], 404)
        code, data = self.call("POST", "/api/practice/answer",
                               {**body, "answer": "", "confidence": None, "dont_know": True}, now=NOW + timedelta(minutes=1))
        self.assertEqual(code, 200, data)
        self.assertFalse(data["correct"])
        self.assertTrue(data["key"])
        topic = next(t for t in self.call("GET", "/api/practice", now=NOW + timedelta(minutes=2))[1]["topics"]
                     if t["id"] == self.topic_id)
        self.assertEqual((topic["attempts"], topic["right"]), (2, 1))


class TestLhApi(StudyCase):
    def setUp(self):
        super().setUp()
        self.root = self.dir / "lh"
        (self.root / "chats").mkdir(parents=True)
        old = 1794225600 - 3600
        for name in ("teach", "practice"):
            path = self.root / "chats" / f"chat_{name}.json"
            shutil.copy(Path(__file__).parent / "lh" / f"{name}.json", path)
            os.utime(path, (old, old))
        self.later = datetime(2026, 11, 10, 10, 0)
        self.topic("paging", course="os")

    def use_folder(self):
        code, data = self.call("POST", "/api/settings", {"key": "lh_dir", "value": str(self.root)})
        self.assertEqual(code, 200, data)

    def test_no_folder(self):
        with mock.patch("pm.lh.default_dir", return_value=self.dir / "missing"):
            self.assertEqual(self.state()["lh"], {"found": False, "cards_ready": 0, "unsorted": 0, "plugin": "no-app"})
            code, data = self.call("POST", "/api/lh/sync")
        self.assertEqual(code, 400)
        self.assertIn("LearnHarness data not found", data["error"])

    def test_sync_list_and_map(self):
        self.use_folder()
        code, data = self.call("POST", "/api/lh/sync", now=self.later)
        self.assertEqual((code, data["sessions"], data["skipped"]), (200, 2, []))
        self.assertEqual(self.state()["lh"], {"found": True, "cards_ready": 0, "unsorted": 1, "plugin": "missing"})
        lh.install_plugin(self.c)
        self.assertEqual(self.state()["lh"]["plugin"], "ok")
        code, data = self.call("GET", "/api/lh")
        self.assertEqual(code, 200)
        self.assertEqual([s["chat_id"] for s in data["sessions"]], ["chat_practice", "chat_teach"])
        self.assertEqual(data["sessions"][1]["topic_id"], 1)
        self.assertEqual(self.call("POST", "/api/lh/sessions/chat_practice/map", {"topic_id": 1}), (200, {}))
        self.assertEqual(self.state()["lh"]["unsorted"], 0)
        self.assertEqual(self.call("POST", "/api/lh/sessions/chat_practice/map", {"topic_id": None}), (200, {}))
        self.assertEqual(self.state()["lh"]["unsorted"], 1)
        self.assertEqual(self.call("POST", "/api/lh/sessions/chat_practice/map", {"topic_id": 99})[0], 404)
        self.assertEqual(self.call("POST", "/api/lh/sessions/chat_practice/map", {})[0], 400)
        self.assertEqual(self.call("POST", "/api/lh/sessions/../x/map", {"topic_id": 1})[0], 404)
        self.assertEqual(self.call("POST", "/api/lh/sessions/a.b/map", {"topic_id": 1})[0], 404)
        self.assertEqual(self.call("GET", "/api/lh/sync")[0], 405)

    def test_tutor(self):
        self.assertIsNone(self.state()["tutor"])
        exam = self.topic("deadlock", course="os", exam="2026-11-20")
        self.assertEqual(self.state()["tutor"], {"topic_id": exam, "topic": "deadlock", "course": "os"})

    def test_opening(self):
        code, data = self.call("GET", "/api/lh/opening?topic=1")
        self.assertEqual(code, 200)
        self.assertTrue(data["text"].startswith("[pm:topic=1]"))
        code, data = self.call("GET", "/api/lh/opening?topic=1&practice=1")
        self.assertTrue(data["text"].endswith("Please give me exam-style practice problems on this topic."))
        self.assertEqual(self.call("GET", "/api/lh/opening?topic=99")[0], 404)
        self.assertEqual(self.call("GET", "/api/lh/opening")[0], 400)

    def test_stats_minutes_are_never_pushed(self):
        self.use_folder()
        self.call("POST", "/api/lh/sync", now=self.later)
        code, body = self.call("GET", "/api/stats")
        self.assertEqual(code, 200)
        self.assertTrue(body["lh"])
        self.assertEqual(body["lh"], lh.minutes_by_day(self.c))
        self.assertNotIn("lh", stats.summary_now(self.c, NOW))


class TestTutorApi(StudyCase):
    def setUp(self):
        super().setUp()
        self.topic("paging", course="os")

    def test_routes(self):
        code, body = self.call("GET", "/api/lh/context?topic=1")
        self.assertEqual((code, body["topic"]), (200, "paging"))
        self.assertEqual(self.call("GET", "/api/lh/search?q=tlb+miss&course=os"), (200, {"hits": []}))
        self.assertEqual(self.call("GET", "/api/lh/exam-questions?topic=1"), (200, {"questions": []}))
        self.assertEqual(self.call("GET", "/api/lh/problem?topic=1"),
                         (404, {"error": "no verified problem for paging yet"}))
        code, body = self.call("GET", "/api/lh/exam-questions?topic=1&n=8")
        self.assertEqual(code, 200)

    def test_bad_input(self):
        for path in ("/api/lh/context?topic=abc", "/api/lh/context", "/api/lh/search?q=",
                     f"/api/lh/search?q={'a' * 201}", "/api/lh/exam-questions?topic=1&n=9",
                     "/api/lh/exam-questions?topic=1&n=0", "/api/lh/problem?topic=" + "9" * 30):
            with self.subTest(path=path):
                self.assertEqual(self.call("GET", path)[0], 400)
        for path in ("/api/lh/context?topic=99", "/api/lh/exam-questions?topic=99", "/api/lh/problem?topic=99"):
            with self.subTest(path=path):
                self.assertEqual(self.call("GET", path)[0], 404)
        for path in ("/api/lh/context", "/api/lh/search", "/api/lh/exam-questions", "/api/lh/problem"):
            with self.subTest(path=path):
                self.assertEqual(self.call("POST", path)[0], 405)

    def test_the_app_never_calls_the_tutor_routes(self):
        ui = Path(api.__file__).parent / "ui"
        for path in ui.rglob("*"):
            if path.is_file():
                text = path.read_text(errors="replace")
                for route in ("/api/lh/context", "/api/lh/search", "/api/lh/exam-questions", "/api/lh/problem"):
                    self.assertNotIn(route, text, f"{path.name} calls {route}")


class TestAgentApi(StudyCase):
    def setUp(self):
        super().setUp()
        self.topic("paging", course="os")

    def test_study_suggestions_and_budget(self):
        body = self.study()
        self.assertEqual((body["suggestions"], body["agent"]), ([], {"budget": 0, "spent": 0, "queued": 0}))
        self.c.execute("INSERT INTO lh_sessions(chat_id, title, kind, mtime, size) VALUES('chat_a', 'TLB', 'teach', 0, 0)")
        self.c.execute("INSERT INTO suggestions(kind, subject, value, created) VALUES('topic', 'chat_a', '1', '2026-11-09T10:00:00')")
        self.c.commit()
        set_setting(self.c, "agent_daily_calls", "30")
        body = self.study()
        self.assertEqual(body["suggestions"], [{"id": 1, "kind": "topic", "text": 'put session "TLB" under os/paging'}])
        self.assertEqual(body["agent"]["budget"], 30)

    def test_accept_and_reject(self):
        self.c.execute("INSERT INTO lh_sessions(chat_id, title, kind, mtime, size) VALUES('chat_a', 'TLB', 'teach', 0, 0)")
        self.c.execute("INSERT INTO lh_sessions(chat_id, title, kind, mtime, size) VALUES('chat_b', 'b', 'teach', 0, 0)")
        for chat in ("chat_a", "chat_b", "chat_b"):
            self.c.execute("INSERT OR IGNORE INTO suggestions(kind, subject, value, created) VALUES('topic', ?, '1', '2026-11-09T10:00:00')",
                           (chat,))
        self.c.execute("INSERT INTO suggestions(kind, subject, value, created) VALUES('prereq', '1', '1', '2026-11-09T10:00:00')")
        self.c.commit()
        code, body = self.call("POST", "/api/suggestions/1/accept")
        self.assertEqual((code, body), (200, {"text": 'put session "TLB" under os/paging'}))
        self.assertEqual(self.call("POST", "/api/suggestions/1/accept")[0], 404)
        self.assertEqual(self.call("POST", "/api/suggestions/2/reject"), (200, {}))
        code, body = self.call("POST", "/api/suggestions/3/accept")
        self.assertEqual(code, 400)
        self.assertTrue(body["error"].startswith("that suggestion no longer applies"))
        self.assertEqual(self.call("GET", "/api/suggestions/1/accept")[0], 405)

    def marked_test(self, misses=2):
        from pm import bank
        ids = [bank.add_question(self.c, origin="manual", ref=f"m{k}", prompt=f"q{k}", now=NOW, trust="source",
                                 topic_id=1, answer="a") for k in range(3)]
        mid = self.c.execute("INSERT INTO mocks(course, title, minutes, created, marked) VALUES('os', 't', 10, ?, ?)",
                             (NOW.isoformat(), NOW.isoformat())).lastrowid
        for pos, qid in enumerate(ids, 1):
            self.c.execute("INSERT INTO mock_items(mock_id, pos, question_id, topic_id, marks, score, confidence)"
                           " VALUES(?, ?, ?, 1, 1, ?, 0.9)", (mid, pos, qid, 0 if pos <= misses else 1))
        self.c.commit()
        return mid, ids

    def test_vary(self):
        mid, _ = self.marked_test()
        self.assertEqual(self.call("POST", f"/api/mocks/{mid}/vary"), (200, {"queued": 2}))
        self.assertEqual(self.c.execute("SELECT count(*) FROM jobs WHERE kind='variants' AND status='queued'"
                                        ).fetchone()[0], 2)
        self.assertEqual(self.call("POST", f"/api/mocks/{mid}/vary"), (200, {"queued": 0}))
        self.c.execute("UPDATE mocks SET marked=NULL")
        self.c.commit()
        self.assertEqual(self.call("POST", f"/api/mocks/{mid}/vary")[0], 400)

    def test_to_check(self):
        code, body = self.call("GET", "/api/exam")
        self.assertEqual(body["to_check"], [])
        _, ids = self.marked_test(misses=1)
        self.c.execute("UPDATE questions SET trust='unverified' WHERE id=?", (ids[0],))
        self.c.commit()
        code, body = self.call("GET", "/api/exam")
        self.assertEqual(body["to_check"], [{"id": ids[0], "flags": ["suspect"], "trust": "unverified", "attempts": 1,
                                             "mean": 0.0, "prompt": "q0"}])
