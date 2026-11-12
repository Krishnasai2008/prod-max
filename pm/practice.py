"""Practice: generators linked to topics, the next problem, and checking an answer (by code, never a model)."""
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from pm import evidence, generators, grade, study, templates
from pm.generators import Problem

WINDOW_DAYS = 30


@dataclass
class Served:
    topic_id: int
    problem: Problem


@dataclass
class Verdict:
    correct: bool
    readable: bool
    key: str
    steps: str


def link(conn, topic_id: int, gen: str) -> None:
    templates.sync(conn)
    generators.info(gen)
    study.get_topic(conn, topic_id)
    conn.execute("INSERT OR IGNORE INTO topic_gens(topic_id, gen) VALUES(?, ?)", (topic_id, gen))
    conn.commit()


def unlink(conn, topic_id: int, gen: str) -> None:
    cur = conn.execute("DELETE FROM topic_gens WHERE topic_id=? AND gen=?", (topic_id, gen))
    conn.commit()
    if cur.rowcount == 0:
        raise LookupError(f"{gen} isn't linked to that topic")


def linked(conn, topic_id: int | None = None) -> list[tuple[int, str]]:
    """(topic_id, gen) pairs for generators registered now (a template whose file is gone drops out)."""
    templates.sync(conn)
    known = set(generators.ids())
    sql, args = "SELECT topic_id, gen FROM topic_gens", ()
    if topic_id is not None:
        sql, args = sql + " WHERE topic_id=?", (topic_id,)
    return [(r[0], r[1]) for r in conn.execute(sql + " ORDER BY topic_id, gen", args) if r[1] in known]


def _last_practised(conn, topic_id: int, gen: str) -> str:
    row = conn.execute("SELECT max(ts) FROM evidence_v WHERE source='practice' AND topic_id=?"
                       " AND substr(ref, 1, length(?) + 1) = ? || '@'", (topic_id, gen, gen)).fetchone()
    return row[0] or ""


def next_problem(conn, now: datetime, rng: random.Random, topic_id: int | None = None) -> Served:
    if topic_id is not None:
        topic = study.get_topic(conn, topic_id)
        gens = [g for _, g in linked(conn, topic_id)]
        if not gens:
            raise ValueError(f"{topic.name} has no generators linked (pm practice link)")
    else:
        pairs = linked(conn)
        if not pairs:
            raise ValueError("no generators are linked to a topic yet (pm practice link)")
        with_links = {t for t, _ in pairs}
        ranked = [p.topic.id for p in study.rank(conn, now) if p.topic.id in with_links]
        topic_id = ranked[0] if ranked else min(with_links)
        gens = [g for t, g in pairs if t == topic_id]
    last = {g: _last_practised(conn, topic_id, g) for g in gens}
    oldest = min(last.values())
    gen = rng.choice(sorted(g for g in gens if last[g] == oldest))
    return Served(topic_id, generators.make(gen, rng.randrange(2**31)))


def submit(conn, *, topic_id: int, gen: str, seed: int, variant: str, answer: str, confidence: float | None,
           dont_know: bool, seconds: int | None, now: datetime) -> Verdict:
    templates.sync(conn)
    try:
        p = generators.make(gen, seed, variant)
    except LookupError as e:
        raise ValueError(str(e)) from None
    study.get_topic(conn, topic_id)
    answer = answer if isinstance(answer, str) else ""
    correct = False if dont_know else grade.check(p.kind, p.expected, answer)
    readable = True if dont_know else grade.readable(p.kind, p.expected, answer)
    evidence.add(conn, source="practice", ref=f"{gen}@{p.version}/{seed}/{variant}/{now.isoformat(timespec='seconds')}",
                 ts=now, topic_id=topic_id, correct=correct, confidence=None if dont_know else confidence,
                 dont_know=dont_know, seconds=seconds, grader="code", facet="application",
                 label=f"{p.title}: {variant}")
    return Verdict(correct, readable, grade.show(p.kind, p.expected), p.steps)


def summary(conn, now: datetime) -> list[tuple[int, int, int]]:
    since = (now - timedelta(days=WINDOW_DAYS)).isoformat(timespec="seconds")
    rows = conn.execute("SELECT topic_id, count(*), sum(correct) FROM evidence_v WHERE source='practice'"
                        " AND topic_id IS NOT NULL AND ts >= ? GROUP BY topic_id ORDER BY topic_id", (since,))
    return [(r[0], r[1], r[2] or 0) for r in rows]
