"""Files and pages a task reopens when you start it."""
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from pm import files
from pm.tasks import get_task

MAX_LINKS = 10
URL_PREFIXES = ("http://", "https://")


@dataclass
class Link:
    id: int
    task_id: int
    target: str
    kind: str


def _is_url(target: str) -> bool:
    return target.startswith(URL_PREFIXES)


def _resolve(target: str) -> Path | None:
    try:
        return Path(target).expanduser().resolve()
    except (OSError, RuntimeError):
        return None


def _kind(target: str) -> str:
    if _is_url(target):
        return "url"
    path = _resolve(target)
    if path is None:
        return "missing"
    try:
        if path.is_dir():
            return "folder"
        return "file" if path.exists() else "missing"
    except (OSError, RuntimeError):
        return "missing"


def _link(row) -> Link:
    return Link(row["id"], row["task_id"], row["target"], _kind(row["target"]))


def short(target: str) -> str:
    home = str(Path.home())
    return "~" + target[len(home):] if target == home or target.startswith(home + os.sep) else target


def add_link(conn, task_id: int, target: str, now: datetime) -> int:
    task = get_task(conn, task_id, now)
    if task.done_at or task.dropped:
        raise ValueError(f"#{task_id} is already done")
    target = target.strip()
    if not target:
        raise ValueError("give a full path or an http(s) address")
    if _is_url(target):
        if len(target) > 2000:
            raise ValueError("that address is too long")
        if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in target):
            raise ValueError("that address has spaces or control characters")
    else:
        try:
            path = Path(target).expanduser()
            absolute = path.is_absolute()
            exists = path.exists()
        except (OSError, RuntimeError):
            raise ValueError(f"no such file: {target}") from None
        if not absolute:
            raise ValueError("give a full path or an http(s) address")
        if not exists:
            raise ValueError(f"no such file: {path}")
        resolved = _resolve(str(path))
        if resolved is None:
            raise ValueError(f"no such file: {path}")
        target = str(resolved)
    count = conn.execute("SELECT COUNT(*) FROM task_links WHERE task_id=?",
                         (task_id,)).fetchone()[0]
    if count >= MAX_LINKS:
        raise ValueError(f"a task can have at most {MAX_LINKS} links")
    if conn.execute("SELECT 1 FROM task_links WHERE task_id=? AND target=?",
                    (task_id, target)).fetchone() is not None:
        raise ValueError("already linked")
    cur = conn.execute("INSERT INTO task_links(task_id, target) VALUES(?, ?)", (task_id, target))
    conn.commit()
    return cur.lastrowid


def links(conn, task_id: int) -> list[Link]:
    rows = conn.execute("SELECT * FROM task_links WHERE task_id=? ORDER BY id", (task_id,))
    return [_link(row) for row in rows]


def drop_link(conn, task_id: int, link_id: int) -> str:
    row = conn.execute("SELECT target FROM task_links WHERE id=? AND task_id=?",
                       (link_id, task_id)).fetchone()
    if row is None:
        raise LookupError("no such link")
    conn.execute("DELETE FROM task_links WHERE id=?", (link_id,))
    conn.commit()
    return row["target"]


def get_link(conn, task_id: int, link_id: int) -> Link:
    row = conn.execute("SELECT * FROM task_links WHERE id=? AND task_id=?",
                       (link_id, task_id)).fetchone()
    if row is None:
        raise LookupError("no such link")
    return _link(row)


def _open_target(link: Link) -> str | None:
    """What to hand the opener: the address, the folder, or a file safe to open."""
    if link.kind == "url":
        return link.target
    path = _resolve(link.target)
    if path is None:
        return None
    try:
        if path.is_dir():
            return str(path)
        if not path.exists():
            return None
    except (OSError, RuntimeError):
        return None
    return str(path) if path.suffix.lower() in files.OPENABLE else str(path.parent)


def open_links(conn, task_id: int,
               opener: Callable[[str], None] | None = None) -> tuple[int, list[str]]:
    opener = opener or files.launch
    opened, skipped = 0, []
    for link in links(conn, task_id):
        target = _open_target(link)
        if target is None:
            skipped.append(f"gone {short(link.target)}")
            continue
        try:
            opener(target)
        except ValueError as e:
            skipped.append(str(e))
            break
        opened += 1
    return opened, skipped


def open_link(conn, task_id: int, link_id: int,
              opener: Callable[[str], None] | None = None) -> tuple[int, list[str]]:
    """Open one link like open_links: re-resolved now, documents and images only, else the folder."""
    link = get_link(conn, task_id, link_id)
    target = _open_target(link)
    if target is None:
        return 0, [f"gone {short(link.target)}"]
    try:
        (opener or files.launch)(target)
    except ValueError as e:
        return 0, [str(e)]
    return 1, []
