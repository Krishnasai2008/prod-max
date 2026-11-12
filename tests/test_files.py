import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from pm.db import connect, set_setting
from pm.files import (Hit, Scan, course_codes, course_of, courses, find, open_file, recent,
                      reveal, roots, scan, total)
from pm.tasks import add_task

NOW = datetime(2026, 11, 9, 10, 0)
OLD = NOW - timedelta(minutes=1)


def fake_extract(path):
    return path.read_text() if path.suffix == ".txt" else ""


class TestFiles(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.root = Path(self.d.name)
        self.c = connect(":memory:")
        set_setting(self.c, "watch", str(self.root))

    def tearDown(self):
        self.c.close()
        self.d.cleanup()

    def write(self, name, text, when=OLD):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        os.utime(path, (when.timestamp(), when.timestamp()))
        return path

    @unittest.skipIf(os.geteuid() == 0, "root can read anything")
    def test_unreadable_subfolder_keeps_its_entries(self):
        self.write("sub/a.txt", "paging")
        self.assertEqual(scan(self.c, NOW, fake_extract).added, 1)
        sub = self.root / "sub"
        sub.chmod(0)
        try:
            self.assertEqual(scan(self.c, NOW, fake_extract).removed, 0)
        finally:
            sub.chmod(0o755)
        self.assertEqual(len(find(self.c, "paging")), 1)

    def test_dependency_and_cache_folders_are_skipped(self):
        self.write("node_modules/x.txt", "paging")
        self.write("proj/__pycache__/y.txt", "paging")
        self.write("proj/venv/lib/site-packages/z.txt", "paging")
        self.write("proj/main.txt", "paging")
        self.assertEqual(scan(self.c, NOW, fake_extract).added, 1)

    def test_watch_ignore_skips_a_folder_and_drops_what_it_had(self):
        self.write("Data/Packages/a.txt", "tensor")
        self.write("lab.txt", "paging")
        self.assertEqual(scan(self.c, NOW, fake_extract).added, 2)
        set_setting(self.c, "watch_ignore", f"{self.root}/Data/:/nowhere")
        self.assertEqual(scan(self.c, NOW, fake_extract), Scan(0, 0, 1, 0))
        self.assertEqual(find(self.c, "tensor"), [])
        self.assertEqual(len(find(self.c, "paging")), 1)

    def test_roots(self):
        set_setting(self.c, "watch", f"{self.root}:~/Downloads")
        self.assertEqual(roots(self.c), [self.root, Path.home() / "Downloads"])

    def test_index_and_rescan(self):
        self.write("a.txt", "alpha")
        self.write("b.txt", "beta")
        self.write("c.txt", "gamma")
        self.assertEqual(scan(self.c, NOW, extract=fake_extract), Scan(3, 0, 0, 0))
        self.assertEqual(scan(self.c, NOW, extract=fake_extract), Scan(0, 0, 0, 0))

    def test_changed_file_is_updated(self):
        self.write("a.txt", "alpha")
        self.assertEqual(scan(self.c, NOW, extract=fake_extract).added, 1)
        self.write("a.txt", "alpha and more", when=NOW)
        result = scan(self.c, NOW + timedelta(minutes=1), extract=fake_extract)
        self.assertEqual(result.updated, 1)

    def test_deleted_file_is_removed(self):
        path = self.write("a.txt", "alpha")
        scan(self.c, NOW, extract=fake_extract)
        self.assertEqual(len(find(self.c, "alpha")), 1)
        path.unlink()
        self.assertEqual(scan(self.c, NOW, extract=fake_extract).removed, 1)
        self.assertEqual(find(self.c, "alpha"), [])

    def test_fresh_edit_keeps_the_old_entry_until_it_settles(self):
        self.write("a.txt", "alpha")
        scan(self.c, NOW, extract=fake_extract)
        self.write("a.txt", "beta", when=NOW + timedelta(seconds=5))
        self.assertEqual(scan(self.c, NOW, extract=fake_extract).updated, 0)
        self.assertEqual(len(find(self.c, "alpha")), 1)
        later = NOW + timedelta(seconds=30)
        self.assertEqual(scan(self.c, later, extract=fake_extract).updated, 1)
        self.assertEqual(len(find(self.c, "beta")), 1)

    def test_skips_partial_hidden_and_fresh_files(self):
        self.write("a.pdf.crdownload", "partial")
        self.write(".hidden/x.txt", "hidden")
        self.write("fresh.txt", "fresh", when=NOW - timedelta(seconds=5))
        self.assertEqual(scan(self.c, NOW, extract=fake_extract), Scan(0, 0, 0, 0))

    def test_limit_leaves_pending(self):
        self.write("a.txt", "alpha")
        self.write("b.txt", "beta")
        self.write("c.txt", "gamma")
        self.assertEqual(scan(self.c, NOW, extract=fake_extract, limit=2), Scan(2, 0, 0, 1))
        self.assertEqual(scan(self.c, NOW, extract=fake_extract, limit=2), Scan(1, 0, 0, 0))

    def test_symlink_outside_root_is_not_indexed(self):
        with tempfile.TemporaryDirectory() as other:
            target = Path(other) / "secret.txt"
            target.write_text("secret")
            os.utime(target, (OLD.timestamp(), OLD.timestamp()))
            link = self.root / "link.txt"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("symlinks are not supported here")
            self.assertEqual(scan(self.c, NOW, extract=fake_extract), Scan(0, 0, 0, 0))
            self.assertEqual(find(self.c, "secret"), [])

    def test_symlink_root_is_not_walked(self):
        inner = self.root / "inner"
        inner.mkdir()
        self.write("inner/a.txt", "alpha")
        link = self.root / "linked"
        try:
            link.symlink_to(inner)
        except OSError:
            self.skipTest("symlinks are not supported here")
        set_setting(self.c, "watch", str(link))
        self.assertEqual(scan(self.c, NOW, extract=fake_extract), Scan(0, 0, 0, 0))

    def test_nested_roots_index_a_file_once(self):
        nested = self.root / "sub"
        self.write("sub/a.txt", "alpha")
        set_setting(self.c, "watch", f"{self.root}:{nested}")
        self.assertEqual(scan(self.c, NOW, extract=fake_extract), Scan(1, 0, 0, 0))
        self.assertEqual(len(find(self.c, "alpha")), 1)
        self.assertEqual(
            self.c.execute("SELECT COUNT(*) FROM files").fetchone()[0], 1)

    def test_missing_root_keeps_old_rows(self):
        self.write("a.txt", "alpha")
        scan(self.c, NOW, extract=fake_extract)
        set_setting(self.c, "watch", f"{self.root}:{self.root / 'missing'}")
        self.assertEqual(scan(self.c, NOW, extract=fake_extract), Scan(0, 0, 0, 0))
        self.assertEqual(len(find(self.c, "alpha")), 1)

    def test_course_codes_parsing(self):
        set_setting(self.c, "course_codes", "os=CS F372; dbms=CS F212")
        self.assertEqual(course_codes(self.c), {"os": "CS F372", "dbms": "CS F212"})
        empty = connect(":memory:")
        self.assertEqual(course_codes(empty), {})
        empty.close()

    def test_course_of_name_and_code(self):
        self.assertEqual(course_of("lab_os_3.pdf", "", {}, ["os"]), "os")
        self.assertIsNone(course_of("photos.jpg", "", {}, ["os"]))
        self.assertEqual(course_of("handout.pdf", "Course No: CS-F372 Operating",
                                   {"os": "CS F372"}, []), "os")

    def test_find_snippet_and_syntax(self):
        self.write("a.txt", "the TLB caches pages")
        scan(self.c, NOW, extract=fake_extract)
        hits = find(self.c, "TLB")
        self.assertEqual(len(hits), 1)
        self.assertIn("[TLB]", hits[0].snippet)
        self.assertEqual(find(self.c, "C++ (pointers"), [])
        with self.assertRaises(ValueError):
            find(self.c, "  ")

    def test_name_match_outranks_body_match(self):
        self.write("tlb_notes.txt", "nothing here")
        self.write("notes.txt", "the TLB caches pages")
        scan(self.c, NOW, extract=fake_extract)
        hits = find(self.c, "tlb")
        self.assertEqual([Path(h.path).name for h in hits], ["tlb_notes.txt", "notes.txt"])
        self.assertIsInstance(hits[0], Hit)

    def test_find_filters_by_course(self):
        self.write("a.txt", "the TLB caches pages")
        scan(self.c, NOW, extract=fake_extract)
        self.c.execute("UPDATE files SET course='os'")
        self.c.commit()
        self.assertEqual(len(find(self.c, "TLB", course="os")), 1)
        self.assertEqual(find(self.c, "TLB", course="dbms"), [])

    def test_course_setting_change_retags_indexed_files(self):
        self.write("handout.txt", "Course No: CS-F372 Operating systems")
        scan(self.c, NOW, extract=fake_extract)
        self.assertIsNone(find(self.c, "Operating")[0].course)
        set_setting(self.c, "course_codes", "os=CS F372")
        self.assertEqual(scan(self.c, NOW, extract=fake_extract), Scan(0, 0, 0, 0))
        hits = find(self.c, "Operating", course="os")
        self.assertEqual([hit.course for hit in hits], ["os"])

    def test_top_folder_is_the_course(self):
        self.write("ai-ml/output/phase-1/notes.txt", "alpha")
        self.write("loose.txt", "beta")
        scan(self.c, NOW, extract=fake_extract)
        self.assertEqual([hit.course for hit in find(self.c, "alpha", course="ai-ml")], ["ai-ml"])
        self.assertIsNone(find(self.c, "beta")[0].course)

    def test_course_code_beats_folder(self):
        set_setting(self.c, "course_codes", "os=CS F372")
        self.write("ai-ml/handout.txt", "Course No: CS F372")
        scan(self.c, NOW, extract=fake_extract)
        self.assertEqual(find(self.c, "handout")[0].course, "os")

    def test_changing_watch_retags_folder_courses(self):
        self.write("ai-ml/sub/notes.txt", "alpha")
        scan(self.c, NOW, extract=fake_extract)
        set_setting(self.c, "watch", str(self.root / "ai-ml"))
        self.assertEqual(scan(self.c, NOW, extract=fake_extract), Scan(0, 0, 0, 0))
        self.assertEqual(find(self.c, "alpha")[0].course, "sub")

    def test_course_on_a_task_retags_indexed_files(self):
        self.write("lab_os_3.txt", "page tables")
        scan(self.c, NOW, extract=fake_extract)
        self.assertIsNone(find(self.c, "page")[0].course)
        add_task(self.c, "OS lab 3", 60, now=NOW, course="os")
        scan(self.c, NOW, extract=fake_extract)
        self.assertEqual([hit.course for hit in find(self.c, "page")], ["os"])


    def index(self, *names):
        for name in names:
            self.write(name, "text")
        scan(self.c, NOW, extract=fake_extract)
        return {Path(row["path"]).name: row["id"]
                for row in self.c.execute("SELECT id, path FROM files")}

    def test_find_hits_carry_the_row_id_and_bound_marks(self):
        self.write("a.txt", "the TLB caches pages")
        scan(self.c, NOW, extract=fake_extract)
        row = self.c.execute("SELECT id FROM files").fetchone()
        hit = find(self.c, "TLB")[0]
        self.assertEqual(hit.id, row["id"])
        marked = find(self.c, "TLB", marks=("\x02", "\x03"))[0]
        self.assertIn("\x02", marked.snippet)
        self.assertNotIn("[", marked.snippet)

    def test_find_survives_quotes_wildcards_and_nul(self):
        self.write("a.txt", "the TLB caches pages")
        scan(self.c, NOW, extract=fake_extract)
        self.assertIsInstance(find(self.c, '"quotes" AND * ('), list)
        self.assertEqual(len(find(self.c, "TLB\x00caches")), 1)
        with self.assertRaises(ValueError):
            find(self.c, " \x00 ")

    def test_recent_is_newest_first_with_empty_snippets(self):
        self.write("a.txt", "alpha")
        self.write("b.txt", "beta")
        scan(self.c, NOW, extract=fake_extract)
        hits = recent(self.c)
        self.assertEqual([Path(hit.path).name for hit in hits], ["b.txt", "a.txt"])
        self.assertEqual([hit.snippet for hit in hits], ["", ""])
        self.assertTrue(all(hit.id for hit in hits))
        self.write("a.txt", "alpha again", when=NOW)
        scan(self.c, NOW + timedelta(minutes=1), extract=fake_extract)
        self.assertEqual(Path(recent(self.c)[0].path).name, "a.txt")
        self.assertEqual(len(recent(self.c, limit=1)), 1)

    def test_recent_filters_by_course(self):
        self.write("a.txt", "alpha")
        self.write("b.txt", "beta")
        scan(self.c, NOW, extract=fake_extract)
        self.c.execute("UPDATE files SET course='os' WHERE path=?",
                       (str(self.root / "a.txt"),))
        self.c.commit()
        self.assertEqual([Path(hit.path).name for hit in recent(self.c, course="os")],
                         ["a.txt"])
        self.assertEqual(recent(self.c, course="dbms"), [])
        self.assertEqual(total(self.c), 2)

    def test_courses_are_sorted_and_skip_unset(self):
        self.write("a.txt", "alpha")
        self.write("b.txt", "beta")
        self.write("c.txt", "gamma")
        scan(self.c, NOW, extract=fake_extract)
        self.c.execute("UPDATE files SET course='os' WHERE path=?",
                       (str(self.root / "a.txt"),))
        self.c.execute("UPDATE files SET course='dbms' WHERE path=?",
                       (str(self.root / "b.txt"),))
        self.c.commit()
        self.assertEqual(courses(self.c), ["dbms", "os"])

    def test_open_file_hands_documents_to_the_opener(self):
        names = ["a.pdf", "b.md", "c.txt", "d.png", "e.docx", "f.PDF"]
        ids = self.index(*names)
        for name in names:
            with self.subTest(name=name):
                calls = []
                target = str((self.root / name).resolve())
                self.assertEqual(open_file(self.c, ids[name], calls.append), target)
                self.assertEqual(calls, [target])

    def test_open_file_refuses_programs_and_pages(self):
        names = ["a.desktop", "b.sh", "c.py", "d.js", "e.html", "f.ipynb"]
        ids = self.index(*names)
        for name in names:
            with self.subTest(name=name):
                calls = []
                with self.assertRaisesRegex(ValueError, "use show in folder"):
                    open_file(self.c, ids[name], calls.append)
                self.assertEqual(calls, [])
        with self.assertRaisesRegex(ValueError, r"won't open a \.desktop file"):
            open_file(self.c, ids["a.desktop"], lambda target: None)

    def test_open_file_refuses_a_file_with_no_extension(self):
        ids = self.index("README")
        calls = []
        with self.assertRaisesRegex(ValueError, "a file with no extension"):
            open_file(self.c, ids["README"], calls.append)
        self.assertEqual(calls, [])

    def test_open_and_reveal_refuse_a_file_that_is_gone(self):
        ids = self.index("a.pdf")
        (self.root / "a.pdf").unlink()
        calls = []
        for func in (open_file, reveal):
            with self.subTest(func=func.__name__):
                with self.assertRaisesRegex(ValueError, "that file is gone"):
                    func(self.c, ids["a.pdf"], calls.append)
        self.assertEqual(calls, [])

    def test_a_pdf_symlink_to_a_script_is_refused(self):
        ids = self.index("paper.pdf")
        script = self.root / "run.sh"
        script.write_text("#!/bin/sh\n")
        path = self.root / "paper.pdf"
        path.unlink()
        try:
            path.symlink_to(script)
        except OSError:
            self.skipTest("symlinks are not supported here")
        calls = []
        with self.assertRaisesRegex(ValueError, "that file is gone"):
            open_file(self.c, ids["paper.pdf"], calls.append)
        self.assertEqual(calls, [])

    def test_reveal_opens_the_parent_of_any_file(self):
        ids = self.index("tool.desktop")
        calls = []
        target = str(self.root.resolve())
        self.assertEqual(reveal(self.c, ids["tool.desktop"], calls.append), target)
        self.assertEqual(calls, [target])

    def test_unknown_file_id_is_a_lookup_error(self):
        for func in (open_file, reveal):
            with self.subTest(func=func.__name__):
                with self.assertRaisesRegex(LookupError, r"no file #99"):
                    func(self.c, 99)

    def test_missing_xdg_open_is_refused(self):
        ids = self.index("a.pdf")
        with mock.patch("pm.files.shutil.which", return_value=None):
            with self.assertRaisesRegex(ValueError, "xdg-open is not installed"):
                open_file(self.c, ids["a.pdf"])

    def test_the_default_opener_starts_xdg_open_without_a_shell(self):
        ids = self.index("a.pdf")
        target = str((self.root / "a.pdf").resolve())
        with mock.patch("pm.files.shutil.which", return_value="/usr/bin/xdg-open"):
            with mock.patch("pm.files.subprocess.Popen") as popen:
                open_file(self.c, ids["a.pdf"])
        args, kwargs = popen.call_args
        self.assertEqual(args, (["/usr/bin/xdg-open", target],))
        self.assertNotIn("shell", kwargs)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
        self.assertIs(kwargs["start_new_session"], True)

    def test_a_failed_launch_is_a_value_error(self):
        ids = self.index("a.pdf")
        for func in (open_file, reveal):
            with self.subTest(func=func.__name__):
                with mock.patch("pm.files.shutil.which", return_value="/usr/bin/xdg-open"), \
                        mock.patch("pm.files.subprocess.Popen",
                                   side_effect=PermissionError("denied")):
                    with self.assertRaisesRegex(ValueError,
                                                "couldn't start xdg-open: denied"):
                        func(self.c, ids["a.pdf"])
