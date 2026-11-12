import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import fsrs

from pm import evidence
from pm.db import get_setting
from pm.evidence import Rate
from pm.excerpt import default_pick, outline

SCHEDULER = fsrs.Scheduler(enable_fuzzing=False)
MASTERED = 0.6
WEIGHTS = {"memory": 1.0, "understanding": 1.0, "application": 2.0}


@dataclass
class Topic:
    id: int
    course: str
    name: str
    exam_date: date | None
    weight: float
    prereqs: list[int]


@dataclass
class Item:
    id: int
    topic_id: int
    path: Path
    locator: str | None
    prompt: str | None
    card: fsrs.Card
    suspended: bool = False


@dataclass
class Pick:
    topic: Topic
    mastery: float
    score: float


@dataclass
class Calibration:
    n: int
    brier: float
    bins: list[tuple[int, int, int, float, float]]


def utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc)


def _topic(conn: sqlite3.Connection, row: sqlite3.Row) -> Topic:
    prereqs = [
        r["prereq_id"]
        for r in conn.execute(
            "SELECT prereq_id FROM topic_prereqs WHERE topic_id=? ORDER BY prereq_id",
            (row["id"],),
        )
    ]
    return Topic(
        row["id"], row["course"], row["name"],
        date.fromisoformat(row["exam_date"]) if row["exam_date"] else None,
        float(row["weight"]), prereqs,
    )


def _item(conn: sqlite3.Connection, row: sqlite3.Row) -> Item:
    return Item(
        row["id"], row["topic_id"], Path(row["path"]), row["locator"], row["prompt"],
        fsrs.Card.from_json(row["card"]), bool(row["suspended"]),
    )


def add_topic(conn, name: str, *, course: str = "", exam_date: date | None = None,
              weight: float = 1.0, needs: list[str] = ()) -> int:
    name = name.strip()
    if not name:
        raise ValueError("topic name can't be blank")
    if not 0 < weight < float("inf"):
        raise ValueError("weight must be a positive finite number")
    prereq_ids = [find_topic(conn, n, course).id for n in needs]
    try:
        cur = conn.execute(
            "INSERT INTO topics(course, name, exam_date, weight) VALUES(?,?,?,?)",
            (course, name, exam_date.isoformat() if exam_date else None, weight),
        )
    except sqlite3.IntegrityError:
        raise ValueError(f"topic {name!r} already exists") from None
    topic_id = cur.lastrowid
    for prereq_id in prereq_ids:
        add_prereq(conn, topic_id, prereq_id)
    conn.commit()
    return topic_id


def find_topic(conn, name: str, course: str | None = None) -> Topic:
    sql = "SELECT * FROM topics WHERE name=?"
    args: list = [name]
    if course is not None:
        sql += " AND course=?"
        args.append(course)
    rows = conn.execute(sql, args).fetchall()
    if not rows:
        raise LookupError(f"no topic {name!r}")
    if len(rows) > 1:
        raise ValueError(f"{name!r} is in several courses; pass --course")
    return _topic(conn, rows[0])


def get_topic(conn, topic_id: int) -> Topic:
    row = conn.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
    if row is None:
        raise LookupError(f"no topic #{topic_id}")
    return _topic(conn, row)


def get_item(conn, item_id: int) -> Item:
    row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if row is None:
        raise LookupError(f"no item #{item_id}")
    return _item(conn, row)


def topics(conn) -> list[Topic]:
    return [_topic(conn, r) for r in conn.execute("SELECT * FROM topics ORDER BY id")]


def would_loop(conn, topic_id: int, prereq_id: int, extra: tuple[tuple[int, int], ...] = ()) -> bool:
    """Whether topic_id needing prereq_id makes a cycle; extra adds (topic, prereq) pairs not yet stored."""
    stack, seen = [prereq_id], set()
    while stack:
        current = stack.pop()
        if current == topic_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(r["prereq_id"] for r in conn.execute(
            "SELECT prereq_id FROM topic_prereqs WHERE topic_id=?", (current,)))
        stack.extend(p for t, p in extra if t == current)
    return False


def add_prereq(conn, topic_id: int, prereq_id: int) -> None:
    get_topic(conn, topic_id)
    get_topic(conn, prereq_id)
    if would_loop(conn, topic_id, prereq_id):
        raise ValueError("that would make a prerequisite loop")
    conn.execute(
        "INSERT OR IGNORE INTO topic_prereqs(topic_id, prereq_id) VALUES(?,?)",
        (topic_id, prereq_id),
    )
    conn.commit()


