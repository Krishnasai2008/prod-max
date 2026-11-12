import tempfile
import unittest
from pathlib import Path

from pm.db import connect, put_setting, set_setting
from pm.notes import anchors, notes_dir, slug, url_of

NOTES = """# Paging
intro

## TLB
a
b
c

## Example
one
two
three

## Example
four
five
six

## Cost of $O(n)$
big O
"""


class TestSlug(unittest.TestCase):
    def test_slug_follows_the_generator(self):
        cases = {
            "Page Replacement (LRU)": "page-replacement-lru",
            "rotate_180": "rotate_180",
            "Größe & Zeit": "groe-zeit",
            "  A  -  B  ": "a-b",
            "!!!": "",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(slug(text), expected)

    def test_repeated_titles_get_a_suffix(self):
        self.assertEqual(anchors(["Example", "Example", "Example"]),
                         ["example", "example_1", "example_2"])

    def test_a_trailing_number_is_raised(self):
        self.assertEqual(anchors(["rotate_180", "rotate_180", "rotate_180"]),
                         ["rotate_180", "rotate_181", "rotate_182"])

    def test_an_empty_slug_still_gets_an_id(self):
        self.assertEqual(anchors(["!!!", "Intro"]), ["_1", "intro"])


class TestUrlOf(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.dir = Path(self.d.name)
        (self.dir / "msm").mkdir()
        (self.dir / "msm" / "module-8.md").write_text("# Module 8\n")
        (self.dir / "msm" / "index.md").write_text("# MSM\n")
        (self.dir / "msm" / "README.md").write_text("# MSM\n")
        (self.dir / "index.md").write_text("# Home\n")
        (self.dir / "my notes").mkdir()
        (self.dir / "my notes" / "a b.md").write_text("# Notes\n")
        (self.dir / "os").mkdir()
        self.paging = self.dir / "os" / "paging.md"
        self.paging.write_text(NOTES)
        (self.dir / "os" / "paper.pdf").write_bytes(b"%PDF-1.4")

    def tearDown(self):
        self.d.cleanup()

    def test_page_addresses(self):
        d = self.dir
        self.assertEqual(url_of(d / "msm" / "module-8.md", None, d), "/msm/module-8/")
        self.assertEqual(url_of(d / "msm" / "index.md", None, d), "/msm/")
        self.assertEqual(url_of(d / "msm" / "README.md", None, d), "/msm/")
        self.assertEqual(url_of(d / "index.md", None, d), "/")
        self.assertEqual(url_of(d / "my notes" / "a b.md", None, d), "/my%20notes/a%20b/")

    def test_headings_become_anchors(self):
        d, paging = self.dir, self.paging
        self.assertEqual(url_of(paging, "TLB", d), "/os/paging/#tlb")
        self.assertEqual(url_of(paging, "tlb", d), "/os/paging/#tlb")
        self.assertEqual(url_of(paging, "Example", d), "/os/paging/#example")

    def test_other_locators_get_the_page_only(self):
        d, paging = self.dir, self.paging
        for locator in ("L10-25", "L10", "p3", "Nope", "Cost of $O(n)$"):
            with self.subTest(locator=locator):
                self.assertEqual(url_of(paging, locator, d), "/os/paging/")

    def test_a_deleted_file_still_has_a_page_address(self):
        gone = self.dir / "os" / "gone.md"
        gone.write_text("# Gone\n## Lost\n")
        gone.unlink()
        self.assertEqual(url_of(gone, "Lost", self.dir), "/os/gone/")

    def test_paths_outside_notes_dir_have_no_address(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        target = Path(outside.name) / "outside.md"
        target.write_text("# Outside\n")
        self.assertIsNone(url_of(target, "Outside", self.dir))
        self.assertIsNone(url_of(self.dir / "os" / "paper.pdf", None, self.dir))
        self.assertIsNone(url_of(self.paging, "TLB", None))

    def test_a_symlink_to_an_outside_file_has_no_address(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        target = Path(outside.name) / "secret.md"
        target.write_text("# Secret\n")
        link = self.dir / "os" / "link.md"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("symlinks are not available here")
        self.assertIsNone(url_of(link, None, self.dir))


class TestNotesDir(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_empty_setting_is_none(self):
        self.assertIsNone(notes_dir(self.conn))

    def test_setting_is_expanded_and_resolved(self):
        folder = Path(self.d.name) / "notes"
        folder.mkdir()
        put_setting(self.conn, "notes_dir", str(folder))
        self.assertEqual(notes_dir(self.conn), folder.resolve())

    def test_a_folder_that_vanished_is_none(self):
        folder = Path(self.d.name) / "notes"
        folder.mkdir()
        put_setting(self.conn, "notes_dir", str(folder))
        folder.rmdir()
        self.assertIsNone(notes_dir(self.conn))

    def test_an_unexpandable_setting_is_none(self):
        set_setting(self.conn, "notes_dir", "~nosuchuser_zz/notes")
        self.assertIsNone(notes_dir(self.conn))
