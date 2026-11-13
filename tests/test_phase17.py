"""Phase 17 fixes, one test per bug, so each stays fixed."""
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from pm import agent, bank, grade, lh, suggest
from pm.api import handle
from pm.calibrate import posteriors
from pm.db import connect, get_setting, put_setting, set_setting
from pm.files import scan
from pm.risk import simulate
from pm.study import add_item, add_items, add_topic, record_review
from pm.tasks import _minutes, add_task, done, open_tasks, start
from pm.today import plan_day
from tests.helpers import CliCase

NOW = datetime(2026, 11, 9, 10, 0)
OLD = (NOW - timedelta(minutes=5)).timestamp()


class Mem(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)


class TestScan(Mem):
    def test_no_write_lock_while_text_is_extracted(self):
        set_setting(self.c, "watch", str(self.dir))
        for name in ("a.txt", "b.txt"):
            (self.dir / name).write_text("x")
            os.utime(self.dir / name, (OLD, OLD))
        held = []

        def extract(path):
            held.append(self.c.in_transaction)
            return "text"

        self.assertEqual(scan(self.c, NOW, extract=extract).added, 2)
        self.assertEqual(held, [False, False])

    def test_a_pipe_is_not_read(self):
        set_setting(self.c, "watch", str(self.dir))
        os.mkfifo(self.dir / "pipe.txt")
        os.utime(self.dir / "pipe.txt", (OLD, OLD))
        self.assertEqual(scan(self.c, NOW, extract=lambda p: self.fail("read a pipe")).added, 0)


class TestModelJobs(Mem):
    def test_a_huge_topic_tag_is_no_tag(self):
        data = {"id": "c1", "version": 1, "messages": [{"role": "user", "content": "[pm:topic=" + "9" * 30 + "] hi"}]}
        self.assertIsNone(lh.parse_session(data).tag)

    def test_deep_nesting_is_a_bad_reply_not_a_crash(self):
        try:
            agent.parse_json("[" * 100_000 + "]" * 100_000)
        except ValueError:
            pass  # Python 3.14+ parses it instead; either way nothing else is raised

    def test_a_session_is_asked_about_once(self):
        add_topic(self.c, "paging", course="os")
        self.c.execute("INSERT INTO lh_sessions(chat_id, title, kind, mtime, size) VALUES('c1','Small talk','teach',0,0)")
        self.c.commit()
        put_setting(self.c, "agent_daily_calls", "5")
        self.assertEqual(len(agent.plan(self.c, NOW)), 1)
        self.assertEqual(suggest.session_topics(self.c, NOW, lambda prompt: json.dumps({"c1": None})), 0)
        self.c.execute("DELETE FROM jobs")
        self.assertEqual(agent.plan(self.c, NOW), [])
        self.assertEqual(suggest.open_suggestions(self.c), [])

    def reviewed(self, name):
        path = self.dir / name
        path.write_text("# OS\n\n## TLB\n" + "".join(f"line {i} of the note\n" for i in range(8)))
        item = add_item(self.c, 1, path, "TLB", now=NOW - timedelta(days=3))
        record_review(self.c, item, 3, 0.8, NOW - timedelta(days=2))
        return item

    def test_an_item_the_model_fails_on_is_not_retried(self):
        add_topic(self.c, "paging", course="os")
        put_setting(self.c, "agent_daily_calls", "20")
        item = self.reviewed("a.md")
        agent.enqueue(self.c, "spots", "", NOW)
        self.assertEqual(agent.run(self.c, NOW, lambda prompt: "nothing like the note"), ["spots #1: 0 cards"])
        self.assertEqual(agent.spot_failed(self.c), {item})
        self.assertEqual(agent.plan(self.c, NOW), [])

    def test_a_dead_model_blames_no_item(self):
        add_topic(self.c, "paging", course="os")
        put_setting(self.c, "agent_daily_calls", "20")
        self.reviewed("a.md")
        self.reviewed("b.md")
        calls = []

        def dead(prompt):
            calls.append(prompt)
            raise ValueError("the llm command took over 120s")

        agent.enqueue(self.c, "spots", "", NOW)
        [line] = agent.run(self.c, NOW, dead)
        self.assertIn("took over 120s", line)
        self.assertEqual((len(calls), agent.spot_failed(self.c)), (1, set()))

    def test_a_broken_card_file_is_read_once(self):
        root = self.dir / "lh"
        (root / "chats").mkdir(parents=True)
        cards = root / lh.CARDS
        cards.parent.mkdir(parents=True, exist_ok=True)
        cards.write_text("{ not json")
        os.utime(cards, (OLD, OLD))
        set_setting(self.c, "lh_dir", str(root))
        lh.sync(self.c, NOW)
        st = cards.stat()
        self.assertEqual(get_setting(self.c, lh.CARDS_SEEN, ""), f"{st.st_mtime}:{st.st_size}")