def add_item(conn, topic_id: int, path: Path, locator: str | None, *, now: datetime,
             prompt: str | None = None) -> int:
    get_topic(conn, topic_id)
    card = fsrs.Card(due=utc(now))
    cur = conn.execute(
        "INSERT INTO items(topic_id, path, locator, prompt, card, due, created)"
        " VALUES(?,?,?,?,?,?,?)",
        (topic_id, str(path), locator, prompt, card.to_json(), card.due.isoformat(),
         now.isoformat(timespec="seconds")),
    )
    conn.commit()
    track_file(conn, topic_id, path)
    return cur.lastrowid


def has_item(conn, topic_id: int, path: Path, locator: str | None, prompt: str | None) -> bool:
    return conn.execute("SELECT 1 FROM items WHERE topic_id=? AND path=? AND locator IS ? AND prompt IS ?",
                        (topic_id, str(path), locator, prompt)).fetchone() is not None


def existing_locators(conn, path: Path, topic_id: int | None = None) -> set[str | None]:
    """The file's locators already added: to one topic, or to any."""
    rows = conn.execute("SELECT locator FROM items WHERE path=? AND (? IS NULL OR topic_id=?)",
                        (str(path), topic_id, topic_id))
    return {row["locator"] for row in rows}


def locator_topics(conn, path: Path) -> dict[str | None, list[int]]:
    """Each of the file's added locators -> the topics that have it."""
    found: dict[str | None, list[int]] = {}
    for row in conn.execute("SELECT locator, topic_id FROM items WHERE path=? ORDER BY topic_id", (str(path),)):
        found.setdefault(row["locator"], []).append(row["topic_id"])
    return found


def add_items(conn, topic_id: int, path: Path, locators: list[str | None], *,
              now: datetime) -> tuple[int, int]:
    get_topic(conn, topic_id)
    existing = existing_locators(conn, path, topic_id)  # the same section may sit in two topics
    added = skipped = 0
    for locator in locators:
        if locator in existing:
            skipped += 1
            continue
        card = fsrs.Card(due=utc(now))  # one card per item, so each keeps its own card_id
        conn.execute(
            "INSERT INTO items(topic_id, path, locator, prompt, card, due, created)"
            " VALUES(?,?,?,?,?,?,?)",
            (topic_id, str(path), locator, None, card.to_json(), card.due.isoformat(),
             now.isoformat(timespec="seconds")),
        )
        existing.add(locator)
        added += 1
    conn.commit()
    track_file(conn, topic_id, path)
    return added, skipped


def _count_sections(path: Path) -> int | None:
    try:
        return len(default_pick(outline(path))) or None
    except (OSError, ValueError):
        return None


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def track_file(conn, topic_id: int, path: Path) -> int | None:
    """Count the file's sections for the topic's coverage; None when they can't be counted."""
    get_topic(conn, topic_id)
    path = Path(path)
    sections = _count_sections(path)
    conn.execute("INSERT OR IGNORE INTO topic_files(topic_id, path) VALUES(?, ?)", (topic_id, str(path)))
    conn.execute("UPDATE topic_files SET sections=?, mtime=? WHERE topic_id=? AND path=?",
                 (sections, _mtime(path), topic_id, str(path)))
    conn.commit()
    return sections


def untrack_file(conn, topic_id: int, path: Path) -> None:
    cur = conn.execute("DELETE FROM topic_files WHERE topic_id=? AND path=?", (topic_id, str(path)))
    if cur.rowcount == 0:
        raise LookupError(f"{get_topic(conn, topic_id).name} doesn't track that file")
    conn.commit()


def refresh_files(conn) -> int:
    """Recount files that changed or were never counted; a missing file keeps its old values."""
    changed = 0
    for row in conn.execute("SELECT topic_id, path, sections, mtime FROM topic_files").fetchall():
        path = Path(row["path"])
        mtime = _mtime(path)
        if mtime is None or (mtime == row["mtime"] and row["sections"] is not None):
            continue
        sections = _count_sections(path)
        if sections is None and row["sections"] is not None:
            continue  # unreadable now: keep the last good count
        if (sections, mtime) == (row["sections"], row["mtime"]):
            continue
        conn.execute("UPDATE topic_files SET sections=?, mtime=? WHERE topic_id=? AND path=?",
                     (sections, mtime, row["topic_id"], row["path"]))
        changed += 1
    conn.commit()
    return changed


