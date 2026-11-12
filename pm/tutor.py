"""What the LearnHarness tutor may know: plain data for a model to read, served only to the plugin.

Everything here reaches the model provider LearnHarness uses, so search stays inside the notes folder
and the files topics track, never the rest of the file index.
"""
import random
import re
from datetime import datetime
from pathlib import Path

from pm import bank, evidence, grade, practice
from pm.excerpt import kind_of
from pm.files import find
from pm.notes import notes_dir
from pm.study import facets, get_topic, mastery

_SPACE = re.compile(r"\s+")


def context(conn, topic_id: int, now: datetime) -> dict:
    topic = get_topic(conn, topic_id)
    f = facets(conn, topic.id, now)
    part = lambda rate: rate.value if rate is not None else None  # noqa: E731
    missed = [r for r in evidence.misses(conn, limit=1000) if r.topic_id == topic.id][:5]
    files = [r[0] for r in conn.execute("SELECT path FROM topic_files WHERE topic_id=? ORDER BY path", (topic.id,))
             if Path(r[0]).is_file()][:5]
    tried = {t: (n, right) for t, n, right in practice.summary(conn, now)}.get(topic.id, (0, 0))
    return {
        "topic": topic.name, "course": topic.course or None,
        "exam": topic.exam_date.isoformat() if topic.exam_date else None,
        "days": (topic.exam_date - now.date()).days if topic.exam_date else None,
        "mastery": f.mastery,
        "parts": {"memory": part(f.memory), "understanding": part(f.understanding),
                  "application": part(f.application)},
        "covered": f.covered, "total": f.total,
        "mistakes": [{"label": evidence.short_label(r.label), "confidence": r.confidence, "source": r.source}
                     for r in missed],
        "files": files,
        "prerequisites": [{"topic": get_topic(conn, p).name, "mastery": mastery(conn, p, now)}
                          for p in topic.prereqs],
        "practised": {"attempts": tried[0], "right": tried[1]},
    }


def _allowed(conn):
    root = notes_dir(conn)
    tracked = {r[0] for r in conn.execute("SELECT path FROM topic_files")}

    def ok(path: str) -> bool:
        if path in tracked:
            return True
        if root is None:
            return False
        try:
            return Path(path).resolve().is_relative_to(root)
        except (OSError, RuntimeError):
            return False
    return ok


def search(conn, query: str, course: str | None = None, limit: int = 8) -> list[dict]:
    try:
        hits = find(conn, query, course, 40)
    except ValueError:
        return []
    ok = _allowed(conn)
    return [{"path": h.path, "name": Path(h.path).name, "course": h.course or None,
             "snippet": _SPACE.sub(" ", h.snippet).strip()}
            for h in hits if ok(h.path)][:limit]


def _from(conn, q: bank.Question) -> str:
    if q.origin == "paper" and q.paper_id is not None:
        return bank.get_paper(conn, q.paper_id).title
    if q.origin == "note" and q.path is not None:
        return q.path.name
    return "your own question"


def _key(q: bank.Question) -> str | None:
    if q.answer:
        return q.answer
    return grade.show(q.kind, q.expected) if q.expected else None


def _page(q: bank.Question) -> str | None:
    if q.path is not None and q.locator is not None and kind_of(q.path, q.locator) == "pdf":
        return f"page {q.locator[1:]} of {q.path}"
    return None


def exam_questions(conn, topic_id: int, n: int = 5) -> list[dict]:
    get_topic(conn, topic_id)
    found = [q for q in bank.questions(conn, topic_id=topic_id)
             if q.origin in ("paper", "note", "manual") and q.trust == "source"]
    found.sort(key=lambda q: (q.origin != "paper", q.id))
    return [{"prompt": q.prompt, "answer": _key(q), "marks": q.marks, "from": _from(conn, q), "page": _page(q)}
            for q in found[:n]]


def problem(conn, topic_id: int, now: datetime, rng: random.Random) -> dict:
    """A problem whose key pm trusts. Serving it records nothing: the attempt comes in with the session."""
    topic = get_topic(conn, topic_id)
    if practice.linked(conn, topic.id):
        p = practice.next_problem(conn, now, rng, topic.id).problem
        return {"source": "generator", "title": p.title, "text": p.text, "key": grade.show(p.kind, p.expected),
                "steps": p.steps}
    seen = {r[0]: r[1] for r in conn.execute(
        "SELECT i.question_id, max(m.started) FROM mock_items i JOIN mocks m ON m.id = i.mock_id"
        " WHERE i.question_id IS NOT NULL GROUP BY i.question_id")}
    usable = [q for q in bank.questions(conn, topic_id=topic.id)
              if q.trust in ("verified", "source") and _key(q) and _page(q) is None]
    if not usable:
        raise LookupError(f"no verified problem for {topic.name} yet")
    q = min(usable, key=lambda q: (seen.get(q.id) is not None, seen.get(q.id) or "", q.id))
    return {"source": "bank", "title": _from(conn, q), "text": q.prompt, "key": _key(q), "steps": ""}
