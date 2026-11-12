import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pm.excerpt import (FULL, default_pick, excerpt, kind_of, outline, page_png, split_answer,
                        split_spec)

MD = "# Graphs\nintro\n## BFS\nqueue based\nlevel order\n\n## DFS\nstack\n# Trees\nroots\n"

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

PDF = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
    b" /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
    b"4 0 obj\n<< /Length 36 >>\nstream\nBT /F1 24 Tf 72 720 Td (Hello) Tj ET\n"
    b"endstream\nendobj\n"
    b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n"
    b"0000000115 00000 n \n0000000241 00000 n \n0000000327 00000 n \n"
    b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n397\n%%EOF\n"
)


class TestExcerpt(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(); p = Path(self.d.name)
        self.md = p / "algo.md"; self.md.write_text(MD)
        self.py = p / "bfs.py"; self.py.write_text("a\nb\nc\nd\n")

    def tearDown(self):
        self.d.cleanup()

    def test_markdown_section(self):
        self.assertEqual(excerpt(self.md, "BFS"), "## BFS\nqueue based\nlevel order")
        self.assertEqual(excerpt(self.md, "graphs"), "# Graphs\nintro\n## BFS\nqueue based\nlevel order\n\n## DFS\nstack")

    def test_missing_heading(self):
        with self.assertRaises(ValueError):
            excerpt(self.md, "Heaps")

    def test_line_range(self):
        self.assertEqual(excerpt(self.py, "L2-3"), "b\nc")
        self.assertEqual(excerpt(self.py, "L4"), "d")
        with self.assertRaises(ValueError):
            excerpt(self.py, "L3-9")

    def test_truncates(self):
        big = Path(self.d.name) / "big.txt"; big.write_text("\n".join(map(str, range(50))))
        out = excerpt(big, None).splitlines()
        self.assertEqual((len(out), out[-1]), (41, "… (10 more lines)"))

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            excerpt(Path(self.d.name) / "nope.md", None)

    def test_directory_is_not_a_file(self):
        with self.assertRaises(FileNotFoundError):
            excerpt(Path(self.d.name), None)

    def test_binary_file_is_refused(self):
        binary = Path(self.d.name) / "paper.docx"
        binary.write_bytes(b"PK\x03\x04\x00\x00junk")
        with self.assertRaisesRegex(
                ValueError, "paper.docx isn't a text file; study a PDF by page,"
                            " or a text or Markdown file"):
            excerpt(binary, None)

    def test_utf8_text_file_still_works(self):
        text = Path(self.d.name) / "u.txt"
        text.write_text("héllo\nwörld", encoding="utf-8")
        self.assertEqual(excerpt(text, None), "héllo\nwörld")
        self.assertEqual(outline(text), [])

    def test_pdf(self):
        pdf = Path(self.d.name) / "s.pdf"; pdf.write_bytes(b"%PDF-1.4")
        with mock.patch("pm.excerpt.shutil.which", return_value=None):
            self.assertEqual(excerpt(pdf, "p3"), f"(open {pdf} at page 3)")
        with self.assertRaises(ValueError):
            excerpt(pdf, None)

    def test_split_spec(self):
        self.assertEqual(split_spec("~/n.md#BFS"), ((Path.home() / "n.md").resolve(), "BFS"))
        self.assertEqual(split_spec("a.md"), (Path("a.md").resolve(), None))
        self.assertEqual(split_spec("a.md#"), (Path("a.md").resolve(), None))

    def test_split_spec_turns_an_unexpandable_home_into_a_value_error(self):
        with self.assertRaises(ValueError):
            split_spec("~nosuchuser_x/n.md#BFS")
        with self.assertRaises(ValueError):
            split_spec("~nosuchuser_x/n.md")


class TestOutline(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.p = Path(self.d.name)
        self.md = self.p / "notes.md"
        self.md.write_text(NOTES)

    def tearDown(self):
        self.d.cleanup()

    def test_markdown_sections(self):
        sections = outline(self.md)
        self.assertEqual([s.title for s in sections], ["Paging", "TLB", "Example", "Example", "Short"])
        self.assertEqual([s.level for s in sections], [1, 2, 2, 2, 2])
        self.assertEqual([s.leaf for s in sections], [False, True, True, True, True])
        self.assertEqual([s.lines for s in sections], [1, 3, 6, 3, 1])
        self.assertEqual([s.pdf for s in sections], [False] * 5)

    def test_repeated_heading_becomes_a_line_range(self):
        first, repeated = outline(self.md)[2:4]
        self.assertEqual(first.locator, "Example")
        self.assertRegex(repeated.locator, r"^L\d+-\d+$")
        text = excerpt(self.md, repeated.locator)
        self.assertIn("four", text)
        self.assertNotIn("one", text)

    def test_default_pick_takes_leaf_sections_with_three_lines(self):
        self.assertEqual([s.title for s in default_pick(outline(self.md))],
                         ["TLB", "Example", "Example"])

    def test_a_markdown_heading_called_p1_is_not_a_pdf_section(self):
        md = self.p / "page.md"
        md.write_text("# p1\n")
        sections = outline(md)
        self.assertEqual([(s.title, s.locator, s.pdf) for s in sections], [("p1", "p1", False)])
        self.assertEqual(default_pick(sections), [])

    def test_other_files_have_no_outline(self):
        txt = self.p / "a.txt"
        txt.write_text("# not markdown\n")
        self.assertEqual(outline(txt), [])

    def test_a_binary_file_is_refused_not_listed_as_whole(self):
        binary = self.p / "slides.pptx"
        binary.write_bytes(b"PK\x03\x04\x00\x00junk")
        with self.assertRaisesRegex(
                ValueError, "slides.pptx isn't a text file; study a PDF by page,"
                            " or a text or Markdown file"):
            outline(binary)

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            outline(self.p / "gone.md")

    def test_markdown_goes_through_the_size_cap(self):
        with mock.patch("pm.excerpt.MAX_BYTES", 2):
            with self.assertRaisesRegex(ValueError, "notes.md is too large"):
                outline(self.md)

    def test_pdf_pages(self):
        pdf = self.p / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(
                args, 0, stdout="Title: x\nPages:          3\n", stderr="")

        with mock.patch("pm.excerpt.shutil.which", return_value="/usr/bin/pdfinfo"), \
                mock.patch("pm.excerpt.subprocess.run", side_effect=fake_run):
            sections = outline(pdf)
        self.assertEqual([s.locator for s in sections], ["p1", "p2", "p3"])
        self.assertEqual([s.title for s in sections], ["page 1", "page 2", "page 3"])
        self.assertEqual([(s.level, s.lines, s.leaf, s.pdf) for s in sections],
                         [(1, 0, True, True)] * 3)
        args, kwargs = calls[0]
        self.assertEqual(args, ["pdfinfo", str(pdf)])
        self.assertEqual(kwargs, {"capture_output": True, "text": True,
                                  "errors": "replace", "timeout": 10})

    def test_pdf_is_capped_at_500_pages(self):
        pdf = self.p / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        run = subprocess.CompletedProcess([], 0, stdout="Pages: 600\n", stderr="")
        with mock.patch("pm.excerpt.shutil.which", return_value="/usr/bin/pdfinfo"), \
                mock.patch("pm.excerpt.subprocess.run", return_value=run):
            sections = outline(pdf)
        self.assertEqual(len(sections), 500)
        self.assertEqual(sections[-1].locator, "p500")

    def test_pdf_without_pdfinfo(self):
        pdf = self.p / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        with mock.patch("pm.excerpt.shutil.which", return_value=None):
            with self.assertRaisesRegex(ValueError, "pdfinfo"):
                outline(pdf)

    def test_pdf_errors(self):
        pdf = self.p / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        runs = [
            subprocess.CompletedProcess([], 1, stdout="Pages: 3\n"),
            subprocess.CompletedProcess([], 0, stdout="Title: x\n"),
        ]
        for run in runs:
            with self.subTest(run=run), \
                    mock.patch("pm.excerpt.shutil.which", return_value="/usr/bin/pdfinfo"), \
                    mock.patch("pm.excerpt.subprocess.run", return_value=run):
                with self.assertRaisesRegex(ValueError, "can't read a.pdf"):
                    outline(pdf)
        with mock.patch("pm.excerpt.shutil.which", return_value="/usr/bin/pdfinfo"), \
                mock.patch("pm.excerpt.subprocess.run",
                           side_effect=subprocess.TimeoutExpired("pdfinfo", 10)):
            with self.assertRaisesRegex(ValueError, "can't read a.pdf"):
                outline(pdf)


class TestSplitAnswer(unittest.TestCase):
    def test_heading_and_marker_are_stripped(self):
        self.assertEqual(
            split_answer("### Q3\nWhat is a TLB?\n\n**Answer.** A cache of page-table entries."),
            ("What is a TLB?", "**Answer.** A cache of page-table entries."),
        )

    def test_model_answer_and_solution(self):
        self.assertEqual(split_answer("Define x.\n\n**Model answer**: y"),
                         ("Define x.", "**Model answer**: y"))
        self.assertEqual(split_answer("Q\n\n**Solution**\nz"), ("Q", "**Solution**\nz"))

    def test_no_marker_or_no_question(self):
        self.assertIsNone(split_answer("no marker here"))
        self.assertIsNone(split_answer("**Answer** only"))

    def test_marker_inside_a_fence_is_ignored(self):
        self.assertEqual(
            split_answer("Q?\n\n```\n**Answer** no\n```\n\n**Answer** yes"),
            ("Q?\n\n```\n**Answer** no\n```", "**Answer** yes"),
        )
        self.assertEqual(
            split_answer("Q?\n\n~~~\n**Solution** no\n~~~\n\n**Solution** yes"),
            ("Q?\n\n~~~\n**Solution** no\n~~~", "**Solution** yes"),
        )

    def test_marker_in_an_indented_code_block_is_ignored(self):
        self.assertEqual(
            split_answer("Q?\n\n    **Answer** no\n\n**Answer** yes"),
            ("Q?\n\n    **Answer** no", "**Answer** yes"),
        )
        self.assertEqual(
            split_answer("Q?\n\n\t**Answer** no\n\n**Answer** yes"),
            ("Q?\n\n\t**Answer** no", "**Answer** yes"),
        )


class TestKindsAndPages(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.p = Path(self.d.name)

    def tearDown(self):
        self.d.cleanup()

    def test_full_is_the_app_cap(self):
        self.assertEqual(FULL, 400)

    def test_kind_of(self):
        self.assertEqual(kind_of(Path("a.pdf"), "p3"), "pdf")
        self.assertEqual(kind_of(Path("a.pdf"), "Intro"), "text")
        self.assertEqual(kind_of(Path("a.pdf"), None), "text")
        self.assertEqual(kind_of(Path("a.md"), "TLB"), "markdown")
        self.assertEqual(kind_of(Path("a.markdown"), None), "markdown")
        self.assertEqual(kind_of(Path("a.py"), "L1-5"), "text")

    def test_page_png_without_pdftoppm(self):
        with mock.patch("pm.excerpt.shutil.which", return_value=None):
            self.assertIsNone(page_png(Path("a.pdf"), 3))

    def test_page_png_missing_file(self):
        with mock.patch("pm.excerpt.shutil.which", return_value="/usr/bin/pdftoppm"):
            with self.assertRaises(FileNotFoundError):
                page_png(self.p / "gone.pdf", 1)

    def test_page_png_rejects_a_bad_page_before_running(self):
        pdf = self.p / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        with mock.patch("pm.excerpt.shutil.which", return_value="/usr/bin/pdftoppm"), \
                mock.patch("pm.excerpt.subprocess.run") as run:
            for page in (0, -1, "3", 1.5):
                with self.subTest(page=page), self.assertRaises(ValueError):
                    page_png(pdf, page)
        run.assert_not_called()

    def test_page_png_renders_the_page(self):
        pdf = self.p / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            Path(args[-1] + ".png").write_bytes(b"\x89PNG fake")
            return subprocess.CompletedProcess(args, 0)

        with mock.patch("pm.excerpt.shutil.which", return_value="/usr/bin/pdftoppm"), \
                mock.patch("pm.excerpt.subprocess.run", side_effect=fake_run):
            self.assertEqual(page_png(pdf, 3), b"\x89PNG fake")
        args, kwargs = calls[0]
        for part in ("-f", "3", "-l", "3", "-r", "110", "-png", "-singlefile", str(pdf)):
            self.assertIn(part, args)
        self.assertEqual(kwargs["timeout"], 20)
        self.assertTrue(kwargs["capture_output"])

    def test_page_png_without_output_or_on_a_non_zero_exit(self):
        pdf = self.p / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        for run in (subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 1)):
            with self.subTest(run=run), \
                    mock.patch("pm.excerpt.shutil.which", return_value="/usr/bin/pdftoppm"), \
                    mock.patch("pm.excerpt.subprocess.run", return_value=run):
                with self.assertRaisesRegex(ValueError, "no page 3 in a.pdf"):
                    page_png(pdf, 3)

    def test_page_png_timeout(self):
        pdf = self.p / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        with mock.patch("pm.excerpt.shutil.which", return_value="/usr/bin/pdftoppm"), \
                mock.patch("pm.excerpt.subprocess.run",
                           side_effect=subprocess.TimeoutExpired("pdftoppm", 20)):
            with self.assertRaisesRegex(ValueError, "no page 3 in a.pdf"):
                page_png(pdf, 3)

    @unittest.skipUnless(shutil.which("pdftoppm"), "pdftoppm is not installed")
    def test_page_png_real_pdf(self):
        pdf = self.p / "tiny.pdf"
        pdf.write_bytes(PDF)
        self.assertTrue(page_png(pdf, 1).startswith(b"\x89PNG"))

    def test_pdf_text_timeout(self):
        pdf = self.p / "s.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        with mock.patch("pm.excerpt.shutil.which", return_value="/usr/bin/pdftotext"), \
                mock.patch("pm.excerpt.subprocess.run",
                           side_effect=subprocess.TimeoutExpired("pdftotext", 20)):
            with self.assertRaisesRegex(ValueError, "can't read s.pdf"):
                excerpt(pdf, "p3")

    def test_pdftotext_replaces_undecodable_bytes(self):
        pdf = self.p / "s.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, stdout="page\ntext", stderr="")

        with mock.patch("pm.excerpt.shutil.which", return_value="/usr/bin/pdftotext"), \
                mock.patch("pm.excerpt.subprocess.run", side_effect=fake_run):
            self.assertEqual(excerpt(pdf, "p1"), "page\ntext")
        self.assertEqual(calls[0][1]["errors"], "replace")

    def test_too_large_text_file_is_not_read(self):
        md = self.p / "algo.md"
        md.write_text(MD)
        with mock.patch("pm.excerpt.MAX_BYTES", 2):
            for locator in (None, "L1", "Graphs"):
                with self.subTest(locator=locator), \
                        self.assertRaisesRegex(ValueError, "algo.md is too large"):
                    excerpt(md, locator)


class TestExcerptEdges(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.p = Path(self.d.name)
    def tearDown(self):
        self.d.cleanup()

    def test_hash_lines_in_code_fences_are_not_headings(self):
        md = self.p / "setup.md"
        md.write_text("## Setup\n```bash\n# install\npip x\n```\ndone\n## Next\nmore\n")
        self.assertEqual(excerpt(md, "Setup"), "## Setup\n```bash\n# install\npip x\n```\ndone")
        with self.assertRaises(ValueError):
            excerpt(md, "install")

    def test_pdf_with_non_page_locator_asks_for_page(self):
        pdf = self.p / "s.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        for loc in ("Intro", "L1-5"):
            with self.assertRaisesRegex(ValueError, "give a page"):
                excerpt(pdf, loc)