def coverage(conn, topic_id: int) -> tuple[int, int]:
    """(covered, total) sections over the topic's tracked files."""
    covered = total = 0
    for row in conn.execute("SELECT path, sections FROM topic_files WHERE topic_id=?", (topic_id,)).fetchall():
        locators = {r[0] for r in conn.execute(
            "SELECT DISTINCT locator FROM items WHERE topic_id=? AND path=? AND suspended=0",
            (topic_id, row["path"]))}
        n, whole = len(locators), None in locators
        if row["sections"] is not None:
            total += row["sections"]
            covered += row["sections"] if whole else min(n, row["sections"])
        else:
            total += max(n, 1)
            covered += max(n, 1) if whole else n
    return covered, total


def new_cap(conn) -> int:
    try:
        value = int(get_setting(conn, "new_per_day", "10"))
    except ValueError:
        return 10
    return value if 1 <= value <= 200 else 10


def _started_today(conn, now: datetime) -> int:
    return conn.execute(
        "SELECT count(*) FROM (SELECT item_id, min(ts) AS first FROM reviews GROUP BY item_id)"
        " WHERE substr(first, 1, 10) = ?",
        (now.date().isoformat(),),
    ).fetchone()[0]


def _due_split(conn, now: datetime, new_cap: int) -> tuple[list[Item], list[Item], int]:
    rows = conn.execute(
        "SELECT i.*, EXISTS(SELECT 1 FROM reviews r WHERE r.item_id=i.id) AS seen"
        " FROM items i WHERE i.due <= ? AND i.suspended=0",
        (utc(now).isoformat(),),
    ).fetchall()
    seen = sorted((r for r in rows if r["seen"]), key=lambda r: (r["due"], r["id"]))
    new = sorted((r for r in rows if not r["seen"]), key=lambda r: r["id"])
    allowed = max(0, new_cap - _started_today(conn, now))
    return [_item(conn, r) for r in seen], [_item(conn, r) for r in new], allowed


def queue(conn, now: datetime, new_cap: int) -> list[Item]:
    seen, new, allowed = _due_split(conn, now, new_cap)
    return seen + new[:allowed]


def held(conn, now: datetime, new_cap: int) -> int:
    _, new, allowed = _due_split(conn, now, new_cap)
    return max(0, len(new) - allowed)


def suspend(conn, item_id: int, on: bool = True) -> None:
    if conn.execute("SELECT 1 FROM items WHERE id=?", (item_id,)).fetchone() is None:
        raise LookupError(f"no item #{item_id}")
    conn.execute("UPDATE items SET suspended=? WHERE id=?", (int(on), item_id))
    conn.commit()


def preview(conn, item_id: int, now: datetime) -> dict[int, datetime]:
    row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if row is None:
        raise LookupError(f"no item #{item_id}")
    out = {}
    for grade in (1, 2, 3, 4):
        card, _ = SCHEDULER.review_card(
            fsrs.Card.from_json(row["card"]), fsrs.Rating(grade), utc(now)
        )
        out[grade] = card.due.astimezone().replace(tzinfo=None)
    return out


def gap(cal: Calibration) -> float:
    if cal.n == 0:
        return 0.0
    said = sum(count * mean for _, _, count, mean, _ in cal.bins) / cal.n
    recalled = sum(count * rate for _, _, count, _, rate in cal.bins) / cal.n
    return said - recalled


def edit_topic(conn, topic_id: int, *, exam_date: date | None = None,
               weight: float | None = None, clear_exam: bool = False) -> Topic:
    get_topic(conn, topic_id)
    if weight is not None and not 0 < weight < float("inf"):
        raise ValueError("weight must be a positive finite number")
    sets, args = [], []
    if clear_exam:
        sets.append("exam_date=NULL")
    elif exam_date is not None:
        sets.append("exam_date=?")
        args.append(exam_date.isoformat())
    if weight is not None:
        sets.append("weight=?")
        args.append(weight)
    if not sets:
        raise ValueError("nothing to change")
    conn.execute(f"UPDATE topics SET {', '.join(sets)} WHERE id=?", (*args, topic_id))
    conn.commit()
    return get_topic(conn, topic_id)