class TestAnswers(Mem):
    def test_a_superscript_digit_is_a_wrong_answer(self):
        key = grade.parse_expected("choice", {"options": ["w", "x", "y", "z"], "correct": [2]})
        self.assertFalse(grade.check("choice", key, "²"))
        self.assertFalse(grade.readable("choice", key, "²"))

    def test_keys_must_be_finite(self):
        for value in (float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                grade.parse_expected("number", {"value": value})
        with self.assertRaises(ValueError):
            bank._answer_field("=1" + "0" * 400)


class TestStudy(Mem):
    def test_a_section_can_sit_in_two_topics(self):
        a, b = add_topic(self.c, "paging"), add_topic(self.c, "tlb")
        path = self.dir / "n.md"
        self.assertEqual(add_items(self.c, a, path, ["X", "Y"], now=NOW), (2, 0))
        self.assertEqual(add_items(self.c, b, path, ["X", "Y"], now=NOW), (2, 0))
        self.assertEqual(add_items(self.c, b, path, ["X"], now=NOW), (0, 1))

    def test_the_app_refuses_a_second_grade(self):
        add_topic(self.c, "paging")
        item = add_item(self.c, 1, self.dir / "n.md", None, now=NOW)
        body = {"grade": 3, "confidence": 80}
        self.assertEqual(handle(self.c, "POST", f"/api/items/{item}/review", {}, body, NOW)[0], 200)
        status, reply = handle(self.c, "POST", f"/api/items/{item}/review", {}, body, NOW + timedelta(seconds=5))
        self.assertEqual((status, reply), (400, {"error": "that item isn't due any more"}))
        self.assertEqual(self.c.execute("SELECT count(*) FROM reviews").fetchone()[0], 1)

    def test_an_id_too_big_for_the_database_is_not_found(self):
        self.assertEqual(handle(self.c, "GET", "/api/bugs/" + "9" * 20, {}, {}, NOW)[0], 404)
        self.assertEqual(handle(self.c, "POST", "/api/items", {}, {"topic_id": 10**30, "path": "/n.md",
                                                                   "locators": [None]}, NOW)[0], 400)


class TestTasks(Mem):
    def test_today_follows_the_forecast_order_on_one_due_date(self):
        due = date(2026, 11, 12)
        for title in ("a", "b"):
            add_task(self.c, title, 120, now=NOW, due=due)
        tasks = open_tasks(self.c, NOW)
        post = posteriors([])
        risks, _ = simulate(tasks, post, 240, NOW.date(), n=50)
        plan = plan_day(tasks, {r.task_id: r for r in risks}, post, 600)
        self.assertEqual([t.id for t, _ in plan], [1, 2])

    def test_a_clock_set_back_is_no_negative_time(self):
        self.assertEqual(_minutes(NOW, NOW - timedelta(minutes=20)), 0)

    def test_start_checks_done_inside_its_transaction(self):
        add_task(self.c, "a", 60, now=NOW)
        done(self.c, 1, NOW)
        with self.assertRaises(ValueError):
            start(self.c, 1, NOW)
        self.assertFalse(self.c.in_transaction)


class TestCli(CliCase):
    def test_the_same_item_twice_is_refused(self):
        notes = Path(self.d.name) / "n.md"
        notes.write_text("# OS\n\n## BFS\nbody\n")
        self.pm("topic", "add", "BFS")
        self.assertEqual(self.pm("study", "add", f"{notes}#BFS", "--topic", "BFS")[0], 0)
        self.assertEqual(self.pm("study", "add", f"{notes}#BFS", "--topic", "BFS"),
                         (1, "error: that item is already in BFS\n"))

    def test_an_empty_prerequisite_says_what_to_do(self):
        self.pm("topic", "add", "Graphs", "--course", "algo")
        self.pm("topic", "add", "BFS", "--course", "algo", "--exam", "2026-11-14", "--needs", "Graphs")
        out = self.pm("study", "next")[1]
        self.assertIn("  nothing in it yet: pm study add FILE --topic Graphs\n", out)


class TestUndo(CliCase):
    def test_reopen_brings_back_a_done_or_dropped_task(self):
        self.pm("add", "lab", "--est", "1h")
        self.pm("add", "essay", "--est", "2h")
        self.assertEqual(self.pm("ls", "--done"), (0, "nothing finished yet\n"))
        self.pm("log", "1", "30m")
        self.pm("done", "1")
        self.pm("drop", "2")
        self.assertEqual(self.pm("ls", "--done")[1],
                         "#2  essay  dropped 2026-11-09  est 2h  logged 0m\n#1  lab  done 2026-11-09  est 1h  logged 30m\n")
        self.assertEqual(self.pm("reopen", "1"), (0, "reopened #1 lab\n"))
        self.assertEqual(self.pm("reopen", "2"), (0, "reopened #2 essay\n"))
        self.assertEqual(self.pm("reopen", "2"), (1, "error: #2 is still open\n"))
        self.assertIn("#1  lab  [task/-]  due -  est 1h  logged 30m", self.pm("ls")[1])
        self.assertEqual(self.pm("bias")[1], "no finished tasks yet (assuming x1.50)\n")

    def test_start_says_what_it_stopped(self):
        self.pm("add", "a", "--est", "1h")
        self.pm("add", "b", "--est", "1h")
        self.pm("start", "1")
        out = self.pm("start", "2", "--no-open", now="2026-11-09T10:40:00")[1]
        self.assertEqual(out, "stopped #1 after 40m\nstarted #2 b\n")

    def test_topic_rename_and_item_removal(self):
        notes = Path(self.d.name) / "n.md"
        notes.write_text("# OS\n\n## BFS\nbody\n\n## DFS\nbody\n")
        self.pm("topic", "add", "Grphs")
        self.pm("topic", "add", "Trees")
        self.assertEqual(self.pm("topic", "rename", "Grphs", "Graphs"), (0, "topic #1 is now Graphs\n"))
        self.assertEqual(self.pm("topic", "rename", "Graphs", "Trees")[0], 1)
        self.pm("study", "add", f"{notes}#BFS", "--topic", "Graphs")
        self.pm("study", "add", f"{notes}#DFS", "--topic", "Graphs")
        self.assertEqual(self.pm("study", "ls", "Graphs")[1], "#1  n.md#BFS\n#2  n.md#DFS\n")
        self.pm("review", "--limit", "1", stdin="50\n3\n")
        self.assertEqual(self.pm("study", "rm", "2"), (0, "removed item #2\n"))
        self.assertEqual(self.pm("study", "rm", "1"),
                         (0, "item #1 has answers on record, so it is suspended instead (pm study resume 1)\n"))
        self.assertEqual(self.pm("study", "ls", "Graphs")[1], "#1  n.md#BFS  (suspended)\n")
        self.assertEqual(self.pm("study", "resume", "1"), (0, "item #1 is back in reviews\n"))
        self.assertEqual(self.pm("study", "rm", "9"), (1, "error: no item #9\n"))


class TestEveryday(CliCase):
    def test_no_command_is_today(self):
        self.assertEqual(self.pm(), (0, "nothing to do\n"))

    def test_a_task_needs_a_title_and_a_unit(self):
        self.assertEqual(self.pm("add", " ", "--est", "1h"), (1, "error: title can't be empty\n"))
        with self.assertRaises(SystemExit):
            self.pm("add", "lab", "--est", "90")

    def test_weekday_and_past_due_dates(self):
        self.pm("add", "lab", "--est", "1h", "--due", "fri")
        self.assertEqual(self.pm("add", "old", "--est", "1h", "--due", "2026-11-01")[1],
                         "added #2\nnote: 2026-11-01 is already past\n")
        self.assertIn("due 2026-11-13", self.pm("ls")[1])

    def test_set_shows_the_settings(self):
        code, out = self.pm("set")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[:2], ["hours_per_day = 4", "peak = 09-12"])
        self.assertEqual(len(out.splitlines()), 13)
        self.pm("set", "peak", "10-13")
        self.assertEqual(self.pm("set", "peak"), (0, "peak = 10-13\n"))
        self.assertEqual(self.pm("set", "nope")[0], 1)
        missing = Path(self.d.name) / "nowhere"
        self.assertEqual(self.pm("set", "watch", str(missing))[1].splitlines()[1],
                         f"note: {missing} isn't a folder (yet), so nothing is indexed from it")

    def test_backup_is_a_whole_copy_and_never_overwrites(self):
        self.pm("add", "lab", "--est", "1h")
        dest = Path(self.d.name) / "copy.db"
        self.assertEqual(self.pm("backup", str(dest)), (0, f"saved {dest}\n"))
        copy = connect(dest)
        self.addCleanup(copy.close)
        self.assertEqual([t.title for t in open_tasks(copy, NOW)], ["lab"])
        self.assertEqual(self.pm("backup", str(dest)), (1, f"error: {dest} already exists\n"))
        code, out = self.pm("backup")
        self.assertEqual((code, out), (0, f"saved {self.d.name}/backups/pm-20261109-100000.db\n"))

    def test_an_upgrade_keeps_the_old_database_once(self):
        path = Path(self.d.name) / "old.db"
        c = connect(path)
        c.execute("PRAGMA user_version=12")
        c.close()
        self.assertFalse(Path(f"{path}.v12.bak").exists())
        connect(path).close()
        self.assertTrue(Path(f"{path}.v12.bak").is_file())
        connect(path).close()
        self.assertEqual(len(list(Path(self.d.name).glob("old.db.v*.bak"))), 1)

    def test_doctor(self):
        from unittest import mock
        with mock.patch("pm.cli.shutil.which", side_effect=lambda name: None if name == "tesseract" else "/usr/bin/" + name):
            out = self.pm("doctor")[1]
            self.assertIn("daemon      never ran", out)
            self.assertIn("missing     tesseract: OCR for scanned PDFs", out)
            self.assertIn("ok          git:", out)
            self.assertIn("model jobs  off", out)
            c = connect(os.environ["PM_DB"])
            set_setting(c, "watch_seen", "2026-11-09T09:59:00")
            self.assertIn("daemon      running", self.pm("doctor")[1])
            set_setting(c, "watch_seen", "2026-11-08T09:00:00")
            c.close()
            self.assertIn("daemon      not running, last seen 2026-11-08 09:00:00", self.pm("doctor")[1])


