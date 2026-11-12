"""Background model work: a job queue under a daily call budget.

Every model call a job makes goes through `counted`, which charges the day's budget before the call.
Handlers take `ask` (a prompt → reply callable) so tests pass fakes. Model output is data: it is parsed
with `parse_json` and checked by code before anything is stored.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from pm import llm
from pm.db import get_setting, set_setting

CALLS = "agent_calls"  # internal: {"day": "2026-11-09", "n": 12}


class OutOfBudget(ValueError):
    pass


HANDLERS: dict[str, Callable] = {}


@dataclass
class Job:
    id: int
    kind: str
    arg: str
    status: str
    created: datetime
    finished: datetime | None
    calls: int
    result: str | None


def _job(row) -> Job:
    return Job(row["id"], row["kind"], row["arg"], row["status"], datetime.fromisoformat(row["created"]),
               datetime.fromisoformat(row["finished"]) if row["finished"] else None, row["calls"], row["result"])


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def enqueue(conn, kind: str, arg: str, now: datetime) -> int:
    if kind not in HANDLERS:
        raise ValueError(f"unknown job kind {kind!r}")
    row = conn.execute("SELECT id FROM jobs WHERE kind=? AND arg=? AND status='queued'", (kind, arg)).fetchone()
    if row:
        return row[0]
    job_id = conn.execute("INSERT INTO jobs(kind, arg, created) VALUES(?,?,?)", (kind, arg, _iso(now))).lastrowid
    conn.commit()
    return job_id


def jobs(conn, limit: int = 20) -> list[Job]:
    return [_job(r) for r in conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))]


def queued(conn) -> int:
    return conn.execute("SELECT count(*) FROM jobs WHERE status='queued'").fetchone()[0]


def budget(conn) -> int:
    try:
        return max(0, int(get_setting(conn, "agent_daily_calls", "0")))
    except ValueError:
        return 0


def spent(conn, now: datetime) -> int:
    try:
        data = json.loads(get_setting(conn, CALLS, "") or "{}")
        return int(data["n"]) if data.get("day") == now.date().isoformat() else 0
    except (ValueError, TypeError, KeyError, AttributeError):
        return 0


def budget_left(conn, now: datetime) -> int:
    return max(0, budget(conn) - spent(conn, now))


def counted(conn, now: datetime, ask) -> Callable[[str], str]:
    def call(prompt: str) -> str:
        if budget_left(conn, now) <= 0:
            raise OutOfBudget("out of budget for today")
        # charged before the call, so a crash can't make a call free
        set_setting(conn, CALLS, json.dumps({"day": now.date().isoformat(), "n": spent(conn, now) + 1}))
        call.calls += 1
        return ask(prompt)
    call.calls = 0
    return call


def run(conn, now: datetime, ask, limit: int | None = None) -> list[str]:
    lines: list[str] = []
    done = 0
    while budget_left(conn, now) > 0 and (limit is None or done < limit):
        row = conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if row is None:
            break
        job = _job(row)
        handler = HANDLERS.get(job.kind)
        call = counted(conn, now, ask)
        done += 1
        try:
            if handler is None:
                raise ValueError(f"unknown job kind {job.kind!r}")
            result = handler(conn, job.arg, now, call)
        except OutOfBudget:
            if conn.in_transaction:
                conn.commit()  # what the job finished stays
            _finish(conn, job, call.calls, "queued", None, None)
            lines.append(f"{job.kind} #{job.id}: paused, out of budget for today")
            break
        except (ValueError, LookupError) as e:
            if conn.in_transaction:
                conn.rollback()
            _finish(conn, job, call.calls, "failed", now, str(e))
            lines.append(f"{job.kind} #{job.id}: failed: {e}")
            continue
        _finish(conn, job, call.calls, "done", now, result)
        lines.append(f"{job.kind} #{job.id}: {result}")
    return lines


def _finish(conn, job: Job, calls: int, status: str, now: datetime | None, result: str | None) -> None:
    conn.execute("UPDATE jobs SET status=?, finished=?, calls=calls+?, result=? WHERE id=?",
                 (status, _iso(now) if now else None, calls, result, job.id))
    conn.commit()


def parse_json(text: str, opener: str = "[") -> object:
    closer = {"[": "]", "{": "}"}[opener]
    body = llm.fenced(text.strip()) if isinstance(text, str) else ""
    start, end = body.find(opener), body.rfind(closer)
    if start < 0 or end < start:
        raise ValueError("the model's reply wasn't the expected JSON")
    try:
        return json.loads(body[start:end + 1])
    except (ValueError, RecursionError):  # RecursionError: thousands of nested brackets
        raise ValueError("the model's reply wasn't the expected JSON") from None


def _ping(conn, arg: str, now: datetime, ask) -> str:
    return f"ping: {ask('Reply with the word ok.').strip()[:200]}"


HANDLERS["ping"] = _ping


# --- planning --------------------------------------------------------------------------------------

SPOT_STOCK = 5
SPOT_FAILED = "spot_failed"  # internal: item ids, as JSON
VARIANTS_PER_QUESTION = 3
VARY_PER_PLAN = 3
VARY_AGAIN_DAYS = 7


def spot_failed(conn) -> set[int]:
    """Items a background job couldn't make a card from; they aren't tried again (pm spot new still can)."""
    try:
        return {n for n in json.loads(get_setting(conn, SPOT_FAILED, "[]")) if isinstance(n, int)}
    except ValueError:
        return set()


def _spots(conn, arg: str, now: datetime, ask) -> str:
    from pm import spot
    failed = spot_failed(conn)
    down: list[ValueError] = []

    def asking(prompt: str) -> str:
        try:
            return ask(prompt)
        except OutOfBudget:
            raise
        except ValueError as e:
            down.append(e)
            raise

    made = 0
    try:
        for item_id in spot.candidates(conn, 3, failed):
            try:
                spot.make(conn, item_id, now, asking)
                made += 1
            except OutOfBudget:
                raise
            except (LookupError, ValueError):
                if down:
                    raise  # the model itself failed: stop here, the items are not to blame
                failed.add(item_id)  # this item didn't work out; the others still can
    finally:
        set_setting(conn, SPOT_FAILED, json.dumps(sorted(failed)[-500:]))
    return f"{made} {'card' if made == 1 else 'cards'}"


HANDLERS["spots"] = _spots


def is_queued(conn, kind: str, arg: str) -> bool:
    return conn.execute("SELECT 1 FROM jobs WHERE kind=? AND arg=? AND status='queued'", (kind, arg)).fetchone() is not None


def vary_candidates(conn, now: datetime, mock_id: int | None = None) -> list[int]:
    """Original questions missed in marked tests that can have more variants; most recently missed first."""
    from pm import bank
    from pm.excerpt import kind_of
    # shortcut: a question varied in the last week waits, so its dropped variants don't spend the budget every hour
    since = (now - timedelta(days=VARY_AGAIN_DAYS)).isoformat(timespec="seconds")
    sql = ("SELECT i.question_id, max(m.marked) AS missed FROM mock_items i JOIN mocks m ON m.id = i.mock_id"
           " WHERE m.marked IS NOT NULL AND i.question_id IS NOT NULL AND i.score < 0.5")
    args: list = []
    if mock_id is not None:
        sql += " AND m.id = ?"
        args.append(mock_id)
    rows = conn.execute(sql + " GROUP BY i.question_id ORDER BY missed DESC, i.question_id", args).fetchall()
    out = []
    for row in rows:
        q = bank.get_question(conn, row["question_id"])
        if q.retired or q.parent_id is not None:
            continue
        page = q.path is not None and q.locator is not None and kind_of(q.path, q.locator) == "pdf"
        if not (q.answer or q.expected or (page and q.path.is_file())):
            continue
        children = conn.execute("SELECT count(*) FROM questions WHERE parent_id=? AND retired IS NULL",
                                (q.id,)).fetchone()[0]
        if children >= VARIANTS_PER_QUESTION:
            continue
        if mock_id is None and conn.execute(
                "SELECT 1 FROM jobs WHERE kind='variants' AND arg=? AND status != 'queued' AND finished >= ?",
                (str(q.id), since)).fetchone():
            continue
        out.append(q.id)
    return out


def plan(conn, now: datetime) -> list[int]:
    """Queue what is worth doing now; returns the new job ids."""
    from pm import spot
    wanted: list[tuple[str, str]] = []
    if len(spot.pending(conn)) < SPOT_STOCK and spot.candidates(conn, 1, spot_failed(conn)):
        wanted.append(("spots", ""))
    if conn.execute("SELECT 1 FROM lh_sessions s WHERE s.topic_id IS NULL AND s.error IS NULL AND NOT EXISTS"
                    " (SELECT 1 FROM suggestions g WHERE g.kind='topic' AND g.subject=s.chat_id)"
                    ).fetchone():
        wanted.append(("sort-sessions", ""))
    # at most VARY_PER_PLAN variant jobs wait at a time, so a small budget doesn't grow the queue every hour
    room = VARY_PER_PLAN - conn.execute("SELECT count(*) FROM jobs WHERE kind='variants' AND status='queued'"
                                        ).fetchone()[0]
    wanted += [("variants", str(q)) for q in vary_candidates(conn, now)
               if not is_queued(conn, "variants", str(q))][:max(0, room)]
    return [enqueue(conn, kind, arg, now) for kind, arg in wanted if not is_queued(conn, kind, arg)]


from pm import suggest, variants  # noqa: E402,F401  (they register their job kinds)
