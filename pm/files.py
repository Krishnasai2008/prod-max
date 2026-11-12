"""Index watched folders into SQLite FTS5, tag files by course, and search them."""
import json
import os
import stat
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from pm.db import get_setting, set_setting
from pm.extract import IMAGE_SUFFIXES, text_of

SETTLE = timedelta(seconds=10)
PER_TICK = 20
SKIP_SUFFIXES = (".part", ".crdownload", ".tmp", ".download")
SKIP_DIRS = frozenset({"node_modules", "__pycache__", "venv", "site-packages"})  # never study material
HEAD = 3000
OPENABLE = frozenset({".pdf", *IMAGE_SUFFIXES,
                      ".docx", ".pptx", ".odt", ".odp", ".txt", ".md", ".tex", ".csv"})


@dataclass
class Scan:
    added: int
    updated: int
    removed: int
    pending: int  # changed files left for the next tick


@dataclass
class Hit:
    path: str
    course: str | None
    snippet: str
    id: int = 0


def roots(conn) -> list[Path]:
    value = get_setting(conn, "watch", "~/Downloads")
    return [Path(part).expanduser() for part in value.split(":") if part.strip()]


def ignored(conn) -> set[str]:
    """Folders under the watched roots to leave out (the watch_ignore setting, ':'-separated)."""
    value = get_setting(conn, "watch_ignore", "")
    return {str(Path(part.strip()).expanduser()) for part in value.split(":") if part.strip()}


def course_codes(conn) -> dict[str, str]:
    value = get_setting(conn, "course_codes", "")
    codes: dict[str, str] = {}
    for pair in value.split(";"):
        name, sep, code = pair.strip().partition("=")
        if sep and name.strip() and code.strip():
            codes[name.strip()] = code.strip()
    return codes


def _norm(text: str) -> str:
    return re.sub(r"[\s_-]+", "", text.lower())


def course_of(name: str, head: str, codes: dict[str, str], courses: list[str]) -> str | None:
    haystack = _norm(name + head[:HEAD])
    code_hits = sorted(course for course, code in codes.items()
                       if _norm(code) and _norm(code) in haystack)
    if code_hits:
        return code_hits[0]
    lowered = name.lower()
    name_hits = []
    for course in {c for c in (*courses, *codes) if c}:
        if re.search(r"(?<![a-z0-9])" + re.escape(course.lower()) + r"(?![a-z0-9])", lowered):
            name_hits.append(course)
    return sorted(name_hits)[0] if name_hits else None


def _courses(conn) -> list[str]:
    rows = conn.execute("SELECT course FROM tasks WHERE course IS NOT NULL AND course != ''"
                        " UNION SELECT course FROM topics WHERE course != ''")
    return sorted({row["course"] for row in rows})


def _fts_name(path: str) -> str:
    return Path(path).name.replace("_", " ").replace("-", " ").replace(".", " ")


def _folder(path: str, roots: list[str]) -> str | None:
    """The first folder under the most specific watched root: docs/ai-ml/x/y.md -> ai-ml."""
    root = max((r for r in roots if path.startswith(r + os.sep)), key=len, default=None)
    if root is None:
        return None
    parts = path[len(root) + 1:].split(os.sep)
    return parts[0] if len(parts) > 1 else None


def _signature(codes: dict[str, str], courses: list[str], roots: list[str]) -> str:
    return json.dumps([codes, courses, roots], sort_keys=True)


def _retag(conn, codes: dict[str, str], courses: list[str], roots: list[str]) -> None:
    rows = conn.execute("SELECT f.id, f.path, substr(files_fts.body, 1, ?) AS body"
                        " FROM files f JOIN files_fts ON files_fts.rowid = f.id", (HEAD,))
    for row in rows:
        course = (course_of(Path(row["path"]).name, row["body"] or "", codes, courses)
                  or _folder(row["path"], roots))
        conn.execute("UPDATE files SET course=? WHERE id=?", (course, row["id"]))


