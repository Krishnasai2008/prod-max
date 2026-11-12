"""Turn one file into plain text for the search index.  Never raises."""
import codecs
import html
import re
import selectors
import shutil
import subprocess
import tempfile
import time
import zipfile
import zlib
from pathlib import Path

MAX_TEXT = 200_000
MAX_BYTES = 50 * 2**20
MAX_XML = MAX_TEXT * 4
# shortcut: only the first 10 pages of a scan are OCR'd (~2-5s each), raise it if long scans matter
OCR_PAGES = 10
MIN_CHARS = 100  # a PDF with less text than this (spaces aside) is treated as a scan

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"})
TEXT_SUFFIXES = frozenset({
    ".txt", ".md", ".tex", ".py", ".c", ".cc", ".cpp", ".h", ".hpp", ".java", ".js", ".ts",
    ".go", ".rs", ".csv", ".json", ".html", ".ipynb", ".sql", ".sh",
})
_SLIDE = re.compile(r"ppt/slides/slide(\d+)\.xml")
_TAG = re.compile(r"<[^>]*>")


def _run(argv: list[str], timeout: int) -> str:
    exe = shutil.which(argv[0])
    if exe is None:
        return ""
    try:
        proc = subprocess.Popen([exe, *argv[1:]], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    parts: list[str] = []
    size = 0
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while size < MAX_TEXT:
                left = deadline - time.monotonic()
                if left <= 0 or not selector.select(left):
                    break
                chunk = proc.stdout.read1(8192)
                if not chunk:
                    break
                text = decoder.decode(chunk)
                parts.append(text)
                size += len(text)
        if size < MAX_TEXT and proc.poll() is None:
            proc.wait(timeout=max(0, deadline - time.monotonic()))
        return "".join(parts)[:MAX_TEXT]
    except subprocess.TimeoutExpired:
        return ""
    except (OSError, ValueError):
        return ""
    finally:
        try:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
        except (OSError, subprocess.SubprocessError):
            pass
        if proc.stdout is not None:
            proc.stdout.close()


def _ocr_pdf(path: Path) -> str:
    """Render the first OCR_PAGES pages and run tesseract on each (for scans with no text layer)."""
    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm is None or shutil.which("tesseract") is None:
        return ""
    with tempfile.TemporaryDirectory(prefix="pm-ocr-") as tmp:
        try:
            subprocess.run([pdftoppm, "-r", "150", "-gray", "-png", "-l", str(OCR_PAGES), str(path),
                            str(Path(tmp) / "p")], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=120)
        except (OSError, subprocess.SubprocessError):
            return ""
        # pdftoppm zero-pads page numbers, so name order is page order
        return "\n".join(_run(["tesseract", str(page), "-"], 60) for page in sorted(Path(tmp).glob("p*.png")))


def _xml(data: bytes) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", data.decode("utf-8", errors="replace"))).split())


def _member(archive: zipfile.ZipFile, name: str, limit: int) -> bytes:
    with archive.open(name) as member:
        return member.read(limit)


def _zip_text(path: Path, suffix: str) -> str:
    with zipfile.ZipFile(path) as archive:
        if suffix == ".docx":
            return _xml(_member(archive, "word/document.xml", MAX_XML))
        if suffix in (".odt", ".odp"):
            return _xml(_member(archive, "content.xml", MAX_XML))
        slides = sorted((int(m.group(1)), name) for name in archive.namelist()
                        if (m := _SLIDE.fullmatch(name)))
        budget = MAX_XML
        parts: list[str] = []
        total = 0
        for _, name in slides:
            if budget <= 0 or total >= MAX_TEXT:
                break
            data = _member(archive, name, budget)
            budget -= len(data)
            text = _xml(data)
            parts.append(text)
            total += len(text) + 1
        return " ".join(parts)


def text_of(path: Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        if path.is_symlink() or path.stat().st_size > MAX_BYTES:
            return ""
        if suffix == ".pdf":
            text = _run(["pdftotext", "-layout", str(path), "-"], 60)
            if len("".join(text.split())) < MIN_CHARS:
                text = _ocr_pdf(path) or text
        elif suffix in IMAGE_SUFFIXES:
            text = _run(["tesseract", str(path), "-"], 120)
        elif suffix in (".docx", ".pptx", ".odt", ".odp"):
            text = _zip_text(path, suffix)
        elif suffix in TEXT_SUFFIXES:
            text = path.read_text(errors="replace")
        else:
            text = ""
    # zip members can be encrypted (RuntimeError), use an unsupported method or be corrupt
    except (OSError, KeyError, zipfile.BadZipFile, RuntimeError, NotImplementedError, zlib.error, EOFError):
        return ""
    return text[:MAX_TEXT]