def rename_topic(conn, topic_id: int, name: str) -> Topic:
    topic = get_topic(conn, topic_id)
    name = name.strip()
    if not name:
        raise ValueError("topic name can't be empty")
    try:
        conn.execute("UPDATE topics SET name=? WHERE id=?", (name, topic_id))
    except sqlite3.IntegrityError:
        raise ValueError(f"topic '{name}' already exists in {topic.course or 'no course'}") from None
    conn.commit()
    return get_topic(conn, topic_id)


def topic_items(conn, topic_id: int) -> list[Item]:
    get_topic(conn, topic_id)
    return [_item(conn, r) for r in conn.execute("SELECT * FROM items WHERE topic_id=? ORDER BY id", (topic_id,))]


def suspended_items(conn) -> list[Item]:
    return [_item(conn, r) for r in conn.execute("SELECT * FROM items WHERE suspended=1 ORDER BY id")]


def remove_item(conn, item_id: int) -> bool:
    """Delete an item nobody has answered yet; one with history is suspended instead (False), so its record stays."""
    get_item(conn, item_id)
    used = conn.execute("SELECT 1 FROM reviews WHERE item_id=? UNION ALL SELECT 1 FROM spots WHERE item_id=?",
                        (item_id, item_id)).fetchone()
    if used:
        suspend(conn, item_id, True)
        return False
    conn.execute("DELETE FROM items WHERE id=?", (item_id,))
    conn.commit()
    return True


def topic_counts(conn, now: datetime) -> dict[int, tuple[int, int]]:
    counts = {topic.id: (0, 0) for topic in topics(conn)}
    rows = conn.execute(
        "SELECT topic_id, count(*) AS n, sum(due <= ?) AS due FROM items"
        " WHERE suspended=0 GROUP BY topic_id",
        (utc(now).isoformat(),),
    ).fetchall()
    for row in rows:
        counts[row["topic_id"]] = (row["n"], row["due"] or 0)
    return counts


def record_review(conn, item_id: int, grade: int, confidence: float, now: datetime) -> datetime:
    if not 1 <= grade <= 4:
        raise ValueError(f"grade must be 1-4, got {grade}")
    if not 0 <= confidence <= 1:
        raise ValueError(f"confidence must be 0-1, got {confidence}")
    row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if row is None:
        raise LookupError(f"no item #{item_id}")
    card, _ = SCHEDULER.review_card(
        fsrs.Card.from_json(row["card"]), fsrs.Rating(grade), utc(now)
    )
    conn.execute(
        "UPDATE items SET card=?, due=? WHERE id=?",
        (card.to_json(), card.due.isoformat(), item_id),
    )
    conn.execute(
        "INSERT INTO reviews(item_id, ts, grade, confidence, recalled) VALUES(?,?,?,?,?)",
        (item_id, now.isoformat(timespec="seconds"), grade, confidence, int(grade >= 2)),
    )
    conn.commit()
    return card.due.astimezone().replace(tzinfo=None)


def memory_values(conn, topic_id: int, now: datetime) -> list[float]:
    rows = conn.execute(
        "SELECT card FROM items WHERE topic_id=? AND suspended=0", (topic_id,)
    ).fetchall()
    current = utc(now)
    values = [SCHEDULER.get_card_retrievability(fsrs.Card.from_json(r["card"]), current) for r in rows]
    cards = conn.execute("SELECT stability, last_review, due FROM lh_cards WHERE topic_id=? AND state IN (1,2,3)"
                         " AND stability > 0 AND last_review IS NOT NULL", (topic_id,))
    for c in cards:
        last = utc(datetime.fromisoformat(c["last_review"]))
        card = fsrs.Card(state=fsrs.State.Review, stability=c["stability"], difficulty=5.0, last_review=last,
                         due=utc(datetime.fromisoformat(c["due"])) if c["due"] else last)
        values.append(SCHEDULER.get_card_retrievability(card, current))
    return values


@dataclass
class Facets:
    memory: Rate | None
    understanding: Rate | None
    application: Rate | None
    covered: int
    total: int

    @property
    def coverage(self) -> float:
        return self.covered / self.total if self.total else 1.0

    @property
    def mastery(self) -> float:
        return self.coverage * blend({"memory": self.memory, "understanding": self.understanding,
                                      "application": self.application})


def facets(conn, topic_id: int, now: datetime) -> Facets:
    values = memory_values(conn, topic_id, now)
    memory = Rate(sum(values) / len(values), min(1.0, len(values) / evidence.FULL_STRENGTH),
                  len(values)) if values else None
    covered, total = coverage(conn, topic_id)
    return Facets(memory,
                  evidence.rate(evidence.rows(conn, topic_id=topic_id, facet="understanding"), now),
                  evidence.rate(evidence.rows(conn, topic_id=topic_id, facet="application"), now),
                  covered, total)


