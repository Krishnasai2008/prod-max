import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pm.extract import MAX_BYTES

FULL = 400

_HEADING = re.compile(r"^(#+)\s+(.*?)\s*$")
_LINES = re.compile(r"^L(\d+)(?:-(\d+))?$")
_PAGE = re.compile(r"^p(\d+)$")
_ANSWER = re.compile(r"^\s*\*\*\s*(answer|solution|model answer)\b", re.IGNORECASE)


@dataclass
class Section:
    locator: str
    title: str
    level: int
    lines: int
    leaf: bool
    pdf: bool = False


def split_spec(spec: str) -> tuple[Path, str | None]:
    path, sep, locator = spec.rpartition("#")
    target = path if sep else spec
    try:
        resolved = Path(target).expanduser().resolve()
    except (OSError, RuntimeError) as e:
        raise ValueError(str(e)) from None
    return resolved, (locator or None) if sep else None


def kind_of(path: Path, locator: str | None) -> str:
    if path.suffix.lower() == ".pdf" and locator is not None and _PAGE.match(locator):
        return "pdf"
    if path.suffix.lower() in (".md", ".markdown"):
        return "markdown"
    return "text"


def outline(path: Path) -> list[Section]:
    if not path.is_file():
        raise FileNotFoundError(f"no such file: {path}")
    suffix = path.suffix.lower()
    if suffix in (".md", ".markdown"):
        lines = _read_text(path).splitlines()
        heads = list(_headings(lines))
        sections = []
        seen = set()
        for i, level, title in heads:
            end = next((j for j, lvl, _ in heads if j > i and lvl <= level), len(lines))
            next_head = next((j for j, _, _ in heads if j > i), len(lines))
            own = sum(1 for line in lines[i + 1:next_head] if line.strip())
            key = title.casefold()
            if key in seen:
                # shortcut: a repeated heading is stored as a line range, which goes stale
                # when the file is edited; store a heading path if that bites
                locator = f"L{i + 1}-{end}"
            else:
                locator = title
                seen.add(key)
            sections.append(Section(locator, title, level, own, next_head == end))
        return sections
    if suffix == ".pdf":
        if not shutil.which("pdfinfo"):
            raise ValueError("install poppler (pdfinfo) to list a PDF's pages")
        try:
            run = subprocess.run(
                ["pdfinfo", str(path)], capture_output=True, text=True, errors="replace",
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            raise ValueError(f"can't read {path.name}") from None
        page_count = re.search(r"^Pages:\s+(\d+)\s*$", run.stdout or "", re.MULTILINE)
        if run.returncode or page_count is None:
            raise ValueError(f"can't read {path.name}")
        return [
            Section(f"p{n}", f"page {n}", 1, 0, True, True)
            for n in range(1, min(int(page_count[1]), 500) + 1)
        ]
    _read_text(path)
    return []


def default_pick(sections: list[Section]) -> list[Section]:
    return [s for s in sections if s.pdf or (s.leaf and s.lines >= 3)]


def _strip_blank(lines: list[str]) -> list[str]:
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def split_answer(text: str) -> tuple[str, str] | None:
    lines = text.splitlines()
    fence = None
    for i, line in enumerate(lines):
        marker = line.lstrip()[:3]
        if marker in ("```", "~~~"):
            fence = None if fence == marker else fence or marker
            continue
        if fence is not None or line.startswith(("    ", "\t")):
            continue
        if _ANSWER.match(line):
            question_lines = _strip_blank(lines[:i])
            if question_lines and _HEADING.match(question_lines[0]):
                question_lines = _strip_blank(question_lines[1:])
            question = "\n".join(question_lines)
            if not question:
                return None
            return question, "\n".join(_strip_blank(lines[i:]))
    return None


def _cap(text: str, max_lines: int) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines] + [f"… ({len(lines) - max_lines} more lines)"])


def _headings(lines: list[str]):
    """(index, level, text) of markdown headings, skipping `#` lines inside ``` or ~~~ fences."""
    fence = None
    for i, line in enumerate(lines):
        marker = line.lstrip()[:3]
        if marker in ("```", "~~~"):
            fence = None if fence == marker else fence or marker
        elif fence is None and (match := _HEADING.match(line)):
            yield i, len(match[1]), match[2]


def _heading_excerpt(text: str, locator: str, path: Path) -> str:
    lines = text.splitlines()
    heads = list(_headings(lines))
    found = next(((i, lvl) for i, lvl, t in heads if t.casefold() == locator.casefold()), None)
    if found is None:
        raise ValueError(f"no heading {locator!r} in {path.name}")
    start, level = found
    end = next((i for i, lvl, _ in heads if i > start and lvl <= level), len(lines))
    return "\n".join(lines[start:end]).rstrip("\n")


def _pdf_page(path: Path, page: int) -> str:
    if not shutil.which("pdftotext"):
        return f"(open {path} at page {page})"
    try:
        out = subprocess.run(
            ["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(path), "-"],
            capture_output=True, text=True, errors="replace", timeout=20,
        ).stdout
    except subprocess.TimeoutExpired:
        raise ValueError(f"can't read {path.name}") from None
    if not out.strip():
        raise ValueError(f"no page {page} in {path.name}")
    return out


def page_png(path: Path, page: int, dpi: int = 110) -> bytes | None:
    if not isinstance(page, int) or page < 1:
        raise ValueError(f"no page {page} in {path.name}")
    if not shutil.which("pdftoppm"):
        return None
    if not path.is_file():
        raise FileNotFoundError(f"no such file: {path}")
    with tempfile.TemporaryDirectory() as tmp:
        prefix = Path(tmp) / "page"
        try:
            run = subprocess.run(
                ["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(dpi),
                 "-png", "-singlefile", str(path), str(prefix)],
                capture_output=True, timeout=20,
            )
        except subprocess.TimeoutExpired:
            raise ValueError(f"no page {page} in {path.name}") from None
        png = Path(f"{prefix}.png")
        if not png.is_file() or getattr(run, "returncode", 0):
            raise ValueError(f"no page {page} in {path.name}")
        return png.read_bytes()


def _read_text(path: Path) -> str:
    if path.stat().st_size > MAX_BYTES:
        raise ValueError(f"{path.name} is too large")
    with path.open("rb") as f:
        head = f.read(8192)
    if b"\x00" in head:
        raise ValueError(f"{path.name} isn't a text file; study a PDF by page,"
                         " or a text or Markdown file")
    return path.read_text(errors="replace")


def excerpt(path: Path, locator: str | None, max_lines: int = 40) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"no such file: {path}")
    is_pdf = path.suffix.lower() == ".pdf"
    if is_pdf and locator is not None and (page := _PAGE.match(locator)):
        return _cap(_pdf_page(path, int(page[1])), max_lines)
    if is_pdf:
        raise ValueError("give a page, like file.pdf#p3")
    if locator is None:
        return _cap(_read_text(path), max_lines)
    if lines := _LINES.match(locator):
        text = _read_text(path)
        all_lines = text.splitlines()
        first = int(lines[1])
        last = int(lines[2]) if lines[2] else first
        if first < 1 or last < first or last > len(all_lines):
            raise ValueError(f"line range {locator} is outside {path.name}")
        return _cap("\n".join(all_lines[first - 1:last]), max_lines)
    return _cap(_heading_excerpt(_read_text(path), locator, path), max_lines)
