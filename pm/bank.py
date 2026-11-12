"""The question bank: questions from notes, past papers and by hand, each with where it came from."""
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pm import grade
from pm.excerpt import FULL, excerpt, outline, split_answer

TRUST = ("verified", "source", "checked", "unverified")
ORIGINS = ("paper", "note", "manual", "lh", "variant")
KINDS = ("open",) + grade.KINDS
MAX_PROMPT = 20_000
_PAGE = re.compile(r"p(\d+)")


@dataclass
class Question:
    id: int
    topic_id: int | None
    origin: str
    ref: str
    prompt: str
    answer: str | None
    kind: str
    expected: dict | None
    marks: float
    trust: str
    path: Path | None
    locator: str | None
    paper_id: int | None
    parent_id: int | None
    created: datetime
    retired: str | None


@dataclass
class Paper:
    id: int
    course: str
    title: str
    path: Path | None
    minutes: int | None
    created: datetime


def _question(row) -> Question:
    return Question(row["id"], row["topic_id"], row["origin"], row["ref"], row["prompt"], row["answer"],
                    row["kind"], json.loads(row["expected"]) if row["expected"] else None, row["marks"],
                    row["trust"], Path(row["path"]) if row["path"] else None, row["locator"],
                    row["paper_id"], row["parent_id"], datetime.fromisoformat(row["created"]), row["retired"])


def _paper(row) -> Paper:
    return Paper(row["id"], row["course"], row["title"], Path(row["path"]) if row["path"] else None,
                 row["minutes"], datetime.fromisoformat(row["created"]))


def _topic_exists(conn, topic_id: int) -> None:
    if conn.execute("SELECT 1 FROM topics WHERE id=?", (topic_id,)).fetchone() is None:
        raise LookupError(f"no topic #{topic_id}")


def add_question(conn, *, origin: str, ref: str, prompt: str, now: datetime, trust: str,
                 topic_id: int | None = None, answer: str | None = None, kind: str = "open",
                 expected: dict | None = None, marks: float = 1, path: Path | None = None,
                 locator: str | None = None, paper_id: int | None = None, parent_id: int | None = None,
                 commit: bool = True) -> int:
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("a question needs text")
    if len(prompt) > MAX_PROMPT:
        raise ValueError("that question is too long")
    if isinstance(marks, bool) or not isinstance(marks, (int, float)) or not marks > 0 or marks == float("inf"):
        raise ValueError("marks must be positive")
    if origin not in ORIGINS:
        raise ValueError(f"unknown origin {origin!r}")
    if trust not in TRUST:
        raise ValueError(f"unknown trust level {trust!r}")
    if kind not in KINDS:
        raise ValueError(f"unknown answer kind {kind!r}")
    if kind == "open":
        if expected is not None:
            raise ValueError("an open question has no answer key")
        key = None
    else:
        if expected is None:
            raise ValueError(f"a {kind} question needs an answer key")
        key = json.dumps(grade.parse_expected(kind, expected))
    if origin == "paper" and paper_id is None:
        raise ValueError("a paper question needs its paper")
    if topic_id is not None:
        _topic_exists(conn, topic_id)
    try:
        cur = conn.execute(
            "INSERT INTO questions(topic_id, origin, ref, prompt, answer, kind, expected, marks, trust,"
            " path, locator, paper_id, parent_id, created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (topic_id, origin, ref, prompt, answer, kind, key, marks, trust,
             str(path) if path is not None else None, locator, paper_id, parent_id,
             now.isoformat(timespec="seconds")))
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e):
            raise ValueError("that question is already in the bank") from None
        raise ValueError(str(e)) from None
    if commit:
        conn.commit()
    return cur.lastrowid


def has(conn, origin: str, ref: str) -> bool:
    return conn.execute("SELECT 1 FROM questions WHERE origin=? AND ref=?", (origin, ref)).fetchone() is not None


def get_question(conn, question_id: int) -> Question:
    row = conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
    if row is None:
        raise LookupError(f"no question #{question_id}")
    return _question(row)


def questions(conn, *, course: str | None = None, topic_id: int | None = None, origin: str | None = None,
              paper_id: int | None = None, retired: bool = False) -> list[Question]:
    sql = "SELECT q.* FROM questions q LEFT JOIN topics t ON t.id = q.topic_id WHERE 1=1"
    args: list = []
    for clause, value in (("t.course = ?", course), ("q.topic_id = ?", topic_id),
                          ("q.origin = ?", origin), ("q.paper_id = ?", paper_id)):
        if value is not None:
            sql += f" AND {clause}"
            args.append(value)
    if not retired:
        sql += " AND q.retired IS NULL"
    return [_question(r) for r in conn.execute(sql + " ORDER BY q.id", args)]


