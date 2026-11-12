"""Mock tests: build one from the bank, linked generators or a paper; take it, mark it, read the result, retry.

The answer key and scores are only part of `view` once the test is finished. Evidence is written once,
when the last question is marked. A generated question whose generator changed version (or is gone) since
the test was built is void: it has no score and counts nowhere.
"""
import random
from dataclasses import dataclass
from datetime import datetime

from pm import evidence, generators, grade, practice, templates
from pm.bank import TRUST, get_paper, get_question, questions
from pm.study import readiness

MAX_ANSWER = 20_000
VOID = "this question came from an older generator and is left out of the score"


@dataclass
class Mock:
    id: int
    course: str
    title: str
    minutes: int
    paper_id: int | None
    predicted: float | None
    created: datetime
    started: datetime | None
    finished: datetime | None
    marked: datetime | None

    @property
    def status(self) -> str:
        if self.marked:
            return "marked"
        if self.finished:
            return "to mark"
        return "running" if self.started else "ready"


@dataclass
class MockItem:
    mock_id: int
    pos: int
    question_id: int | None
    gen: str | None
    seed: int | None
    variant: str | None
    topic_id: int | None
    marks: float
    answer: str | None
    confidence: float | None
    dont_know: bool
    seconds: int | None
    score: float | None


@dataclass
class Result:
    got: float
    total: float
    pct: float
    predicted: float | None
    over_min: int
    by_topic: list[tuple[int | None, float, float]]
    said: float | None
    unread: list[int]
    missed: list[int]


def _time(text):
    return datetime.fromisoformat(text) if text else None


def _mock(row) -> Mock:
    return Mock(row["id"], row["course"], row["title"], row["minutes"], row["paper_id"], row["predicted"],
                datetime.fromisoformat(row["created"]), _time(row["started"]), _time(row["finished"]),
                _time(row["marked"]))


def _item(row) -> MockItem:
    return MockItem(row["mock_id"], row["pos"], row["question_id"], row["gen"], row["seed"], row["variant"],
                    row["topic_id"], row["marks"], row["answer"], row["confidence"], bool(row["dont_know"]),
                    row["seconds"], row["score"])


@dataclass
class _Content:
    prompt: str
    kind: str
    expected: dict | None
    model: str | None
    steps: str
    trust: str
    page: bool
    label: str
    void: bool = False


def _content(conn, item: MockItem) -> _Content:
    """What a question shows and how it is marked, for a bank question and a generated one alike."""
    if item.question_id is not None:
        q = get_question(conn, item.question_id)
        page = bool(q.path and q.path.suffix.lower() == ".pdf" and q.locator and q.locator[:1] == "p"
                    and q.locator[1:].isdigit())
        return _Content(q.prompt, q.kind, q.expected, q.answer, "", q.trust, page,
                        q.prompt.strip().splitlines()[0][:80])
    gen_id, _, version = item.gen.rpartition("@")
    templates.sync(conn)
    try:
        g = generators.info(gen_id)
        if str(g.VERSION) != version:
            raise LookupError(gen_id)
        p = generators.make(gen_id, item.seed, item.variant)
    except (LookupError, ValueError):
        return _Content(VOID, "open", None, None, "", "verified", False, item.gen, void=True)
    return _Content(p.text, p.kind, p.expected, None, p.steps, "verified", False, f"{p.title}: {p.variant}")


def _blank(text: str | None) -> bool:
    return text is None or not text.strip()


def _default_minutes(total_marks: float) -> int:
    return max(5, round(1.5 * total_marks))


def get(conn, mock_id: int) -> Mock:
    row = conn.execute("SELECT * FROM mocks WHERE id=?", (mock_id,)).fetchone()
    if row is None:
        raise LookupError(f"no test #{mock_id}")
    return _mock(row)


def items(conn, mock_id: int) -> list[MockItem]:
    return [_item(r) for r in conn.execute("SELECT * FROM mock_items WHERE mock_id=? ORDER BY pos", (mock_id,))]


def mocks(conn) -> list[Mock]:
    return [_mock(r) for r in conn.execute("SELECT * FROM mocks ORDER BY id DESC")]


def in_progress(conn) -> int | None:
    row = conn.execute("SELECT id FROM mocks WHERE started IS NOT NULL AND finished IS NULL"
                       " ORDER BY id DESC LIMIT 1").fetchone()
    return row[0] if row else None