class TestMockFamilies(Mem):
    def test_a_question_and_its_variant_never_share_a_test(self):
        import random
        from pm import mock as mocks
        t = add_topic(self.c, "paging", course="os")
        first = bank.add_question(self.c, origin="manual", ref="q1", prompt="What is a TLB?", now=NOW,
                                  trust="source", topic_id=t, answer="a cache")
        bank.add_question(self.c, origin="variant", ref="v1", prompt="What does a TLB hold?", now=NOW,
                          trust="checked", topic_id=t, answer="translations", parent_id=first)
        bank.add_question(self.c, origin="manual", ref="q2", prompt="What is a page fault?", now=NOW,
                          trust="source", topic_id=t, answer="a miss")
        for seed in range(10):
            mock_id = mocks.build(self.c, "os", NOW, random.Random(seed), n=3)
            ids = [i.question_id for i in mocks.items(self.c, mock_id)]
            self.assertEqual(len(ids), 2, ids)
            self.assertFalse({first, first + 1} <= set(ids))

    def test_the_app_lists_suspended_items(self):
        from pm.study import suspend
        add_topic(self.c, "paging")
        item = add_item(self.c, 1, self.dir / "n.md", "TLB", now=NOW)
        suspend(self.c, item)
        self.assertEqual(handle(self.c, "GET", "/api/study", {}, {}, NOW)[1]["suspended"],
                         [{"id": item, "title": "n.md › TLB", "topic_id": 1}])


if __name__ == "__main__":
    unittest.main()
