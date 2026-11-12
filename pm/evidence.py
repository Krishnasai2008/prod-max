"""One record of graded answers: reviews and spot cards through the evidence_v view, outside sources here.

Reviews are never copied into `evidence`; later phases (tests, practice, LearnHarness) add rows with `add`.
"""
from dataclasses import dataclass
from datetime import datetime

SOURCES = ("test", "practice", "lh-quiz", "lh-practice")
GRADERS = ("code", "self", "llm")
FACETS = ("memory", "understanding", "application")
HALF_LIFE_DAYS = 30.0
FULL_STRENGTH = 5.0
MAX_LABEL = 200


@dataclass
class Row:
    source: str
    ref: str
    topic_id: int | None
    ts: datetime
    correct: bool | None
    score: float | None
    confidence: float | None
    dont_know: bool
    seconds: int | None
    grader: str
    facet: str | None
    label: str


@dataclass
class Rate:
    value: float
    strength: float
    n: int


def _row(r) -> Row:
    return Row(r["source"], r["ref"], r["topic_id"], datetime.fromisoformat(r["ts"]),
               None if r["correct"] is None else bool(r["correct"]), r["score"], r["confidence"],
               bool(r["dont_know"]), r["seconds"], r["grader"], r["facet"], r["label"] or "")


def add(conn, *, source: str, ref: str, ts: datetime, grader: str, topic_id: int | None = None,
        correct: bool | None = None, score: float | None = None, confidence: float | None = None,
        dont_know: bool = False, seconds: int | None = None, facet: str | None = None,
        label: str = "", commit: bool = True) -> bool:
    """Store one graded answer; the same (source, ref) twice is stored once (False the second time)."""
    if source not in SOURCES:
        raise ValueError(f"unknown evidence source {source!r}")
    if not ref:
        raise ValueError("evidence needs a ref")
    if grader not in GRADERS:
        raise ValueError("grader must be code, self or llm")
    if facet is not None and facet not in FACETS:
        raise ValueError("facet must be memory, understanding or application")
    if score is not None and not 0 <= score <= 1:
        raise ValueError("score must be 0-1")
    if confidence is not None and not 0 <= confidence <= 1:
        raise ValueError("confidence must be 0-1")
    if seconds is not None and seconds < 0:
        raise ValueError("seconds can't be negative")
    if topic_id is not None and conn.execute("SELECT 1 FROM topics WHERE id=?", (topic_id,)).fetchone() is None:
        raise LookupError(f"no topic #{topic_id}")
    cur = conn.execute(
        "INSERT OR IGNORE INTO evidence(topic_id, source, ref, ts, correct, score, confidence, dont_know,"
        " seconds, grader, facet, label) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (topic_id, source, ref, ts.isoformat(timespec="seconds"),
         None if correct is None else int(bool(correct)), score, confidence, int(bool(dont_know)),
         seconds, grader, facet, label[:MAX_LABEL]))
    if commit:
        conn.commit()
    return cur.rowcount == 1


def rows(conn, *, topic_id: int | None = None, facet: str | None = None,
         source: str | None = None) -> list[Row]:
    where, args = [], []
    for column, value in (("topic_id", topic_id), ("facet", facet), ("source", source)):
        if value is not None:
            where.append(f"{column} = ?")
            args.append(value)
    sql = "SELECT * FROM evidence_v" + (" WHERE " + " AND ".join(where) if where else "")
    return [_row(r) for r in conn.execute(sql + " ORDER BY ts, source, ref", args)]


def value(row: Row) -> float | None:
    if row.score is not None:
        return row.score
    if row.correct is not None:
        return 1.0 if row.correct else 0.0
    return 0.0 if row.dont_know else None


def rate(rows: list[Row], now: datetime) -> Rate | None:
    """Recency-weighted mean: a row loses half its weight every 30 days; a future row weighs 1."""
    total = weighted = 0.0
    n = 0
    for row in rows:
        v = value(row)
        if v is None:
            continue
        age = max(0.0, (now - row.ts).total_seconds() / 86400)
        w = 0.5 ** (age / HALF_LIFE_DAYS)
        total += w
        weighted += w * v
        n += 1
    if not n:
        return None
    return Rate(weighted / total, min(1.0, total / FULL_STRENGTH), n)


def short_label(label: str) -> str:
    """notes.md#TLB for /home/me/os/notes.md#TLB; a prompt (not a path) is left alone."""
    if not label.startswith(("/", "~")):
        return label
    path, sep, rest = label.partition("#")
    return path.rstrip("/").rsplit("/", 1)[-1] + sep + rest


def misses(conn, limit: int = 20, min_confidence: float = 0.7) -> list[Row]:
    """Confident mistakes: said at least min_confidence, scored under half; newest first."""
    found = [r for r in (_row(x) for x in conn.execute(
        "SELECT * FROM evidence_v WHERE confidence >= ? ORDER BY ts DESC, source, ref", (min_confidence,)))
        if (v := value(r)) is not None and v < 0.5]
    return found[:limit]