def retire(conn, question_id: int, reason: str = "") -> None:
    get_question(conn, question_id)
    conn.execute("UPDATE questions SET retired=? WHERE id=?", (reason.strip() or "retired", question_id))
    conn.commit()


def restore(conn, question_id: int) -> None:
    get_question(conn, question_id)
    conn.execute("UPDATE questions SET retired=NULL WHERE id=?", (question_id,))
    conn.commit()


def counts(conn) -> list[tuple[int | None, str, int]]:
    rows = conn.execute("SELECT topic_id, trust, count(*) FROM questions WHERE retired IS NULL"
                        " GROUP BY topic_id, trust ORDER BY topic_id, trust")
    return [(r[0], r[1], r[2]) for r in rows]


def import_note(conn, path: Path, topic_id: int, now: datetime) -> tuple[int, int]:
    """Every leaf section with an **Answer** part becomes an open question; (added, skipped)."""
    if path.suffix.lower() not in (".md", ".markdown"):
        raise ValueError("question import needs a markdown file")
    _topic_exists(conn, topic_id)
    try:
        sections = outline(path)
    except OSError as e:
        raise ValueError(str(e)) from None
    added = skipped = 0
    for section in sections:
        if not section.leaf:
            continue
        try:
            split = split_answer(excerpt(path, section.locator, FULL))
        except (OSError, ValueError):
            continue
        if split is None:
            continue
        ref = f"{path}#{section.locator}"
        if conn.execute("SELECT 1 FROM questions WHERE origin='note' AND ref=?", (ref,)).fetchone():
            skipped += 1
            continue
        try:
            add_question(conn, origin="note", ref=ref, prompt=split[0], answer=split[1], now=now,
                         trust="source", topic_id=topic_id, path=path, locator=section.locator, commit=False)
        except ValueError:
            continue  # a section too long to be a question
        added += 1
    conn.commit()
    return added, skipped


def add_paper(conn, course: str, title: str, now: datetime, path: Path | None = None,
              minutes: int | None = None) -> int:
    course, title = (course or "").strip(), (title or "").strip()
    if not course or not title:
        raise ValueError("a paper needs a course and a title")
    if path is not None and not Path(path).is_file():
        raise ValueError(f"no such file: {path}")
    if minutes is not None and minutes < 1:
        raise ValueError("minutes must be positive")
    try:
        cur = conn.execute("INSERT INTO papers(course, title, path, minutes, created) VALUES(?,?,?,?,?)",
                           (course, title, str(path) if path is not None else None, minutes,
                            now.isoformat(timespec="seconds")))
    except sqlite3.IntegrityError:
        raise ValueError(f"{course} already has a paper called {title!r}") from None
    conn.commit()
    return cur.lastrowid


def get_paper(conn, paper_id: int) -> Paper:
    row = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
    if row is None:
        raise LookupError(f"no paper #{paper_id}")
    return _paper(row)


def papers(conn, course: str | None = None) -> list[Paper]:
    if course is None:
        rows = conn.execute("SELECT * FROM papers ORDER BY id")
    else:
        rows = conn.execute("SELECT * FROM papers WHERE course=? ORDER BY id", (course,))
    return [_paper(r) for r in rows]


def _answer_field(text: str) -> tuple[str, dict | None, str | None]:
    """'=12' / '=6.25~0.01' → a number key; other text → a model answer; '' → nothing."""
    if not text:
        return "open", None, None
    if not text.startswith("="):
        return "open", None, text
    value, _, tol = text[1:].partition("~")
    try:
        number = grade.number(value)
        tolerance = grade.number(tol) if tol else 0
    except ValueError:
        raise ValueError(f"couldn't read {text!r} as a number") from None
    if tolerance < 0:
        raise ValueError(f"couldn't read {text!r} as a number")
    try:
        return "number", {"value": float(number), "tol": float(tolerance)}, None
    except OverflowError:
        raise ValueError(f"{text!r} is too large a number") from None