def _seats(n: int, weight: dict[int, float], have: dict[int, int]) -> dict[int, int]:
    """Seats per topic by exam weight; a short topic's spare seats go to the heaviest topics with more."""
    order = sorted(weight)
    total = sum(weight.values())
    exact = {t: n * weight[t] / total for t in order}
    seats = {t: int(exact[t]) for t in order}
    for t in sorted(order, key=lambda t: (-(exact[t] - seats[t]), t))[:n - sum(seats.values())]:
        seats[t] += 1
    spare = 0
    for t in order:
        if seats[t] > have[t]:
            spare += seats[t] - have[t]
            seats[t] = have[t]
    while spare:
        open_topics = [t for t in sorted(order, key=lambda t: (-weight[t], t)) if seats[t] < have[t]]
        if not open_topics:
            break
        for t in open_topics:
            if not spare:
                break
            seats[t] += 1
            spare -= 1
    return seats


def _last_seen(conn) -> dict[int, str]:
    rows = conn.execute("SELECT mi.question_id, max(m.finished) FROM mock_items mi JOIN mocks m ON m.id = mi.mock_id"
                        " WHERE m.finished IS NOT NULL AND mi.question_id IS NOT NULL GROUP BY mi.question_id")
    return {r[0]: r[1] for r in rows}


def _question_row(q) -> tuple:
    return (q.id, None, None, None, q.topic_id, q.marks)


def _generated_row(topic_id: int, gen: str, rng: random.Random, variant: str | None = None) -> tuple:
    p = generators.make(gen, rng.randrange(2**31), variant)
    return (None, f"{p.gen}@{p.version}", p.seed, p.variant, topic_id, p.marks)


def _sample(conn, course: str, n: int, rng: random.Random) -> list[tuple]:
    by_topic: dict[int, list] = {}
    seen = _last_seen(conn)
    families: set[int] = set()
    pool = sorted(questions(conn, course=course),
                  key=lambda q: (TRUST.index(q.trust), q.id in seen, seen.get(q.id, ""), rng.random()))
    for q in pool:  # best first, so a family is represented by its most trusted, least recently seen member
        family = q.parent_id or q.id
        if family not in families:
            families.add(family)
            by_topic.setdefault(q.topic_id, []).append(q)
    course_topics = {r[0] for r in conn.execute("SELECT id FROM topics WHERE course=?", (course,))}
    gens: dict[int, list[str]] = {}
    for topic_id, gen in practice.linked(conn):
        if topic_id in course_topics:
            gens.setdefault(topic_id, []).append(gen)
    taking = set(by_topic) | set(gens)
    if not taking:
        raise ValueError(f"no questions for {course} yet (pm q import, pm paper import, pm practice link)")
    weight = {r["id"]: r["weight"] for r in conn.execute(
        f"SELECT id, weight FROM topics WHERE id IN ({','.join('?' * len(taking))})", list(taking))}
    seats = _seats(n, weight, {t: n if t in gens else len(by_topic[t]) for t in taking})
    chosen = []
    for t in sorted(taking):
        bank = by_topic.get(t, [])
        made = seats.get(t, 0) if not bank else seats.get(t, 0) // 2 if t in gens else 0
        from_bank = min(seats.get(t, 0) - made, len(bank))
        made = seats.get(t, 0) - from_bank
        chosen.extend(_question_row(q) for q in bank[:from_bank])
        turns = sorted(gens.get(t, []))
        rng.shuffle(turns)
        chosen.extend(_generated_row(t, turns[k % len(turns)], rng) for k in range(made))
    rng.shuffle(chosen)
    return chosen


def _create(conn, course: str, title: str, chosen: list[tuple], minutes: int | None, paper_id: int | None,
            now: datetime) -> int:
    """chosen: (question_id, gen, seed, variant, topic_id, marks) per question, in order."""
    total = sum(row[5] for row in chosen)
    cur = conn.execute("INSERT INTO mocks(course, title, minutes, paper_id, predicted, created) VALUES(?,?,?,?,?,?)",
                       (course, title, minutes or _default_minutes(total), paper_id,
                        readiness(conn, course, now), now.isoformat(timespec="seconds")))
    mock_id = cur.lastrowid
    conn.executemany("INSERT INTO mock_items(mock_id, pos, question_id, gen, seed, variant, topic_id, marks)"
                     " VALUES(?,?,?,?,?,?,?,?)", [(mock_id, pos, *row) for pos, row in enumerate(chosen, 1)])
    conn.commit()
    return mock_id


