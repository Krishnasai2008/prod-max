import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from pm.db import connect
from pm.links import MAX_LINKS, add_link, drop_link, links, open_link, open_links
from pm.tasks import add_task, done

NOW = datetime(2026, 11, 9, 10, 0)


class TestLinks(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.root = Path(self.d.name)
        self.c = connect(":memory:")
        self.task_id = add_task(self.c, "OS lab", 60, now=NOW)
        for name in ("a.pdf", "run.sh", "app.desktop", "notes.md"):
            (self.root / name).write_text("x")
        (self.root / "folder").mkdir()
        self.folder = self.root / "folder"

    def tearDown(self):
        self.c.close()
        self.d.cleanup()

    def test_a_pdf_link_is_a_file_at_its_resolved_path(self):
        link_id = add_link(self.c, 1, str(self.root / "a.pdf"), NOW)
        link, = links(self.c, 1)
        self.assertEqual(link.id, link_id)
        self.assertEqual(link.kind, "file")
        self.assertEqual(link.target, str((self.root / "a.pdf").resolve()))

    def test_a_folder_link_is_a_folder(self):
        add_link(self.c, 1, str(self.folder), NOW)
        link, = links(self.c, 1)
        self.assertEqual((link.kind, link.target), ("folder", str(self.folder.resolve())))

    def test_a_link_whose_file_is_gone_is_missing(self):
        add_link(self.c, 1, str(self.root / "a.pdf"), NOW)
        (self.root / "a.pdf").unlink()
        link, = links(self.c, 1)
        self.assertEqual(link.kind, "missing")

    def test_an_address_is_kept_as_typed(self):
        target = "https://example.com/a?b=1"
        add_link(self.c, 1, target, NOW)
        link, = links(self.c, 1)
        self.assertEqual((link.kind, link.target), ("url", target))

    def test_an_address_with_spaces_or_control_characters_is_refused(self):
        for target in ("https://x.dev/a b", "https://x.dev/a\nb", "https://x.dev/a\tb",
                       "https://x.dev/a\x7fb"):
            with self.subTest(target=target):
                with self.assertRaisesRegex(ValueError, "spaces or control characters"):
                    add_link(self.c, 1, target, NOW)

    def test_a_relative_target_is_refused(self):
        with self.assertRaisesRegex(ValueError, "give a full path"):
            add_link(self.c, 1, "notes.md", NOW)

    def test_a_missing_path_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no such file"):
            add_link(self.c, 1, str(self.root / "nope.pdf"), NOW)

    def test_an_unreadable_path_is_refused_as_missing(self):
        with mock.patch.object(Path, "exists", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(ValueError, "no such file"):
                add_link(self.c, 1, str(self.root / "a.pdf"), NOW)

    def test_an_unreadable_link_counts_as_missing(self):
        add_link(self.c, 1, str(self.root / "a.pdf"), NOW)
        calls = []
        with mock.patch.object(Path, "exists", side_effect=PermissionError("denied")):
            link, = links(self.c, 1)
            opened, skipped = open_links(self.c, 1, calls.append)
        self.assertEqual(link.kind, "missing")
        self.assertEqual((opened, calls), (0, []))
        self.assertTrue(skipped[0].startswith("gone "))

    def test_an_empty_target_is_refused(self):
        with self.assertRaisesRegex(ValueError, "give a full path or an http"):
            add_link(self.c, 1, "   ", NOW)

    def test_an_address_over_2000_characters_is_refused(self):
        with self.assertRaisesRegex(ValueError, "too long"):
            add_link(self.c, 1, "https://" + "a" * 2000, NOW)

    def test_the_same_target_twice_is_refused(self):
        add_link(self.c, 1, str(self.root / "a.pdf"), NOW)
        with self.assertRaisesRegex(ValueError, "already linked"):
            add_link(self.c, 1, str(self.root / "a.pdf"), NOW)

    def test_a_task_holds_at_most_ten_links(self):
        for n in range(MAX_LINKS):
            (self.root / f"f{n}.pdf").write_text("x")
            add_link(self.c, 1, str(self.root / f"f{n}.pdf"), NOW)
        (self.root / "extra.pdf").write_text("x")
        with self.assertRaisesRegex(ValueError, f"at most {MAX_LINKS} links"):
            add_link(self.c, 1, str(self.root / "extra.pdf"), NOW)

    def test_an_unknown_task_is_a_lookup_error(self):
        with self.assertRaisesRegex(LookupError, r"no task #99"):
            add_link(self.c, 99, str(self.root / "a.pdf"), NOW)

    def test_a_done_task_refuses_links(self):
        done(self.c, 1, NOW)
        with self.assertRaisesRegex(ValueError, "#1 is already done"):
            add_link(self.c, 1, str(self.root / "a.pdf"), NOW)

    def test_open_links_opens_documents_folders_and_addresses_but_not_scripts(self):
        add_link(self.c, 1, str(self.root / "a.pdf"), NOW)
        add_link(self.c, 1, str(self.root / "run.sh"), NOW)
        add_link(self.c, 1, str(self.root / "app.desktop"), NOW)
        add_link(self.c, 1, str(self.folder), NOW)
        add_link(self.c, 1, "https://x.dev", NOW)
        calls = []
        opened, skipped = open_links(self.c, 1, calls.append)
        folder = str(self.root.resolve())
        self.assertEqual((opened, skipped), (5, []))
        self.assertEqual(calls, [str((self.root / "a.pdf").resolve()), folder, folder,
                                 str(self.folder.resolve()), "https://x.dev"])
        self.assertNotIn(str((self.root / "run.sh").resolve()), calls)
        self.assertNotIn(str((self.root / "app.desktop").resolve()), calls)

    def test_a_deleted_link_is_skipped(self):
        add_link(self.c, 1, str(self.root / "a.pdf"), NOW)
        add_link(self.c, 1, str(self.folder), NOW)
        gone = self.root / "a.pdf"
        gone.unlink()
        calls = []
        opened, skipped = open_links(self.c, 1, calls.append)
        self.assertEqual(opened, 1)
        self.assertEqual(calls, [str(self.folder.resolve())])
        self.assertEqual(len(skipped), 1)
        self.assertTrue(skipped[0].startswith("gone "))
        self.assertIn(gone.name, skipped[0])

    def test_a_link_replaced_by_a_symlink_to_a_script_opens_the_folder(self):
        path = self.root / "a.pdf"
        add_link(self.c, 1, str(path), NOW)
        script = self.root / "run.sh"
        try:
            path.unlink()
            path.symlink_to(script)
        except OSError:
            self.skipTest("symlinks are not supported here")
        calls = []
        opened, skipped = open_links(self.c, 1, calls.append)
        self.assertEqual((opened, skipped), (1, []))
        self.assertEqual(calls, [str(self.root.resolve())])
        self.assertNotIn(str(script.resolve()), calls)

    def test_a_linked_symlink_retargeted_to_a_script_opens_the_folder(self):
        path = self.root / "notes.pdf"
        path.write_text("x")
        add_link(self.c, 1, str(path), NOW)
        try:
            path.unlink()
            path.symlink_to(self.root / "a.pdf")
            path.unlink()
            path.symlink_to(self.root / "run.sh")
        except OSError:
            self.skipTest("symlinks are not supported here")
        calls = []
        opened, skipped = open_links(self.c, 1, calls.append)
        self.assertEqual((opened, skipped), (1, []))
        self.assertEqual(calls, [str(self.root.resolve())])
        self.assertNotIn(str((self.root / "run.sh").resolve()), calls)

    def test_an_opener_that_cannot_start_stops_the_loop(self):
        add_link(self.c, 1, str(self.root / "a.pdf"), NOW)
        add_link(self.c, 1, str(self.folder), NOW)
        calls = []

        def refuse(target):
            calls.append(target)
            raise ValueError("xdg-open is not installed")

        self.assertEqual(open_links(self.c, 1, refuse), (0, ["xdg-open is not installed"]))
        self.assertEqual(len(calls), 1)

    def test_open_link_opens_one_link(self):
        first = add_link(self.c, 1, str(self.root / "a.pdf"), NOW)
        add_link(self.c, 1, str(self.folder), NOW)
        calls = []
        self.assertEqual(open_link(self.c, 1, first, calls.append), (1, []))
        self.assertEqual(calls, [str((self.root / "a.pdf").resolve())])

    def test_open_link_refuses_a_link_on_another_task(self):
        link_id = add_link(self.c, 1, str(self.root / "a.pdf"), NOW)
        add_task(self.c, "other", 30, now=NOW)
        with self.assertRaisesRegex(LookupError, "no such link"):
            open_link(self.c, 2, link_id, lambda target: None)

    def test_open_link_reports_a_missing_target(self):
        link_id = add_link(self.c, 1, str(self.root / "a.pdf"), NOW)
        gone = self.root / "a.pdf"
        gone.unlink()
        calls = []
        opened, skipped = open_link(self.c, 1, link_id, calls.append)
        self.assertEqual(opened, 0)
        self.assertEqual(calls, [])
        self.assertTrue(skipped[0].startswith("gone "))

    def test_drop_link_returns_the_target_and_removes_it(self):
        first = add_link(self.c, 1, str(self.root / "a.pdf"), NOW)
        add_link(self.c, 1, str(self.folder), NOW)
        target = str((self.root / "a.pdf").resolve())
        self.assertEqual(drop_link(self.c, 1, first), target)
        self.assertEqual([link.target for link in links(self.c, 1)],
                         [str(self.folder.resolve())])

    def test_drop_link_with_an_unknown_link_is_a_lookup_error(self):
        add_link(self.c, 1, str(self.root / "a.pdf"), NOW)
        with self.assertRaisesRegex(LookupError, "no such link"):
            drop_link(self.c, 1, 99)