def _paper_line(conn, paper, line: str, pages: list) -> tuple:
    """One import line → (label, marks, topic_id, locator, kind, key, model); ValueError when it's wrong."""
    fields = [f.strip() for f in line.split("|", 4)]
    if len(fields) < 3 or not fields[0]:
        raise ValueError("expected label | marks | topic")
    label, marks_text, topic_name = fields[:3]
    where = fields[3] if len(fields) > 3 else ""
    answer_text = fields[4] if len(fields) > 4 else ""
    try:
        marks = float(marks_text)
    except ValueError:
        marks = 0.0
    if not 0 < marks < float("inf"):
        raise ValueError("marks must be a positive number")
    row = conn.execute("SELECT id FROM topics WHERE course=? AND name=?", (paper.course, topic_name)).fetchone()
    if row is None:
        raise ValueError(f"no topic {topic_name!r} in {paper.course}")
    locator = None
    if where:
        if paper.path is None:
            raise ValueError('this paper has no PDF, so leave "where" empty')
        if not pages:
            try:
                pages.append(len(outline(paper.path)))
            except (OSError, ValueError):
                pages.append(0)
        page = _PAGE.fullmatch(where)
        if page is None or not 1 <= int(page[1]) <= pages[0]:
            raise ValueError(f"no page {where.lstrip('p')} in {paper.path.name}")
        locator = where
    kind, key, model = _answer_field(answer_text)
    return label, marks, row["id"], locator, kind, key, model


def _paper_lines(lines: list[str]):
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if line and not line.startswith("#"):
            yield number, line


def check_paper_lines(conn, paper_id: int, lines: list[str]) -> list[str]:
    """The errors import_paper would report for these lines, storing nothing."""
    paper = get_paper(conn, paper_id)
    pages: list = []
    errors = []
    for number, line in _paper_lines(lines):
        try:
            _paper_line(conn, paper, line, pages)
        except ValueError as e:
            errors.append(f"line {number}: {e}")
    return errors


def import_paper(conn, paper_id: int, lines: list[str], now: datetime) -> tuple[int, int, list[str]]:
    """label | marks | topic | where | answer per line; bad lines are reported, the rest imported."""
    paper = get_paper(conn, paper_id)
    pages: list = []
    added = skipped = 0
    errors: list[str] = []
    seen: set[str] = set()
    for number, line in _paper_lines(lines):
        try:
            label, marks, topic_id, locator, kind, key, model = _paper_line(conn, paper, line, pages)
            ref = f"{paper_id}/{label}"
            if ref in seen or conn.execute("SELECT 1 FROM questions WHERE origin='paper' AND ref=?",
                                           (ref,)).fetchone():
                skipped += 1
                seen.add(ref)
                continue
            seen.add(ref)
            add_question(conn, origin="paper", ref=ref, prompt=f"{paper.title} {label}", now=now,
                         trust="source", topic_id=topic_id, answer=model, kind=kind, expected=key,
                         marks=marks, path=paper.path, locator=locator, paper_id=paper_id, commit=False)
            added += 1
        except ValueError as e:
            errors.append(f"line {number}: {e}")
    conn.commit()
    return added, skipped, errors


@dataclass
class QStat:
    question_id: int
    attempts: int
    mean: float
    flags: list[str]


SUSPECT_CONFIDENCE = 0.8


def stats(conn) -> dict[int, QStat]:
    """Per bank question, over the scored items of marked tests."""
    rows = conn.execute(
        "SELECT i.question_id, i.score, i.confidence, q.trust FROM mock_items i JOIN mocks m ON m.id = i.mock_id"
        " JOIN questions q ON q.id = i.question_id WHERE m.marked IS NOT NULL AND i.score IS NOT NULL")
    seen: dict[int, list] = {}
    for r in rows:
        seen.setdefault(r["question_id"], []).append(r)
    out = {}
    for qid, tries in seen.items():
        mean = sum(t["score"] for t in tries) / len(tries)
        flags = []
        if tries[0]["trust"] in ("checked", "unverified") and any(
                (t["confidence"] or 0) >= SUSPECT_CONFIDENCE and t["score"] < 0.5 for t in tries):
            flags.append("suspect")
        if len(tries) >= 3 and mean >= 0.95:
            flags.append("too easy")
        if len(tries) >= 3 and mean <= 0.1:
            flags.append("too hard")
        out[qid] = QStat(qid, len(tries), mean, flags)
    return out


def to_check(conn) -> list[tuple[Question, QStat]]:
    flagged = [(get_question(conn, qid), s) for qid, s in stats(conn).items() if s.flags]
    found = [(q, s) for q, s in flagged if q.retired is None]
    return sorted(found, key=lambda pair: ("suspect" not in pair[1].flags, pair[0].id))