def build(conn, course: str | None, now: datetime, rng: random.Random, *, n: int = 10,
          minutes: int | None = None, paper_id: int | None = None) -> int:
    if not 1 <= n <= 100:
        raise ValueError("a test has 1-100 questions")
    if minutes is not None and not 1 <= minutes <= 600:
        raise ValueError("a test lasts 1-600 minutes")
    if paper_id is not None:
        paper = get_paper(conn, paper_id)
        chosen = questions(conn, paper_id=paper_id)
        if not chosen:
            raise ValueError("that paper has no questions yet (pm paper import)")
        return _create(conn, paper.course, paper.title, [_question_row(q) for q in chosen],
                       minutes or paper.minutes, paper_id, now)
    if not course:
        raise ValueError("give a course or a paper")
    chosen = _sample(conn, course, n, rng)
    return _create(conn, course, f"{course} mock {now:%Y-%m-%d}", chosen, minutes, None, now)


def start(conn, mock_id: int, now: datetime) -> None:
    m = get(conn, mock_id)
    if m.finished:
        raise ValueError("that test is finished")
    if m.started is None:
        conn.execute("UPDATE mocks SET started=? WHERE id=?", (now.isoformat(timespec="seconds"), mock_id))
        conn.commit()


def _get_item(conn, mock_id: int, pos: int) -> MockItem:
    row = conn.execute("SELECT * FROM mock_items WHERE mock_id=? AND pos=?", (mock_id, pos)).fetchone()
    if row is None:
        raise LookupError(f"no question {pos} in test #{mock_id}")
    return _item(row)


def save(conn, mock_id: int, pos: int, *, answer: str | None = None, confidence: float | None = None,
         dont_know: bool = False, seconds: int | None = None) -> None:
    m = get(conn, mock_id)
    if m.started is None:
        raise ValueError("start the test first")
    if m.finished:
        raise ValueError("that test is finished")
    _get_item(conn, mock_id, pos)
    if answer is not None and len(answer) > MAX_ANSWER:
        raise ValueError("that answer is too long")
    if confidence is not None and not 0 <= confidence <= 1:
        raise ValueError("confidence must be 0-1")
    if seconds is not None and seconds < 0:
        raise ValueError("seconds can't be negative")
    changes: dict = {}
    if dont_know:
        changes.update(answer=None, dont_know=1)
    elif answer is not None:
        changes.update(answer=answer, dont_know=0)
    if confidence is not None:
        changes["confidence"] = confidence
    if seconds is not None:
        changes["seconds"] = seconds
    if changes:
        sets = ", ".join(f"{k}=?" for k in changes)
        conn.execute(f"UPDATE mock_items SET {sets} WHERE mock_id=? AND pos=?", (*changes.values(), mock_id, pos))
        conn.commit()


def _unscored(conn, mock_id: int) -> int:
    """Open bank answers still to mark; generated questions are scored at finish or void."""
    return conn.execute("SELECT count(*) FROM mock_items WHERE mock_id=? AND score IS NULL"
                        " AND question_id IS NOT NULL", (mock_id,)).fetchone()[0]


def _mark_test(conn, mock_id: int, now: datetime) -> None:
    """All scored: record the marking and one evidence row per question, in one commit."""
    m = get(conn, mock_id)
    conn.execute("UPDATE mocks SET marked=? WHERE id=?", (now.isoformat(timespec="seconds"), mock_id))
    for item in items(conn, mock_id):
        if item.score is None:
            continue  # void
        c = _content(conn, item)
        evidence.add(conn, source="test", ref=f"{mock_id}/{item.pos}", ts=m.finished, grader=(
            "self" if c.kind == "open" else "code"), topic_id=item.topic_id, score=item.score,
            confidence=item.confidence, dont_know=item.dont_know, seconds=item.seconds,
            facet="application", label=c.label, commit=False)


def finish(conn, mock_id: int, now: datetime) -> int:
    """Score what code can score; returns how many open answers wait for the user's marks."""
    m = get(conn, mock_id)
    if m.started is None:
        raise ValueError("start the test first")
    if m.finished:
        return _unscored(conn, mock_id)
    try:
        conn.execute("UPDATE mocks SET finished=? WHERE id=?", (now.isoformat(timespec="seconds"), mock_id))
        for item in items(conn, mock_id):
            q = _content(conn, item)
            if q.void:
                continue
            blank = item.dont_know or _blank(item.answer)
            if q.kind != "open":
                score = 0.0 if blank else float(grade.check(q.kind, q.expected, item.answer))
            elif blank:
                score = 0.0
            else:
                continue
            conn.execute("UPDATE mock_items SET score=? WHERE mock_id=? AND pos=?", (score, mock_id, item.pos))
        waiting = _unscored(conn, mock_id)
        if not waiting:
            _mark_test(conn, mock_id, now)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return waiting


