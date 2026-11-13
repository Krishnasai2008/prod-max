import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

LONG_SESSION_MIN = 360


@dataclass
class Task:
    id: int
    title: str
    course: str | None
    kind: str
    est_min: int
    due: date | None
    energy: str
    first_step: str | None
    done_at: datetime | None
    logged_min: int
    running: bool
    dropped: bool = False


def _ts(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _minutes(a: datetime, b: datetime) -> int:
    return max(0, int((b - a).total_seconds() // 60))  # a clock set back mid-session is no negative time


def _task(conn: sqlite3.Connection, row: sqlite3.Row, now: datetime) -> Task:
    logged, running = 0, False
    for s in conn.execute("SELECT start, end FROM sessions WHERE task_id=?", (row["id"],)):
        end = datetime.fromisoformat(s["end"]) if s["end"] else now
        running = running or s["end"] is None
        logged += _minutes(datetime.fromisoformat(s["start"]), end)
    return Task(
        row["id"], row["title"], row["course"], row["kind"], row["est_min"],
        date.fromisoformat(row["due"]) if row["due"] else None, row["energy"], row["first_step"],
        datetime.fromisoformat(row["done_at"]) if row["done_at"] else None, logged, running,
        bool(row["dropped"]),
    )


def add_task(conn, title: str, est_min: int, *, now: datetime, course: str | None = None,
             kind: str = "task", due: date | None = None, energy: str = "deep",
             first_step: str | None = None) -> int:
    if energy not in ("deep", "shallow"):
        raise ValueError("energy must be deep or shallow")
    title = title.strip()
    if not title:
        raise ValueError("title can't be empty")
    cur = conn.execute(
        "INSERT INTO tasks(title, course, kind, est_min, due, energy, first_step, created)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (title, course, kind, est_min, due.isoformat() if due else None, energy, first_step, _ts(now)),
    )
    conn.commit()
    return cur.lastrowid


def edit_task(conn, task_id: int, now: datetime, *, title: str | None = None,
              course: str | None = None, kind: str | None = None, due: date | None = None,
              energy: str | None = None, first_step: str | None = None, est_min: int | None = None,
              clear: tuple[str, ...] = ()) -> Task:
    task = get_task(conn, task_id, now)
    if task.done_at or task.dropped:
        raise ValueError(f"#{task_id} is already done")
    updates: dict[str, object] = {}
    if title is not None:
        title = title.strip()
        if not title:
            raise ValueError("title can't be empty")
        updates["title"] = title
    if energy is not None and energy not in ("deep", "shallow"):
        raise ValueError("energy must be deep or shallow")
    if est_min is not None and est_min <= 0:
        raise ValueError("estimate must be positive")
    if kind is not None and not kind.strip():
        raise ValueError("kind can't be empty")
    if est_min is not None and est_min != task.est_min:
        if task.logged_min > 0:
            raise ValueError("the estimate is locked once time is logged; pm learns from it")
        updates["est_min"] = est_min
    if course is not None:
        updates["course"] = course
    if kind is not None:
        updates["kind"] = kind
    if due is not None:
        updates["due"] = due.isoformat()
    if energy is not None:
        updates["energy"] = energy
    if first_step is not None:
        updates["first_step"] = first_step
    for name in clear:
        if name not in ("due", "course", "first_step"):
            raise ValueError(f"can't clear '{name}'")
        updates[name] = None
    if not updates:
        raise ValueError("nothing to change")
    conn.execute(f"UPDATE tasks SET {', '.join(f'{name}=?' for name in updates)} WHERE id=?",
                 (*updates.values(), task_id))
    conn.commit()
    return get_task(conn, task_id, now)


def get_task(conn, task_id: int, now: datetime) -> Task:
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if row is None:
        raise LookupError(f"no task #{task_id}")
    return _task(conn, row, now)


def _energy(energy) -> int:
    if isinstance(energy, bool) or not isinstance(energy, int) or not 1 <= energy <= 5:
        raise ValueError("energy must be 1-5")
    return energy


def stop(conn, now: datetime, note: str | None = None, minutes: int | None = None,
         energy: int | None = None) -> tuple[Task, int] | None:
    if energy is not None:
        _energy(energy)
    s = conn.execute("SELECT id, task_id, start FROM sessions WHERE end IS NULL").fetchone()
    if s is None:
        return None
    begun = datetime.fromisoformat(s["start"])
    if minutes is not None and minutes > _minutes(begun, now):
        raise ValueError(f"only {_minutes(begun, now)}m have passed since you started")
    end = begun + timedelta(minutes=minutes) if minutes is not None else now
    conn.execute("UPDATE sessions SET end=?, note=coalesce(?, note), energy=coalesce(?, energy) WHERE id=?",
                 (_ts(end), note, energy, s["id"]))
    conn.commit()
    return get_task(conn, s["task_id"], now), _minutes(begun, end)


RATE_WINDOW_MIN = 30


def _last_ended(conn):
    return conn.execute("SELECT id, end, energy FROM sessions WHERE end IS NOT NULL"
                        " ORDER BY end DESC, id DESC LIMIT 1").fetchone()


def unrated(conn, now: datetime) -> bool:
    """The session that ended last has no energy yet and ended at most 30 minutes ago."""
    row = _last_ended(conn)
    if row is None or row["energy"] is not None:
        return False
    return now - datetime.fromisoformat(row["end"]) <= timedelta(minutes=RATE_WINDOW_MIN)


def rate_session(conn, energy: int, now: datetime) -> None:
    _energy(energy)
    if not unrated(conn, now):
        raise ValueError("nothing to rate")
    conn.execute("UPDATE sessions SET energy=? WHERE id=?", (energy, _last_ended(conn)["id"]))
    conn.commit()


def start(conn, task_id: int, now: datetime) -> Task:
    try:
        conn.execute("BEGIN IMMEDIATE")  # the check is inside: another pm can't finish the task in between
        task = get_task(conn, task_id, now)
        if task.done_at or task.dropped:
            raise ValueError(f"#{task_id} is already done")
        conn.execute("UPDATE sessions SET end=? WHERE end IS NULL", (_ts(now),))
        conn.execute("INSERT INTO sessions(task_id, start) VALUES(?, ?)", (task_id, _ts(now)))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return get_task(conn, task_id, now)


def log_time(conn, task_id: int, minutes: int, now: datetime) -> None:
    task = get_task(conn, task_id, now)
    if task.done_at or task.dropped:
        raise ValueError(f"#{task_id} is already done")
    conn.execute("INSERT INTO sessions(task_id, start, end, logged) VALUES(?,?,?,1)",
                 (task_id, _ts(now - timedelta(minutes=minutes)), _ts(now)))
    conn.commit()


def done(conn, task_id: int, now: datetime) -> Task:
    task = get_task(conn, task_id, now)
    if task.done_at or task.dropped:
        raise ValueError(f"#{task_id} is already done")
    conn.execute("UPDATE sessions SET end=? WHERE task_id=? AND end IS NULL", (_ts(now), task_id))
    conn.execute("UPDATE tasks SET done_at=? WHERE id=?", (_ts(now), task_id))
    conn.commit()
    return get_task(conn, task_id, now)


def drop_task(conn, task_id: int, now: datetime) -> Task:
    task = get_task(conn, task_id, now)
    if task.done_at or task.dropped:
        raise ValueError(f"#{task_id} is already done")
    if running_task_id(conn) == task_id:
        stop(conn, now)
    conn.execute("UPDATE tasks SET done_at=?, dropped=1 WHERE id=?", (_ts(now), task_id))
    conn.commit()
    return get_task(conn, task_id, now)


def reopen(conn, task_id: int, now: datetime) -> Task:
    """Undo done or drop. The logged time was never touched, so nothing else needs restoring."""
    task = get_task(conn, task_id, now)
    if not (task.done_at or task.dropped):
        raise ValueError(f"#{task_id} is still open")
    conn.execute("UPDATE tasks SET done_at=NULL, dropped=0 WHERE id=?", (task_id,))
    conn.commit()
    return get_task(conn, task_id, now)


def closed_tasks(conn, limit: int = 20) -> list[Task]:
    """Finished and dropped tasks, the latest first."""
    rows = conn.execute("SELECT * FROM tasks WHERE done_at IS NOT NULL ORDER BY done_at DESC, id DESC LIMIT ?",
                        (limit,)).fetchall()
    return [_task(conn, r, datetime.min) for r in rows]


def open_tasks(conn, now: datetime) -> list[Task]:
    rows = conn.execute("SELECT * FROM tasks WHERE done_at IS NULL ORDER BY id").fetchall()
    return [_task(conn, r, now) for r in rows]


def running_task_id(conn) -> int | None:
    row = conn.execute("SELECT task_id FROM sessions WHERE end IS NULL").fetchone()
    return row["task_id"] if row else None


def running_session(conn) -> tuple[int, datetime] | None:
    row = conn.execute("SELECT task_id, start FROM sessions WHERE end IS NULL").fetchone()
    return (row["task_id"], datetime.fromisoformat(row["start"])) if row else None


def finished_tasks(conn) -> list[Task]:
    rows = conn.execute("SELECT * FROM tasks WHERE done_at IS NOT NULL AND dropped=0"
                        " ORDER BY done_at, id").fetchall()
    return [_task(conn, r, datetime.min) for r in rows]  # done tasks have no running session, so no clock is needed


def finished_ratios(conn) -> list[tuple[str, float]]:
    return [(t.kind, t.logged_min / t.est_min) for t in finished_tasks(conn) if t.logged_min > 0]


def last_note(conn, task_id: int) -> str | None:
    row = conn.execute("SELECT note FROM sessions WHERE task_id=? AND note IS NOT NULL"
                       " ORDER BY start DESC, id DESC LIMIT 1", (task_id,)).fetchone()
    return row["note"] if row else None


def worked_min(conn, day: date, now: datetime) -> int:
    start = f"{day.isoformat()}T00:00:00"
    end = f"{(day + timedelta(days=1)).isoformat()}T00:00:00"
    total = 0
    for s in conn.execute("SELECT start, end FROM sessions WHERE start >= ? AND start < ?",
                          (start, end)):
        begun = datetime.fromisoformat(s["start"])
        finished = datetime.fromisoformat(s["end"]) if s["end"] else now
        total += _minutes(begun, finished)
    return total


def worked_on(conn, task_id: int, day: date) -> bool:
    start = f"{day.isoformat()}T00:00:00"
    end = f"{(day + timedelta(days=1)).isoformat()}T00:00:00"
    row = conn.execute(
        "SELECT 1 FROM sessions WHERE task_id=? AND start < ?"
        " AND (end IS NULL OR end > ?) LIMIT 1", (task_id, end, start)).fetchone()
    return row is not None
