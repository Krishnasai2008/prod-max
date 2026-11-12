"""Spot-the-error cards: a model changes one line of your note; you find it.

The model's text is untrusted. A card is stored only when exactly one line differs from the
original, and it grades from its stored copy, so editing the note later changes nothing.
"""
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from pm.excerpt import FULL, excerpt, kind_of
from pm.llm import fenced
from pm.study import get_item

PROMPT = """Below is an excerpt from a student's notes. Return the same excerpt with exactly ONE line changed so that the line states something false: a plausible mistake a student could make, such as a wrong number, a swapped term or a reversed condition.

Rules:
- Change one line only. Keep every other line exactly as it is.
- Keep the number of lines the same.
- Do not mark the change, and do not add comments or explanations.
- Output only the excerpt.

<excerpt>
{text}
</excerpt>"""

MIN_LINES, MAX_LINES, MAX_CHARS = 4, 60, 6000
HEADING = re.compile(r"#{1,6}\s")  # a Markdown heading states nothing, so it can't be the false line


@dataclass
class Spot:
    id: int
    item_id: int
    original: str
    mutated: str
    line: int
    created: datetime
    answered: datetime | None
    picked: int | None
    confidence: float | None


def _spot(row) -> Spot:
    return Spot(row["id"], row["item_id"], row["original"], row["mutated"], row["line"],
                datetime.fromisoformat(row["created"]),
                datetime.fromisoformat(row["answered"]) if row["answered"] else None,
                row["picked"], row["confidence"])


def _lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]


def eligible(text: str) -> bool:
    return MIN_LINES <= sum(1 for line in text.splitlines() if line.strip()) <= MAX_LINES \
        and len(text) <= MAX_CHARS


def check(original: str, mutated: str) -> int:
    """The 1-based number of the one line that differs; ValueError otherwise."""
    a, b = _lines(original), _lines(mutated)
    if len(a) != len(b):
        raise ValueError("the line count changed")
    changed = [i for i, (x, y) in enumerate(zip(a, b), 1) if x != y]
    if not changed:
        raise ValueError("no line changed")
    if len(changed) > 1:
        raise ValueError("more than one line changed")
    if not b[changed[0] - 1].strip():
        raise ValueError("the changed line is blank")
    if HEADING.match(a[changed[0] - 1]):
        raise ValueError("the changed line is a heading")
    return changed[0]


def make(conn, item_id: int, now: datetime, ask: Callable[[str], str], tries: int = 2) -> int:
    item = get_item(conn, item_id)
    if item.path.suffix.lower() == ".pdf" or kind_of(item.path, item.locator) == "pdf":
        raise ValueError("spot-the-error needs a text or markdown item")
    try:
        text = excerpt(item.path, item.locator, FULL)
    except OSError as e:
        raise ValueError(str(e)) from None
    if not eligible(text):
        raise ValueError("that excerpt is too short or too long for spot-the-error")
    original = "\n".join(_lines(text))
    problem = ""
    for _ in range(max(1, tries)):
        reply = fenced(ask(PROMPT.format(text=original)))  # a ValueError from ask stops at once
        try:
            line = check(original, reply)
        except ValueError as e:
            problem = str(e)
            continue
        mutated = "\n".join(_lines(reply))
        cur = conn.execute(
            "INSERT INTO spots(item_id, original, mutated, line, created) VALUES(?, ?, ?, ?, ?)",
            (item_id, original, mutated, line, now.isoformat(timespec="seconds")))
        conn.commit()
        return cur.lastrowid
    raise ValueError(f"the model didn't change exactly one line: {problem}")


def candidates(conn, limit: int, skip: frozenset[int] | set[int] = frozenset()) -> list[int]:
    """Text and markdown items you have recalled at least once, with no card waiting; never-spotted first."""
    rows = conn.execute(
        "SELECT i.id, i.path, i.locator, (SELECT max(created) FROM spots s WHERE s.item_id = i.id) AS last"
        " FROM items i WHERE i.suspended = 0"
        " AND EXISTS (SELECT 1 FROM reviews r WHERE r.item_id = i.id AND r.grade >= 3)"
        " AND NOT EXISTS (SELECT 1 FROM spots s WHERE s.item_id = i.id AND s.answered IS NULL)"
        " ORDER BY last IS NOT NULL, last, i.id").fetchall()
    out = []
    for row in rows:
        path = Path(row["path"])
        if row["id"] not in skip and path.suffix.lower() != ".pdf" and kind_of(path, row["locator"]) in ("markdown", "text"):
            out.append(row["id"])
        if len(out) >= limit:
            break
    return out


def pending(conn) -> list[Spot]:
    rows = conn.execute("SELECT * FROM spots WHERE answered IS NULL ORDER BY created, id")
    return [_spot(row) for row in rows]


def get(conn, spot_id: int) -> Spot:
    row = conn.execute("SELECT * FROM spots WHERE id=?", (spot_id,)).fetchone()
    if row is None:
        raise LookupError(f"no spot #{spot_id}")
    return _spot(row)


def answer(conn, spot_id: int, picked: int, confidence: float, now: datetime) -> bool:
    spot = get(conn, spot_id)
    count = len(spot.mutated.split("\n"))
    if isinstance(picked, bool) or not isinstance(picked, int) or not 1 <= picked <= count:
        raise ValueError(f"pick a line between 1 and {count}")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) \
            or not 0 <= confidence <= 1:
        raise ValueError("confidence must be 0-1")
    if spot.answered is not None:
        raise ValueError("that card is already answered")
    cur = conn.execute("UPDATE spots SET answered=?, picked=?, confidence=? WHERE id=? AND answered IS NULL",
                       (now.isoformat(timespec="seconds"), picked, float(confidence), spot_id))
    conn.commit()
    if cur.rowcount == 0:
        raise ValueError("that card is already answered")
    return picked == spot.line