def mark(conn, mock_id: int, pos: int, got: float, now: datetime) -> int:
    m = get(conn, mock_id)
    if m.finished is None:
        raise ValueError("finish the test first")
    if m.marked:
        raise ValueError("that test is already marked")
    item = _get_item(conn, mock_id, pos)
    if item.question_id is None or get_question(conn, item.question_id).kind != "open":
        raise ValueError("pm marks that question itself")
    if isinstance(got, bool) or not isinstance(got, (int, float)) or not 0 <= got <= item.marks:
        raise ValueError(f"marks must be between 0 and {item.marks:g}")
    try:
        conn.execute("UPDATE mock_items SET score=? WHERE mock_id=? AND pos=?", (got / item.marks, mock_id, pos))
        waiting = _unscored(conn, mock_id)
        if not waiting:
            _mark_test(conn, mock_id, now)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return waiting


def result(conn, mock_id: int) -> Result:
    m = get(conn, mock_id)
    if not m.marked:
        raise ValueError("that test isn't marked yet")
    rows = [i for i in items(conn, mock_id) if i.score is not None]  # a marked test's void items have none
    got = sum(i.score * i.marks for i in rows)
    total = sum(i.marks for i in rows)
    over = 0
    if m.started and m.finished:
        late = (m.finished - m.started).total_seconds() - m.minutes * 60
        over = int(late // 60) if late > 0 else 0
    topics: dict = {}
    for i in rows:
        g, t = topics.get(i.topic_id, (0.0, 0.0))
        topics[i.topic_id] = (g + i.score * i.marks, t + i.marks)
    by_topic = [(t, g, tot) for t, (g, tot) in sorted(topics.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))]
    said = [i.confidence for i in rows if i.confidence is not None]
    unread = []
    for i in rows:
        if i.dont_know or _blank(i.answer):
            continue
        q = _content(conn, i)
        if q.kind != "open" and not q.void and not grade.readable(q.kind, q.expected, i.answer):
            unread.append(i.pos)
    return Result(got, total, got / total if total else 0.0, m.predicted, over, by_topic,
                  sum(said) / len(said) if said else None, unread, [i.pos for i in rows if i.score < 0.5])


def _variant_of(conn, question_id: int) -> int:
    """A checked variant of the question, the one seen longest ago (never seen first); else the question."""
    row = conn.execute(
        "SELECT q.id FROM questions q WHERE q.parent_id=? AND q.trust='checked' AND q.retired IS NULL"
        " ORDER BY (SELECT max(coalesce(m.started, m.created)) FROM mock_items i JOIN mocks m ON m.id = i.mock_id"
        "           WHERE i.question_id = q.id) IS NOT NULL,"
        " (SELECT max(coalesce(m.started, m.created)) FROM mock_items i JOIN mocks m ON m.id = i.mock_id"
        "  WHERE i.question_id = q.id), q.id LIMIT 1", (question_id,)).fetchone()
    return row[0] if row else question_id


def retry(conn, mock_id: int, now: datetime, rng: random.Random) -> int:
    m = get(conn, mock_id)
    missed = result(conn, mock_id).missed
    if not missed:
        raise ValueError("nothing was missed in that test")
    old = {i.pos: i for i in items(conn, mock_id)}
    chosen = []
    for pos in missed:
        i = old[pos]
        if i.question_id is not None:
            chosen.append(_question_row(get_question(conn, _variant_of(conn, i.question_id))))
        else:
            chosen.append(_generated_row(i.topic_id, i.gen.rpartition("@")[0], rng, i.variant))
    return _create(conn, m.course, f"{m.title} (retry)", chosen, None, None, now)


def view(conn, mock_id: int, pos: int) -> dict:
    """One question as the screen may show it; the key and score only once the test is finished."""
    m = get(conn, mock_id)
    item = _get_item(conn, mock_id, pos)
    q = _content(conn, item)
    topic = conn.execute("SELECT name FROM topics WHERE id=?", (item.topic_id,)).fetchone() \
        if item.topic_id is not None else None
    out = {"pos": item.pos, "question_id": item.question_id, "marks": item.marks,
           "topic": topic[0] if topic else None, "prompt": q.prompt, "kind": q.kind, "page": q.page,
           "answer": item.answer, "confidence": item.confidence, "dont_know": item.dont_know, "trust": q.trust,
           "void": q.void}
    if q.kind == "choice":
        out["options"] = list(q.expected["options"])
    if m.finished and not q.void:
        typed = q.kind != "open"
        out["key"] = grade.show(q.kind, q.expected) if typed else q.model
        out["steps"] = q.steps
        out["score"] = item.score
        out["readable"] = (not typed or item.dont_know or _blank(item.answer)
                           or grade.readable(q.kind, q.expected, item.answer))
        out["auto"] = typed
    return out
