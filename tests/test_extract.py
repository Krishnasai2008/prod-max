import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from pm.extract import MAX_TEXT, _run, text_of


def pdf_bytes(text: str, size: int = 24) -> bytes:
    stream = f"BT /F1 {size} Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref)
    return bytes(out)


class TestExtract(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.root = Path(self.d.name)

    def tearDown(self):
        self.d.cleanup()

    def write(self, name: str, data: bytes | str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data)
        return path

    def zip(self, name: str, entries: dict[str, str]) -> Path:
        path = self.root / name
        with zipfile.ZipFile(path, "w") as archive:
            for arcname, text in entries.items():
                archive.writestr(arcname, text)
        return path

    def test_text_file(self):
        self.assertIn("paging and TLB", text_of(self.write("notes.md", "paging and TLB\n")))

    def test_docx_reads_document_xml(self):
        path = self.zip("x.docx", {"word/document.xml":
                                   "<w:p><w:t>Paging &amp; TLB</w:t></w:p>"})
        self.assertIn("Paging & TLB", text_of(path))

    def test_pptx_slides_are_numeric_order(self):
        path = self.zip("x.pptx", {"ppt/slides/slide2.xml": "<a:t>two</a:t>",
                                   "ppt/slides/slide10.xml": "<a:t>ten</a:t>"})
        text = text_of(path)
        self.assertLess(text.index("two"), text.index("ten"))

    def test_unknown_suffix(self):
        self.assertEqual(text_of(self.write("x.zip", "not really a zip")), "")

    def test_corrupt_office_file(self):
        self.assertEqual(text_of(self.write("x.docx", "just bytes")), "")

    def test_missing_file(self):
        self.assertEqual(text_of(self.root / "gone.pdf"), "")

    def test_missing_pdf_command(self):
        path = self.write("x.pdf", "%PDF-1.4\n")
        with mock.patch("pm.extract.shutil.which", return_value=None) as which:
            self.assertEqual(text_of(path), "")
        which.assert_called()

    def test_pdf_timeout(self):
        path = self.write("x.pdf", "%PDF-1.4\n")
        with mock.patch("pm.extract.shutil.which", return_value="/usr/bin/pdftotext"), \
                mock.patch("pm.extract.subprocess.Popen",
                           side_effect=subprocess.TimeoutExpired("pdftotext", 60)):
            self.assertEqual(text_of(path), "")

    def test_tool_timeout_stops_reading(self):
        script = self.write("slow", f"#!{sys.executable}\nimport time\ntime.sleep(5)\n")
        script.chmod(0o755)
        self.assertEqual(_run([str(script)], 0.1), "")

    def test_tool_output_is_capped_and_stopped(self):
        path = self.write("x.pdf", "%PDF-1.4\n")
        marker = self.root / "finished"
        script = self.write("noisy", f"""#!{sys.executable}
import sys
sys.stdout.write("x" * 500000)
sys.stdout.flush()
open({str(marker)!r}, "w").close()
""")
        script.chmod(0o755)
        with mock.patch("pm.extract.shutil.which", return_value=str(script)):
            text = text_of(path)
        self.assertEqual(len(text), MAX_TEXT)
        self.assertFalse(marker.exists())

    @unittest.skipUnless(shutil.which("pdftotext"), "pdftotext is not installed")
    def test_real_pdf(self):
        path = self.write("x.pdf", pdf_bytes("Hello TLB"))
        self.assertIn("Hello TLB", text_of(path))

    def test_scanned_pdf_falls_back_to_ocr(self):
        path = self.write("scan.pdf", pdf_bytes(""))
        with mock.patch("pm.extract._ocr_pdf", return_value="page one of the scan") as ocr:
            self.assertEqual(text_of(path), "page one of the scan")
        ocr.assert_called_once_with(path)

    @unittest.skipUnless(shutil.which("pdftotext"), "pdftotext is not installed")
    def test_pdf_with_text_is_not_ocrd(self):
        path = self.write("x.pdf", pdf_bytes(" ".join(["word"] * 25), size=8))
        with mock.patch("pm.extract._ocr_pdf") as ocr:
            self.assertIn("word", text_of(path))
        ocr.assert_not_called()

    @unittest.skipUnless(shutil.which("pdftoppm") and shutil.which("tesseract"), "needs pdftoppm and tesseract")
    def test_ocr_pdf_reads_the_rendered_page(self):
        from pm.extract import _ocr_pdf
        path = self.write("x.pdf", pdf_bytes("Hello TLB"))
        self.assertIn("TLB", _ocr_pdf(path))

    def test_text_is_capped(self):
        path = self.write("big.txt", "x" * (MAX_TEXT + 1))
        self.assertEqual(len(text_of(path)), MAX_TEXT)

    def test_office_xml_read_is_bounded(self):
        path = self.root / "bomb.docx"
        payload = "<w:t>" + "x" * (MAX_TEXT * 8) + "</w:t>"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", payload)
        reads = []
        original = zipfile.ZipExtFile.read

        def spy(member, size=-1):
            reads.append(size)
            return original(member, size)

        with mock.patch.object(zipfile.ZipExtFile, "read", spy):
            text = text_of(path)
        self.assertEqual(len(text), MAX_TEXT)
        self.assertTrue(reads)
        self.assertTrue(all(size >= 0 for size in reads))

    def test_symlink_is_not_followed(self):
        target = self.write("real.txt", "secret")
        link = self.root / "link.txt"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("symlinks are not supported here")
        self.assertEqual(text_of(link), "")


class TestExtractNeverRaises(unittest.TestCase):
    def test_encrypted_or_unsupported_zip_members_give_empty_text(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.docx"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("word/document.xml", "<w:t>hi</w:t>")
            for error in (RuntimeError("encrypted"), NotImplementedError("compression")):
                with mock.patch("zipfile.ZipFile.open", side_effect=error):
                    self.assertEqual(text_of(path), "")
