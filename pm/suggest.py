"""Model suggestions for how topics are organised. Nothing changes until the user accepts one."""
from dataclasses import dataclass
from datetime import datetime

from pm import agent, lh
from pm.study import add_prereq, get_topic, topics, would_loop

MAX_SESSIONS = 10
MAX_PAIRS = 20

SESSIONS = """Match each study session to the topic it belongs to. Reply with only a JSON object that maps each session id to a topic number from the list, or to null when no topic fits.

Topics:
{topics}

Sessions:
{sessions}"""

PREREQS = """These are the topics of one university course. List which topics need which others first: a pair [A, B] means a student should understand B before A. Only list direct, strong dependencies. Reply with only a JSON list of pairs, using the topic names exactly as written.

Topics:
{topics}"""


@dataclass
class Suggestion:
    id: int
    kind: str
    subject: str
    value: str
    created: datetime
    status: str
    text: str


def _where(t) -> str:
    return f"{t.course or '-'}/{t.name}"


def _fill(template: str, **values: str) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", value)
    return out


def _store(conn, kind: str, subject: str, value: str, now: datetime) -> bool:
    cur = conn.execute("INSERT OR IGNORE INTO suggestions(kind, subject, value, created) VALUES(?,?,?,?)",
                       (kind, subject, value, now.isoformat(timespec="seconds")))
    return cur.rowcount == 1


def session_topics(conn, now: datetime, ask) -> int:
    asked_about = {r[0] for r in conn.execute("SELECT subject FROM suggestions WHERE kind='topic'")}
    sessions = [s for s in lh.sessions(conn) if s.topic_id is None and s.error is None
                and s.chat_id not in asked_about][:MAX_SESSIONS]
    all_topics = topics(conn)
    if not sessions or not all_topics:
        return 0
    reply = ask(_fill(SESSIONS, topics="\n".join(f"{t.id}: {t.course or '-'} / {t.name}" for t in all_topics),
                      sessions="\n".join(f"{s.chat_id}: {s.title} — {s.kind}" for s in sessions)))
    data = agent.parse_json(reply, "{")
    if not isinstance(data, dict):
        raise ValueError("the model's reply wasn't the expected JSON")
    known = {s.chat_id for s in sessions}
    ids = {t.id for t in all_topics}
    stored = 0
    for chat_id, topic_id in data.items():
        if chat_id in known and isinstance(topic_id, int) and not isinstance(topic_id, bool) and topic_id in ids:
            stored += _store(conn, "topic", chat_id, str(topic_id), now)
            known.discard(chat_id)
    for chat_id in known:  # no topic fits: remember it was asked, so the hourly plan doesn't ask again
        conn.execute("INSERT OR IGNORE INTO suggestions(kind, subject, value, created, status) VALUES('topic',?,'',?,'rejected')",
                     (chat_id, now.isoformat(timespec="seconds")))
    conn.commit()
    return stored


def prereqs(conn, course: str, now: datetime, ask) -> int:
    course_topics = [t for t in topics(conn) if t.course == course]
    if len(course_topics) < 2:
        return 0
    reply = ask(_fill(PREREQS, topics="\n".join(t.name for t in course_topics)))
    data = agent.parse_json(reply)
    if not isinstance(data, list):
        raise ValueError("the model's reply wasn't the expected JSON")
    by_name = {t.name: t for t in course_topics}
    taken: list[tuple[int, int]] = []
    stored = 0
    for pair in data:
        if len(taken) >= MAX_PAIRS:
            break
        if not (isinstance(pair, list) and len(pair) == 2 and all(isinstance(x, str) for x in pair)):
            continue
        topic, needs = by_name.get(pair[0]), by_name.get(pair[1])
        if topic is None or needs is None or topic.id == needs.id or needs.id in topic.prereqs:
            continue
        if (topic.id, needs.id) in taken or would_loop(conn, topic.id, needs.id, tuple(taken)):
            continue
        taken.append((topic.id, needs.id))
        stored += _store(conn, "prereq", str(topic.id), str(needs.id), now)
    conn.commit()
    return stored


def _close(conn, suggestion_id: int, status: str) -> None:
    conn.execute("UPDATE suggestions SET status=? WHERE id=?", (status, suggestion_id))
    conn.commit()


def _topic_or_none(conn, topic_id: str):
    try:
        return get_topic(conn, int(topic_id))
    except (LookupError, ValueError):
        return None


def _text(conn, row) -> str | None:
    """The readable form, or None when the suggestion no longer applies."""
    if row["kind"] == "topic":
        session = conn.execute("SELECT title, topic_id FROM lh_sessions WHERE chat_id=?", (row["subject"],)).fetchone()
        topic = _topic_or_none(conn, row["value"])
        if session is None or topic is None or session["topic_id"] is not None:
            return None
        return f'put session "{session["title"]}" under {_where(topic)}'
    topic, needs = _topic_or_none(conn, row["subject"]), _topic_or_none(conn, row["value"])
    if topic is None or needs is None or needs.id in topic.prereqs:
        return None
    return f"{_where(topic)} needs {_where(needs)}"


def _suggestion(row, text: str) -> Suggestion:
    return Suggestion(row["id"], row["kind"], row["subject"], row["value"], datetime.fromisoformat(row["created"]),
                      row["status"], text)


def open_suggestions(conn) -> list[Suggestion]:
    found = []
    for row in conn.execute("SELECT * FROM suggestions WHERE status='open' ORDER BY id").fetchall():
        text = _text(conn, row)
        if text is None:
            _close(conn, row["id"], "rejected")
        else:
            found.append(_suggestion(row, text))
    return found


def _open(conn, suggestion_id: int):
    row = conn.execute("SELECT * FROM suggestions WHERE id=? AND status='open'", (suggestion_id,)).fetchone()
    if row is None:
        raise LookupError(f"no open suggestion #{suggestion_id}")
    return row


def accept(conn, suggestion_id: int) -> str:
    row = _open(conn, suggestion_id)
    text = _text(conn, row)
    try:
        if text is None:
            raise ValueError("its session or topic has changed")
        if row["kind"] == "topic":
            lh.map_session(conn, row["subject"], int(row["value"]))
        else:
            add_prereq(conn, int(row["subject"]), int(row["value"]))
    except (LookupError, ValueError) as e:
        _close(conn, suggestion_id, "rejected")
        raise ValueError(f"that suggestion no longer applies: {e}") from None
    _close(conn, suggestion_id, "accepted")
    return text


def reject(conn, suggestion_id: int) -> None:
    _open(conn, suggestion_id)
    _close(conn, suggestion_id, "rejected")


def _sort_job(conn, arg: str, now: datetime, ask) -> str:
    return f"{session_topics(conn, now, ask)} suggestions"


def _prereq_job(conn, arg: str, now: datetime, ask) -> str:
    return f"{prereqs(conn, arg, now, ask)} suggestions"


agent.HANDLERS["sort-sessions"] = _sort_job
agent.HANDLERS["prereqs"] = _prereq_job