def scan(conn, now: datetime, extract=text_of, limit: int = PER_TICK) -> Scan:
    existing = {row["path"]: (row["id"], row["mtime"], row["size"])
                for row in conn.execute("SELECT id, path, mtime, size FROM files")}
    watched = [root for root in roots(conn) if not root.is_symlink() and root.is_dir()]
    cutoff = now - SETTLE
    seen: set[str] = set()
    skip = ignored(conn)
    changed: dict[str, os.stat_result] = {}
    unreadable: list[str] = []  # folders os.walk couldn't list: keep their entries
    for root in watched:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False,
                                                    onerror=lambda error: unreadable.append(str(error.filename))):
            dirnames[:] = [name for name in dirnames if not name.startswith(".") and name not in SKIP_DIRS
                           and os.path.join(dirpath, name) not in skip]
            for name in filenames:
                path = Path(dirpath) / name
                key = str(path)
                if name.startswith(".") or name.lower().endswith(SKIP_SUFFIXES):
                    seen.add(key)
                    continue
                if path.is_symlink():
                    continue
                seen.add(key)
                try:
                    st = path.stat()
                    fresh = datetime.fromtimestamp(st.st_mtime) > cutoff
                except (OSError, ValueError, OverflowError):  # gone, or a timestamp no calendar holds
                    continue
                if fresh or not stat.S_ISREG(st.st_mode):  # a pipe named notes.txt would block the read forever
                    continue
                if key not in existing or existing[key][1:] != (st.st_mtime, st.st_size):
                    changed[key] = st
    # text first, writes after: extracting a scan can take minutes, and a write lock held that long fails other pm commands
    work = [(key, st, extract(Path(key))) for key, st in sorted(changed.items())[:limit]]
    codes = course_codes(conn)
    courses = _courses(conn)
    root_strings = [str(root) for root in watched]
    signature = _signature(codes, courses, root_strings)
    retag = get_setting(conn, "course_sig", "") != signature
    if retag:
        _retag(conn, codes, courses, root_strings)
    stamp = now.isoformat(timespec="seconds")
    added = updated = 0
    for key, st, body in work:
        course = course_of(Path(key).name, body, codes, courses) or _folder(key, root_strings)
        if key in existing:
            file_id = existing[key][0]
            conn.execute("UPDATE files SET mtime=?, size=?, course=?, indexed=? WHERE id=?",
                         (st.st_mtime, st.st_size, course, stamp, file_id))
            conn.execute("DELETE FROM files_fts WHERE rowid=?", (file_id,))
            updated += 1
        else:
            cur = conn.execute("INSERT INTO files(path, mtime, size, course, indexed)"
                               " VALUES(?,?,?,?,?)", (key, st.st_mtime, st.st_size, course, stamp))
            file_id = cur.lastrowid
            added += 1
        conn.execute("INSERT INTO files_fts(rowid, name, body) VALUES(?,?,?)",
                     (file_id, _fts_name(key), body))
    pending = len(changed) - min(len(changed), limit)
    removed = 0
    for key, (file_id, _, _) in existing.items():
        if key in seen or any(key.startswith(d + os.sep) for d in unreadable):
            continue
        if any(key == root or key.startswith(root + os.sep) for root in root_strings):
            conn.execute("DELETE FROM files_fts WHERE rowid=?", (file_id,))
            conn.execute("DELETE FROM files WHERE id=?", (file_id,))
            removed += 1
    conn.commit()
    if retag:
        set_setting(conn, "course_sig", signature)
    return Scan(added, updated, removed, pending)


def find(conn, query: str, course: str | None = None, limit: int = 10,
         marks: tuple[str, str] = ("[", "]")) -> list[Hit]:
    words = query.replace("\x00", " ").split()
    if not words:
        raise ValueError("give some words to search for")
    match = " ".join('"' + word.replace('"', '""') + '"' for word in words)
    sql = ("SELECT f.id, f.path, f.course, files_fts.body AS body,"
           " snippet(files_fts, 1, ?, ?, '…', 12) AS snippet"
           " FROM files_fts JOIN files f ON f.id = files_fts.rowid"
           " WHERE files_fts MATCH ?")
    params: list = [marks[0], marks[1], match]
    if course is not None:
        sql += " AND f.course = ?"
        params.append(course)
    sql += " ORDER BY bm25(files_fts, 5.0, 1.0) LIMIT ?"
    params.append(limit)
    return [Hit(row["path"], row["course"], row["snippet"] or Path(row["path"]).name,
                row["id"]) for row in conn.execute(sql, params)]


def recent(conn, limit: int = 20, course: str | None = None) -> list[Hit]:
    sql = "SELECT id, path, course FROM files"
    params: list = []
    if course is not None:
        sql += " WHERE course = ?"
        params.append(course)
    sql += " ORDER BY indexed DESC, id DESC LIMIT ?"
    params.append(limit)
    return [Hit(row["path"], row["course"], "", row["id"])
            for row in conn.execute(sql, params)]


def courses(conn) -> list[str]:
    rows = conn.execute("SELECT DISTINCT course FROM files"
                        " WHERE course IS NOT NULL AND course != '' ORDER BY course")
    return [row["course"] for row in rows]


def total(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]


def _file_path(conn, file_id: int) -> Path:
    row = conn.execute("SELECT path FROM files WHERE id=?", (file_id,)).fetchone()
    if row is None:
        raise LookupError(f"no file #{file_id}")
    path = Path(row["path"])
    try:
        gone = path.is_symlink() or not path.is_file()
    except (OSError, RuntimeError) as e:
        raise ValueError(str(e)) from None
    if gone:
        raise ValueError("that file is gone")
    return path


def launch(target: str) -> None:
    xdg = shutil.which("xdg-open")
    if xdg is None:
        raise ValueError("xdg-open is not installed")
    try:
        subprocess.Popen([xdg, target], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except (OSError, RuntimeError) as e:
        raise ValueError(f"couldn't start xdg-open: {e}") from None


def _launch(target: str, opener: Callable[[str], None] | None) -> None:
    if opener is not None:
        opener(target)
        return
    launch(target)


def open_file(conn, file_id: int, opener: Callable[[str], None] | None = None) -> str:
    path = _file_path(conn, file_id)
    try:
        real = path.resolve()
    except (OSError, RuntimeError) as e:
        raise ValueError(str(e)) from None
    suffix = real.suffix.lower()
    if suffix not in OPENABLE:
        if not suffix:
            raise ValueError("pm won't open a file with no extension; use show in folder")
        raise ValueError(f"pm won't open a {suffix} file; use show in folder")
    target = str(real)
    _launch(target, opener)
    return target


def reveal(conn, file_id: int, opener: Callable[[str], None] | None = None) -> str:
    path = _file_path(conn, file_id)
    try:
        target = str(path.resolve().parent)
    except (OSError, RuntimeError) as e:
        raise ValueError(str(e)) from None
    _launch(target, opener)
    return target
