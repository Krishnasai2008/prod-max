import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from pm.tags import TAG, suggest

IDLE_CAP = timedelta(minutes=30)
STALE = timedelta(hours=24)
MAX_DIFF = 100_000
BURST = 3
BURST_DAYS = 7


@dataclass
class Episode:
    id: int
    cmd: str
    cwd: str
    status: str
    opened: datetime
    closed: datetime | None
    fails: int
    lost_s: int | None
    diff: str | None
    tags: list[str]


@dataclass
class Run:
    start: datetime
    dur_s: float
    code: int


@dataclass
class BugSummary:
    fixed: int
    open: int
    abandoned: int
    lost_s: int
    tags: list[tuple[str, int]]
    untagged: int
    bursts: list[tuple[str, int]]


def _ts(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _episode(conn: sqlite3.Connection, row: sqlite3.Row) -> Episode:
    fails = conn.execute("SELECT count(*) FROM runs WHERE episode_id=? AND code!=0",
                         (row["id"],)).fetchone()[0]
    tags = [r["tag"] for r in conn.execute(
        "SELECT tag FROM episode_tags WHERE episode_id=? ORDER BY tag", (row["id"],))]
    return Episode(row["id"], row["cmd"], row["cwd"], row["status"], _dt(row["opened"]),
                   _dt(row["closed"]), fails, row["lost_s"], row["diff"], tags)


def _lost(starts: list[datetime]) -> int:
    return int(sum(min(b - a, IDLE_CAP).total_seconds() for a, b in zip(starts, starts[1:])))


def _cap(text: str) -> str:
    return text[:MAX_DIFF] + "\n… (diff cut)" if len(text) > MAX_DIFF else text


def _replace_tags(conn: sqlite3.Connection, episode_id: int, tags: list[str]) -> None:
    conn.execute("DELETE FROM episode_tags WHERE episode_id=?", (episode_id,))
    conn.executemany("INSERT INTO episode_tags(episode_id, tag) VALUES(?, ?)",
                     [(episode_id, tag) for tag in sorted(set(tags))])


def record_run(conn, cmd: str, cwd: str, start: datetime, dur_s: float, code: int,
               snap: str | None, task_id: int | None,
               differ: Callable[[str, str], str] | None = None) -> Episode | None:
    ep = conn.execute("SELECT * FROM episodes WHERE cmd=? AND cwd=? AND status='open'",
                      (cmd, cwd)).fetchone()
    if ep is not None:
        newest = conn.execute("SELECT start FROM runs WHERE episode_id=?"
                              " ORDER BY start DESC, id DESC LIMIT 1", (ep["id"],)).fetchone()
        if newest is not None and datetime.fromisoformat(newest["start"]) < start - STALE:
            runs = conn.execute("SELECT start, code FROM runs WHERE episode_id=?"
                                " ORDER BY start, id", (ep["id"],)).fetchall()
            _replace_tags(conn, ep["id"], suggest("", [r["code"] for r in runs if r["code"]]))
            conn.execute("UPDATE episodes SET status='abandoned', closed=?, lost_s=?, diff=NULL"
                         " WHERE id=?", (_ts(datetime.fromisoformat(runs[-1]["start"])),
                                         _lost([datetime.fromisoformat(r["start"]) for r in runs]),
                                         ep["id"]))
            ep = None

    run_id = conn.execute(
        "INSERT INTO runs(cmd, cwd, start, dur_s, code, task_id, snap) VALUES(?,?,?,?,?,?,?)",
        (cmd, cwd, _ts(start), dur_s, code, task_id, snap)).lastrowid

    if code != 0:
        if ep is None:
            ep_id = conn.execute("INSERT INTO episodes(cmd, cwd, opened) VALUES(?,?,?)",
                                 (cmd, cwd, _ts(start))).lastrowid
        else:
            ep_id = ep["id"]
        conn.execute("UPDATE runs SET episode_id=? WHERE id=?", (ep_id, run_id))
        conn.commit()
        return None

    if ep is None:
        conn.commit()
        return None

    conn.execute("UPDATE runs SET episode_id=? WHERE id=?", (ep["id"], run_id))
    runs = conn.execute("SELECT start, code, snap FROM runs WHERE episode_id=?"
                        " ORDER BY start, id", (ep["id"],)).fetchall()
    fails = [r for r in runs if r["code"] != 0]
    text = None
    last_fail = fails[-1]
    if differ is not None and last_fail["snap"] and snap:
        text = _cap(differ(last_fail["snap"], snap))
    conn.execute("UPDATE episodes SET status='fixed', closed=?, lost_s=?, diff=? WHERE id=?",
                 (_ts(start), _lost([datetime.fromisoformat(r["start"]) for r in runs]), text,
                  ep["id"]))
    _replace_tags(conn, ep["id"], suggest(text or "", [r["code"] for r in fails]))
    conn.commit()
    return get_episode(conn, ep["id"])


def get_episode(conn, episode_id: int) -> Episode:
    row = conn.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
    if row is None:
        raise LookupError(f"no bug #{episode_id}")
    return _episode(conn, row)


def episodes(conn, limit: int = 10, tag: str | None = None) -> list[Episode]:
    if tag is None:
        rows = conn.execute("SELECT * FROM episodes ORDER BY opened DESC, id DESC LIMIT ?",
                            (limit,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT e.* FROM episodes e JOIN episode_tags t ON t.episode_id=e.id"
            " WHERE t.tag=? ORDER BY e.opened DESC, e.id DESC LIMIT ?", (tag, limit)).fetchall()
    return [_episode(conn, row) for row in rows]


def runs(conn, episode_id: int) -> list[Run]:
    get_episode(conn, episode_id)
    rows = conn.execute("SELECT start, dur_s, code FROM runs WHERE episode_id=?"
                        " ORDER BY start, id", (episode_id,)).fetchall()
    return [Run(_dt(row["start"]), row["dur_s"], row["code"]) for row in rows]


def set_tags(conn, episode_id: int, tags: list[str]) -> list[str]:
    get_episode(conn, episode_id)
    for tag in tags:
        if tag == "none":
            raise ValueError("'none' isn't a tag; pm bug ID none clears the tags")
        if not TAG.fullmatch(tag):
            raise ValueError(f"bad tag {tag!r} (lowercase words with dashes)")
    _replace_tags(conn, episode_id, tags)
    conn.commit()
    return sorted(set(tags))


def summary(conn, today: date) -> BugSummary:
    counts = {r["status"]: r["n"] for r in conn.execute(
        "SELECT status, count(*) n FROM episodes GROUP BY status")}
    lost = conn.execute("SELECT coalesce(sum(lost_s), 0) FROM episodes WHERE status!='open'"
                        ).fetchone()[0]
    tags = [(r["tag"], r["n"]) for r in conn.execute(
        "SELECT tag, count(*) n FROM episode_tags GROUP BY tag ORDER BY n DESC, tag")]
    untagged = conn.execute(
        "SELECT count(*) FROM episodes e WHERE status='fixed' AND NOT EXISTS"
        " (SELECT 1 FROM episode_tags t WHERE t.episode_id=e.id)").fetchone()[0]
    lo = (today - timedelta(days=BURST_DAYS - 1)).isoformat()
    bursts = [(r["tag"], r["n"]) for r in conn.execute(
        "SELECT t.tag, count(*) n FROM episode_tags t JOIN episodes e ON e.id=t.episode_id"
        " WHERE date(e.opened) BETWEEN ? AND ? GROUP BY t.tag"
        " HAVING count(*) >= ? ORDER BY n DESC, t.tag", (lo, today.isoformat(), BURST))]
    return BugSummary(counts.get("fixed", 0), counts.get("open", 0), counts.get("abandoned", 0),
                      lost, tags, untagged, bursts)
