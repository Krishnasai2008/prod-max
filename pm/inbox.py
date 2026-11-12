"""Apply the phone inbox's entries, at most once each, and report what happened."""
import re
import sqlite3
from datetime import datetime

from pm.tasks import add_task, done as finish_task, get_task, log_time
from pm.units import MAX_DAYS, fmt_duration, parse_due, parse_duration

SKIPPED = "inbox: skipped an entry with a bad id"
BUSY = "inbox: the database is busy; the rest waits for the next check"
_ID = re.compile(r"[A-Za-z0-9_-]{1,40}")
_LIMIT = 100
_MESSAGE = 200  # an error goes back to the phone in every push; junk input must not grow it
UNPUSHED = "inbox_unpushed"  # setting: applied entries whose acknowledgement no push has carried yet


def _when(entry: dict, now: datetime) -> datetime:
    at = entry.get("at")
    if not isinstance(at, str):
        return now
    try:
        when = datetime.fromisoformat(at)
        if when.tzinfo is not None:
            when = when.astimezone().replace(tzinfo=None)
        # shortcut: the phone's local time is read as the laptop's, convert it if you travel across time zones
        return now if (now - when).days > MAX_DAYS else min(when, now)
    except (ValueError, OverflowError):
        return now


def _text(entry: dict, key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text")
    return value


def _task_id(entry: dict) -> int:
    value = entry.get("task")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("task must be a whole number")
    return value


def apply(conn, entries: list, now: datetime) -> list[str]:
    lines: list[str] = []
    if not isinstance(entries, list):
        return lines
    for entry in entries[:_LIMIT]:
        if not isinstance(entry, dict):
            lines.append(SKIPPED)
            continue
        ident = entry.get("id")
        if not isinstance(ident, str) or _ID.fullmatch(ident) is None:
            lines.append(SKIPPED)
            continue
        try:
            line = _apply_one(conn, entry, ident, now)
        except sqlite3.OperationalError:  # e.g. the database is locked: not this entry's fault, try again later
            if conn.in_transaction:
                conn.rollback()
            lines.append(BUSY)
            break
        if line:
            lines.append(line)
    return lines


def _owe_push(conn) -> None:  # no commit: it is saved together with the entry's own change
    conn.execute("INSERT INTO settings(key, value) VALUES(?, '1')"
                 " ON CONFLICT(key) DO UPDATE SET value='1'", (UNPUSHED,))


def _apply_one(conn, entry: dict, ident: str, now: datetime) -> str | None:
    applied = now.isoformat(timespec="seconds")
    if conn.in_transaction:
        conn.rollback()
    if conn.execute("SELECT 1 FROM inbox_applied WHERE id=?", (ident,)).fetchone():
        if conn.execute("SELECT 1 FROM (SELECT id FROM inbox_applied ORDER BY applied DESC, rowid DESC"
                        " LIMIT ?) WHERE id=?", (_LIMIT, ident)).fetchone():
            return None
        # the phone still holds it but its acknowledgement left the newest 100 the push carries: send it again
        conn.execute("UPDATE inbox_applied SET applied=? WHERE id=?", (applied, ident))
        _owe_push(conn)
        conn.commit()
        return f"inbox: acknowledged {ident} again"
    conn.execute("INSERT INTO inbox_applied(id, applied) VALUES(?, ?)", (ident, applied))
    _owe_push(conn)
    op = entry.get("op")
    label = op if isinstance(op, str) and re.fullmatch(r"[a-z-]{1,20}", op) else "entry"
    try:
        when = _when(entry, now)
        if op == "add":
            title = _text(entry, "title").strip()
            if not 1 <= len(title) <= 200:
                raise ValueError("title must be 1-200 characters")
            est = _text(entry, "est")
            due_text = entry.get("due")
            if due_text is not None and not isinstance(due_text, str):
                raise ValueError("due must be text")
            course = entry.get("course")
            if course is not None and not isinstance(course, str):
                raise ValueError("course must be text")
            course = course.strip() if course is not None else None
            if course and len(course) > 80:
                raise ValueError("course must be at most 80 characters")
            due = parse_due(due_text, when.date()) if due_text else None
            tid = add_task(conn, title, parse_duration(est), now=when, due=due,
                           course=course or None)
            return f"inbox: added #{tid} {title}"
        if op == "log":
            task_id = _task_id(entry)
            minutes = parse_duration(_text(entry, "duration"))
            task = get_task(conn, task_id, now)
            if task.done_at or task.dropped:
                raise ValueError(f"#{task_id} is already done")
            log_time(conn, task_id, minutes, when)
            return f"inbox: logged {fmt_duration(minutes)} on #{task_id}"
        if op == "done":
            task_id = _task_id(entry)
            task = get_task(conn, task_id, now)
            if task.done_at or task.dropped:
                raise ValueError(f"#{task_id} is already done")
            finish_task(conn, task_id, when)
            return f"inbox: done #{task_id}"
        raise ValueError(f"unknown op {op!r}")
    except sqlite3.OperationalError:
        raise
    except (LookupError, ValueError, OverflowError, TypeError, sqlite3.Error) as error:
        message = (str(error) or type(error).__name__)[:_MESSAGE]
        if conn.in_transaction:
            conn.rollback()
        conn.execute(
            "INSERT INTO inbox_applied(id, applied, error) VALUES(?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET applied=excluded.applied, error=excluded.error",
            (ident, applied, message),
        )
        _owe_push(conn)
        conn.commit()
        return f"inbox: {label} failed: {message}"


def done(conn, limit: int = _LIMIT) -> list[dict]:
    rows = conn.execute("SELECT id, error FROM inbox_applied ORDER BY applied DESC, rowid DESC LIMIT ?",
                        (limit,)).fetchall()
    return [{"id": row["id"]} if row["error"] is None
            else {"id": row["id"], "error": row["error"]} for row in rows]
