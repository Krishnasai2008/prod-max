import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from pm.db import DEFAULTS, connect, default_path, get_setting, put_setting, set_setting, settings


class TestDb(unittest.TestCase):
    def test_schema_and_settings(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 13)
        self.assertEqual(get_setting(conn, "hours_per_day", "4"), "4")
        set_setting(conn, "hours_per_day", "5")
        self.assertEqual(get_setting(conn, "hours_per_day", "4"), "5")

    def test_file_tables(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"files", "files_fts"} <= names)

    def test_study_tables(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"topics", "topic_prereqs", "items", "reviews"} <= names)

    def test_evidence_table_and_view(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        kinds = {r["name"]: r["type"] for r in conn.execute("SELECT name, type FROM sqlite_master")}
        self.assertEqual(kinds["evidence"], "table")
        self.assertEqual(kinds["topic_files"], "table")
        self.assertEqual(kinds["evidence_v"], "view")

    def test_view_is_kept_then_restored(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "pm.db"
            connect(path).close()
            view = "SELECT sql FROM sqlite_master WHERE name='evidence_v'"
            first = sqlite3.connect(path)
            before = first.execute(view).fetchone()[0]
            first.close()
            connect(path).close()
            conn = sqlite3.connect(path)
            self.assertEqual(conn.execute(view).fetchone()[0], before)
            conn.execute("DROP VIEW evidence_v")
            conn.execute("CREATE VIEW evidence_v AS SELECT 1 AS source")
            conn.commit()
            conn.close()
            conn = connect(path)
            self.addCleanup(conn.close)
            self.assertEqual(conn.execute(view).fetchone()[0], before)
            self.assertEqual(conn.execute("SELECT count(*) FROM evidence_v").fetchone()[0], 0)

    def test_old_database_gets_its_files_tracked(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "pm.db"
            conn = connect(path)
            conn.execute("INSERT INTO topics(name) VALUES('paging')")
            for loc in ("A", "B"):
                conn.execute("INSERT INTO items(topic_id, path, locator, card, due, created)"
                             " VALUES(1, '/n/os.md', ?, '{}', 'x', 'x')", (loc,))
            conn.execute("DELETE FROM topic_files")
            conn.execute("PRAGMA user_version=8")
            conn.commit()
            conn.close()
            for _ in range(2):
                conn = connect(path)
                rows = [tuple(r) for r in conn.execute("SELECT topic_id, path, sections FROM topic_files")]
                self.assertEqual(rows, [(1, "/n/os.md", None)])
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 13)
                conn.close()

    def test_exam_tables(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"papers", "questions", "mocks", "mock_items"} <= names)
        conn.execute("INSERT INTO mocks(course, title, minutes, created) VALUES('os', 't', 10, 'x')")
        conn.execute("INSERT INTO questions(origin, ref, prompt, trust, created) VALUES('manual', 'r', 'p', 'source', 'x')")
        for question, gen in ((1, "g"), (None, None)):
            with self.subTest(question=question, gen=gen), self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO mock_items(mock_id, pos, question_id, gen, marks) VALUES(1, 1, ?, ?, 1)",
                             (question, gen))

    def test_inbox_table(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("inbox_applied", names)
        self.assertEqual([r["name"] for r in conn.execute("PRAGMA table_info(inbox_applied)")],
                         ["id", "applied", "error"])

    def test_bug_tables(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"episodes", "runs", "episode_tags"} <= names)
        conn.execute("INSERT INTO episodes(cmd, cwd, opened) VALUES('make', '/p', '2026-11-09T10:00:00')")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO episodes(cmd, cwd, opened) VALUES('make', '/p', '2026-11-09T11:00:00')")

    def test_connect_adds_dropped_to_an_old_tasks_table(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "pm.db"
            old = sqlite3.connect(path)
            old.execute(
                "CREATE TABLE tasks("
                " id INTEGER PRIMARY KEY, title TEXT NOT NULL, course TEXT,"
                " kind TEXT NOT NULL DEFAULT 'task', est_min INTEGER NOT NULL CHECK(est_min > 0),"
                " due TEXT, energy TEXT NOT NULL DEFAULT 'deep' CHECK(energy IN ('deep','shallow')),"
                " first_step TEXT, created TEXT NOT NULL, done_at TEXT)")
            old.execute("INSERT INTO tasks(title, est_min, created)"
                        " VALUES('old', 30, '2026-11-09T09:00:00')")
            old.commit()
            old.close()

            conn = connect(path)
            names = [r["name"] for r in conn.execute("PRAGMA table_info(tasks)")]
            self.assertIn("dropped", names)
            self.assertEqual(conn.execute("SELECT dropped FROM tasks").fetchone()[0], 0)
            conn.close()

            connect(path).close()

    def test_connect_adds_suspended_to_an_old_items_table(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "pm.db"
            old = sqlite3.connect(path)
            old.execute(
                "CREATE TABLE items("
                " id INTEGER PRIMARY KEY, topic_id INTEGER NOT NULL, path TEXT NOT NULL,"
                " locator TEXT, prompt TEXT, card TEXT NOT NULL, due TEXT NOT NULL,"
                " created TEXT NOT NULL)")
            old.execute("INSERT INTO items(topic_id, path, card, due, created)"
                        " VALUES(1, '/n.md', '{}', '2026-11-09T10:00:00+00:00',"
                        " '2026-11-09T10:00:00')")
            old.commit()
            old.close()

            conn = connect(path)
            names = [r["name"] for r in conn.execute("PRAGMA table_info(items)")]
            self.assertIn("suspended", names)
            self.assertEqual(conn.execute("SELECT suspended FROM items").fetchone()[0], 0)
            conn.close()

    def test_default_path_env(self):
        with mock.patch.dict(os.environ, {"PM_DB": "/tmp/x.db"}):
            self.assertEqual(default_path(), Path("/tmp/x.db"))

    def test_connect_creates_parent(self):
        with tempfile.TemporaryDirectory() as d:
            connect(Path(d) / "a" / "pm.db").close()
            self.assertTrue((Path(d) / "a" / "pm.db").exists())

    def test_file_database_is_wal_with_busy_timeout(self):
        with tempfile.TemporaryDirectory() as d:
            conn = connect(Path(d) / "pm.db")
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0], 5000)
            conn.close()

    def test_a_writer_waiting_on_another_writer_does_not_lock(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "pm.db"
            b = connect(path)
            a = sqlite3.connect(path, check_same_thread=False)
            a.execute("BEGIN IMMEDIATE")
            a.execute("INSERT INTO settings(key, value) VALUES('held', 'x')")
            timer = threading.Timer(0.3, a.commit)
            timer.start()
            try:
                set_setting(b, "waited", "yes")
            finally:
                timer.join()
                a.close()
                b.close()
            conn = connect(path)
            self.assertEqual(get_setting(conn, "waited", ""), "yes")
            conn.close()

    def test_put_setting_rejects_unknown_keys_and_keeps_the_old_value(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        with self.assertRaisesRegex(ValueError, "unknown setting 'nope'"):
            put_setting(conn, "nope", "1")
        with self.assertRaisesRegex(ValueError, "expected a range like 09-17"):
            put_setting(conn, "peak", "25-30")
        self.assertEqual(get_setting(conn, "peak", DEFAULTS["peak"]), "09-12")
        put_setting(conn, "peak", "10-13")
        self.assertEqual(get_setting(conn, "peak", DEFAULTS["peak"]), "10-13")

    def test_phase10_tables_and_the_energy_column(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertLessEqual({"task_links", "spots"}, tables)
        self.assertIn("energy", {r[1] for r in conn.execute("PRAGMA table_info(sessions)")})

    def test_an_old_database_gets_the_energy_column(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "pm.db"
            old = sqlite3.connect(path)
            old.execute("CREATE TABLE sessions(id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL,"
                        " start TEXT NOT NULL, end TEXT, note TEXT)")
            old.commit()
            old.close()
            conn = connect(path)
            self.addCleanup(conn.close)
            self.assertIn("energy", {r[1] for r in conn.execute("PRAGMA table_info(sessions)")})

    def test_llm_cmd_is_a_command_line_or_empty(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        put_setting(conn, "llm_cmd", "")
        put_setting(conn, "llm_cmd", "my-llm --model small")
        for bad in ["echo 'unclosed", "   "]:
            with self.subTest(value=bad), self.assertRaisesRegex(ValueError, "^llm_cmd must be a command line"):
                put_setting(conn, "llm_cmd", bad)
        self.assertEqual(get_setting(conn, "llm_cmd", ""), "my-llm --model small")

    def test_lh_dir_holds_chats(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError, r"^lh_dir must be LearnHarness's data folder, the one that holds chats/$"):
                put_setting(conn, "lh_dir", d)
            (Path(d) / "chats").mkdir()
            put_setting(conn, "lh_dir", d)
            self.assertEqual(get_setting(conn, "lh_dir", ""), d)
            put_setting(conn, "lh_dir", "")
            self.assertEqual(get_setting(conn, "lh_dir", "x"), "")
        self.assertEqual({r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'lh_%'")},
                         {"lh_sessions", "lh_days", "lh_cards"})

    def test_agent_tables_and_budget(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"jobs", "suggestions"} <= names)
        for bad in ("501", "-1", "many", "1.5"):
            with self.subTest(value=bad), self.assertRaisesRegex(ValueError, "^agent_daily_calls must be between 0 and 500$"):
                put_setting(conn, "agent_daily_calls", bad)
        put_setting(conn, "agent_daily_calls", "30")
        self.assertEqual(get_setting(conn, "agent_daily_calls", "0"), "30")

    def test_put_setting_requires_text(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        for key, value in (([], "1"), ("peak", 5), (None, None)):
            with self.subTest(key=key, value=value):
                with self.assertRaisesRegex(ValueError, "setting key and value must be text"):
                    put_setting(conn, key, value)

    def test_put_setting_checks_hours(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        for value in ("abc", "", "nan", "inf", "-inf", "0.001", "17"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError,
                                            "hours_per_day must be between 0.1 and 16"):
                    put_setting(conn, "hours_per_day", value)
        put_setting(conn, "hours_per_day", "0.1")
        self.assertEqual(get_setting(conn, "hours_per_day", ""), "0.1")
        put_setting(conn, "hours_per_day", "16")
        self.assertEqual(get_setting(conn, "hours_per_day", ""), "16")

    def test_put_setting_checks_the_notes_url(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        for value in ("http://x.dev", "https://", "https:///x", "x.dev", " https://x.dev",
                      "https://x.dev ", "https://x.dev:abc", "https://x.dev:99999",
                      "https://x.dev/?a=1", "https://x.dev#s"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError,
                                            "notes_url must be empty or https://your-site"):
                    put_setting(conn, "notes_url", value)
        for value in ("", "https://x.dev"):
            put_setting(conn, "notes_url", value)
            self.assertEqual(get_setting(conn, "notes_url", ""), value)

    def test_put_setting_refuses_a_bad_notes_url_and_keeps_the_old_value(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        put_setting(conn, "notes_url", "https://good.dev")
        for value in ("https://x.dev ", "https://x.dev:abc", "https://x.dev:99999",
                      "https://x.dev/?a=1", "https://x.dev#s"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError,
                                            "notes_url must be empty or https://your-site"):
                    put_setting(conn, "notes_url", value)
                self.assertEqual(get_setting(conn, "notes_url", ""), "https://good.dev")

    def test_put_setting_checks_notes_dir(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        with tempfile.TemporaryDirectory() as d:
            put_setting(conn, "notes_dir", d)
            self.assertEqual(get_setting(conn, "notes_dir", ""), d)
            Path(d, "docs").mkdir()
            old = os.getcwd()
            os.chdir(d)
            try:
                with self.assertRaisesRegex(
                        ValueError, "notes_dir must be a folder, like ~/prod-max/notes-site/docs"):
                    put_setting(conn, "notes_dir", "docs")
            finally:
                os.chdir(old)
        for value in ("/nope/x", " /tmp", "/tmp ", "~nosuchuser_zz/x"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                        ValueError, "notes_dir must be a folder, like ~/prod-max/notes-site/docs"):
                    put_setting(conn, "notes_dir", value)
        put_setting(conn, "notes_dir", "")
        self.assertEqual(get_setting(conn, "notes_dir", "x"), "")

    def test_put_setting_checks_watch_folders(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        for key in ("watch", "watch_ignore"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(
                        ValueError, f"{key} folders must be full paths like ~/Downloads"):
                    put_setting(conn, key, "Downloads")
                with self.assertRaisesRegex(ValueError, "full paths"):
                    put_setting(conn, key, "/tmp: ~/x")  # files.roots doesn't strip, so " ~/x" is relative
                put_setting(conn, key, "/tmp:~/Downloads")
                self.assertEqual(get_setting(conn, key, ""), "/tmp:~/Downloads")
        put_setting(conn, "watch_ignore", "")
        self.assertEqual(get_setting(conn, "watch_ignore", "x"), "")

    def test_put_setting_refuses_watch_folders_with_outer_whitespace(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        for key in ("watch", "watch_ignore"):
            for value in ("/tmp:~/Downloads ", " /tmp", "/tmp: ~/x"):
                with self.subTest(key=key, value=value):
                    with self.assertRaisesRegex(
                            ValueError, f"{key} folders must be full paths like ~/Downloads"):
                        put_setting(conn, key, value)
            put_setting(conn, key, ":/tmp::")
            self.assertEqual(get_setting(conn, key, ""), ":/tmp::")

    def test_put_setting_checks_ranges_and_course_codes(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        with self.assertRaisesRegex(ValueError, "0 <= start < end <= 24"):
            put_setting(conn, "nudge_hours", "22-08")
        with self.assertRaisesRegex(ValueError, "course_codes must be name=CODE pairs"):
            put_setting(conn, "course_codes", "os")
        for value in ("x", "0", "201"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError,
                                            "new_per_day must be between 1 and 200"):
                    put_setting(conn, "new_per_day", value)
        put_setting(conn, "new_per_day", "200")
        self.assertEqual(get_setting(conn, "new_per_day", ""), "200")

    def test_settings_has_every_default(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        self.assertEqual(settings(conn), DEFAULTS)
        put_setting(conn, "peak", "10-13")
        self.assertEqual(settings(conn), {**DEFAULTS, "peak": "10-13"})