def blend(parts: dict[str, Rate | None]) -> float:
    """Weighted by kind and by how much evidence each part has; a missing part isn't a zero."""
    num = den = 0.0
    for name, part in parts.items():
        if part is not None:
            num += WEIGHTS[name] * part.strength * part.value
            den += WEIGHTS[name] * part.strength
    return num / den if den else 0.0


def mastery(conn, topic_id: int, now: datetime) -> float:
    return facets(conn, topic_id, now).mastery


def readiness(conn, course: str, now: datetime) -> float | None:
    today = now.date()
    upcoming = [t for t in topics(conn)
                if t.course == course and t.exam_date is not None and t.exam_date >= today]
    if not upcoming:
        return None
    return sum(t.weight * mastery(conn, t.id, now) for t in upcoming) / sum(t.weight for t in upcoming)


def ready_courses(conn, now: datetime) -> list[tuple[str, float, date, int]]:
    """(course, readiness, nearest exam, upcoming topics) per course with an exam ahead, nearest first."""
    today = now.date()
    upcoming: dict[str, list[Topic]] = {}
    for t in topics(conn):
        if t.exam_date is not None and t.exam_date >= today:
            upcoming.setdefault(t.course, []).append(t)
    found = [(course, readiness(conn, course, now), min(t.exam_date for t in ts), len(ts))
             for course, ts in upcoming.items()]
    return sorted(found, key=lambda r: (r[2], r[0]))


def rank(conn, now: datetime) -> list[Pick]:
    today = now.date()
    picks = []
    for topic in topics(conn):
        if topic.exam_date is None or topic.exam_date < today:
            continue
        m = mastery(conn, topic.id, now)
        days = max((topic.exam_date - today).days, 1)
        picks.append(Pick(topic, m, topic.weight * (1 - m) / days))
    picks.sort(key=lambda p: (-p.score, p.topic.id))
    return picks


def studyable(conn, topic_id: int) -> bool:
    """Whether the topic has anything to do: an item to review or a linked generator."""
    return conn.execute("SELECT 1 FROM items WHERE topic_id=? AND suspended=0 UNION ALL"
                        " SELECT 1 FROM topic_gens WHERE topic_id=?", (topic_id, topic_id)).fetchone() is not None


def next_topic(conn, now: datetime) -> tuple[Topic, Topic | None] | None:
    ranking = rank(conn, now)
    if not ranking:
        return None
    goal = ranking[0].topic
    current = goal
    while True:
        unmet = [
            get_topic(conn, prereq_id)
            for prereq_id in current.prereqs
            if mastery(conn, prereq_id, now) < MASTERED
        ]
        if not unmet:
            break
        current = min(unmet, key=lambda t: (mastery(conn, t.id, now), t.id))
    return current, (None if current.id == goal.id else goal)


def _calibrated(conn, since: datetime | None, source: str | None) -> list[tuple[float, float]]:
    """(confidence, outcome) of every answer that counts: a bet was made, not graded by a model."""
    found = []
    for row in evidence.rows(conn, source=source):
        if row.confidence is None or row.dont_know or row.grader == "llm":
            continue
        if since is not None and row.ts < since:
            continue
        if (outcome := evidence.value(row)) is not None:
            found.append((row.confidence, outcome))
    return found


def calibration(conn, since: datetime | None = None, source: str | None = None) -> Calibration:
    rows = _calibrated(conn, since, source)
    n = len(rows)
    if n == 0:
        return Calibration(0, 0.0, [])
    brier = sum((conf - outcome) ** 2 for conf, outcome in rows) / n
    groups: dict[int, list] = {}
    for conf, outcome in rows:
        groups.setdefault(min(int(conf * 5), 4), []).append((conf, outcome))
    bins = []
    for index in sorted(groups):
        group = groups[index]
        bins.append((
            index * 20, (index + 1) * 20, len(group),
            sum(c for c, _ in group) / len(group),
            sum(o for _, o in group) / len(group),
        ))
    return Calibration(n, brier, bins)


def calibration_sources(conn) -> list[tuple[str, Calibration]]:
    names = sorted({r[0] for r in conn.execute("SELECT DISTINCT source FROM evidence_v")})
    found = [(name, calibration(conn, source=name)) for name in names]
    return [(name, cal) for name, cal in found if cal.n]
