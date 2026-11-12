"""LearnHarness in: read its data folder (never write to it) into evidence, the question bank and minutes.

Written from LearnHarness's documented session format; no LearnHarness
code is copied. Session text is untrusted: nothing in it is evaluated or followed.
"""
import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pm import bank, evidence
from pm.db import get_setting, set_setting
from pm.study import facets, get_topic

TAG = re.compile(r"\[pm:topic=(\d+)\]")
GAP_S = 300
MAX_BYTES = 50 * 2**20
SETTLE_S = 10
CARDS = "core-plugin-data/flashcards/flashcards.json"
CARDS_SEEN = "lh_cards_seen"  # internal: mtime and size of the card file last read
SCORES = {"solved": 1.0, "solvedWithHints": 0.5, "surrendered": 0.0, "movedOn": None}


def local(value) -> datetime | None:
    """Unix milliseconds or an ISO string → naive local time; anything else → None."""
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000)
        if isinstance(value, str):
            text = value.strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            t = datetime.fromisoformat(text)
            return t.astimezone().replace(tzinfo=None) if t.tzinfo else t
    except (ValueError, OverflowError, OSError):
        return None
    return None


@dataclass
class Answer:
    ref: str
    ts: datetime
    role: str
    question: str
    options: list[str]
    correct_options: list[int]
    correct: bool
    confidence: float | None
    dont_know: bool


@dataclass
class Solved:
    ref: str
    ts: datetime
    statement: str
    solution: str
    outcome: str
    score: float | None


@dataclass
class Session:
    chat_id: str
    title: str
    kind: str
    created: datetime | None
    updated: datetime | None
    tag: int | None
    answers: list[Answer] = field(default_factory=list)
    solved: list[Solved] = field(default_factory=list)
    days: dict[str, int] = field(default_factory=dict)


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b["text"] for b in content
                         if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
    return ""


def _str(value) -> str:
    return value if isinstance(value, str) else ""


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _answer(chat_id, msg, ts, calls) -> Answer | None:
    details = msg.get("details")
    if msg.get("isError") is True or not isinstance(details, dict) or details.get("kind") != "quiz":
        return None
    if details.get("dismissed") is True:
        return None
    dont_know = details.get("dontKnow") is True
    if not isinstance(details.get("correct"), bool) and not dont_know:
        return None
    mid = msg.get("id")
    if not isinstance(mid, str) or not mid:
        return None
    if msg.get("toolName") == "probe":
        role = "probe"
    else:
        role = details.get("questionType") if details.get("questionType") in ("predict", "check") else "check"
    call = calls.get(msg.get("toolCallId"))
    args = call.get("arguments") if isinstance(call, dict) and isinstance(call.get("arguments"), dict) else {}
    question = _str(details.get("questionText")) or _str(args.get("question"))
    options = []
    for o in details.get("options") if isinstance(details.get("options"), list) else []:
        if isinstance(o, str):
            options.append(o)
        elif isinstance(o, dict) and isinstance(o.get("label"), str):
            options.append(o["label"])
    idx = details.get("correctIndices")
    good = (isinstance(idx, list) and all(isinstance(i, int) and not isinstance(i, bool) and 1 <= i <= len(options)
                                          for i in idx))
    conf = details.get("confidence")
    confidence = conf / 100 if _number(conf) and 0 <= conf <= 100 and not dont_know else None
    when = local(details.get("answeredAt")) or ts
    if when is None:
        return None
    return Answer(f"{chat_id}/{mid}", when, role, question, options, list(idx) if good else [],
                  details.get("correct") is True and not dont_know, confidence, dont_know)


def _days(stamps: list[float]) -> dict[str, int]:
    seconds: dict[str, float] = {}
    stamps = sorted(stamps)
    for a, b in zip(stamps, stamps[1:]):
        gap = (b - a) / 1000
        if 0 <= gap <= GAP_S:
            day = datetime.fromtimestamp(a / 1000).date().isoformat()
            seconds[day] = seconds.get(day, 0) + gap
    return {d: round(s / 60) for d, s in seconds.items() if round(s / 60) > 0}


def parse_session(data: dict) -> Session:
    if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not isinstance(data.get("messages"), list):
        raise ValueError("not a LearnHarness session")
    version = data.get("version", 1)
    if _number(version) and version > 1:
        raise ValueError(f"newer LearnHarness format (version {version})")
    chat_id = data["id"]
    kind = data.get("kind") if isinstance(data.get("kind"), str) else "teach"
    title = data.get("title") if isinstance(data.get("title"), str) and data["title"].strip() else chat_id
    s = Session(chat_id, title, kind, local(data.get("createdAt")), local(data.get("updatedAt")), None)
    messages = [m for m in data["messages"] if isinstance(m, dict)]
    first_user = next((m for m in messages if m.get("role") == "user"), None)
    if first_user is not None:
        found = TAG.search(_text(first_user.get("content")))
        s.tag = int(found[1]) if found and len(found[1]) < 19 else None  # more digits than SQLite can hold is no topic
    calls: dict = {}
    problem = None
    stamps = []
    for m in messages:
        stamp = m.get("timestamp")
        ts = local(stamp)
        if _number(stamp) and ts is not None:  # local() proved it converts, so _days can't overflow on it
            stamps.append(stamp)
        role = m.get("role")
        if role == "assistant":
            for block in m.get("content") if isinstance(m.get("content"), list) else []:
                if not isinstance(block, dict) or block.get("type") != "toolCall" or not isinstance(block.get("id"), str):
                    continue
                calls[block["id"]] = block  # a repeated id replaces the earlier call from here on
                args = block.get("arguments") if isinstance(block.get("arguments"), dict) else {}
                if block.get("name") == "problem" and isinstance(m.get("id"), str):
                    problem = (m["id"], block["id"], _str(args.get("statement")), _str(args.get("modelSolution")))
                elif block.get("name") == "conclude" and problem is not None:
                    outcome = args.get("outcome")
                    if outcome in SCORES and ts is not None:
                        s.solved.append(Solved(f"{chat_id}/{problem[0]}/{problem[1]}", ts, problem[2], problem[3],
                                               outcome, SCORES[outcome]))
                    problem = None
        elif role == "toolResult" and m.get("toolName") in ("probe", "quiz"):
            answer = _answer(chat_id, m, ts, calls)
            if answer is not None:
                s.answers.append(answer)
        elif role == "custom" and m.get("customType") == "problem-dismissed":
            problem = None
    s.days = _days(stamps)
    return s


# --- the data folder -------------------------------------------------------------------------------

def default_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "LearnHarness" / "data"


def data_dir(conn) -> Path | None:
    setting = get_setting(conn, "lh_dir", "")
    folder = Path(setting).expanduser() if setting else default_dir()
    try:
        return folder if (folder / "chats").is_dir() else None
    except OSError:
        return None


@dataclass
class Sync:
    sessions: int = 0
    answers: int = 0
    outcomes: int = 0
    questions: int = 0
    cards: int = 0
    skipped: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any((self.sessions, self.answers, self.outcomes, self.questions, self.cards))


@dataclass
class LhSession:
    chat_id: str
    title: str
    kind: str
    topic_id: int | None
    tagged: bool
    created: datetime | None
    updated: datetime | None
    minutes: int
    error: str | None


def _iso(t: datetime | None) -> str | None:
    return t.isoformat(timespec="seconds") if t else None


def _label(text: str) -> str:
    lines = text.strip().splitlines()
    return lines[0][:200] if lines else ""


def _retopic(conn, chat_id: str, topic_id: int | None) -> None:
    """Point every evidence row and question of the session at its topic."""
    match = "substr(ref, 1, length(?) + 1) = ? || '/'"
    conn.execute(f"UPDATE evidence SET topic_id=? WHERE source IN ('lh-quiz', 'lh-practice') AND {match}",
                 (topic_id, chat_id, chat_id))
    conn.execute(f"UPDATE questions SET topic_id=? WHERE origin='lh' AND {match}", (topic_id, chat_id, chat_id))


def _store(conn, s: Session, mtime: float, size: int, now: datetime, out: Sync) -> None:
    old = conn.execute("SELECT topic_id, tagged FROM lh_sessions WHERE chat_id=?", (s.chat_id,)).fetchone()
    manual = old is not None and not old["tagged"] and old["topic_id"] is not None  # pm lh map wins over the tag
    tagged = (not manual and s.tag is not None
              and conn.execute("SELECT 1 FROM topics WHERE id=?", (s.tag,)).fetchone() is not None)
    topic_id = s.tag if tagged else (old["topic_id"] if old else None)
    minutes = sum(s.days.values())
    conn.execute(
        "INSERT INTO lh_sessions(chat_id, title, kind, topic_id, tagged, created, updated, minutes, mtime, size, error)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,NULL) ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title,"
        " kind=excluded.kind, topic_id=excluded.topic_id, tagged=excluded.tagged, created=excluded.created,"
        " updated=excluded.updated, minutes=excluded.minutes, mtime=excluded.mtime, size=excluded.size, error=NULL",
        (s.chat_id, s.title, s.kind, topic_id, int(tagged), _iso(s.created), _iso(s.updated), minutes, mtime, size))
    conn.execute("DELETE FROM lh_days WHERE chat_id=?", (s.chat_id,))
    conn.executemany("INSERT INTO lh_days(chat_id, day, minutes) VALUES(?,?,?)",
                     [(s.chat_id, day, m) for day, m in s.days.items()])
    for a in s.answers:
        out.answers += evidence.add(
            conn, source="lh-quiz", ref=a.ref, ts=a.ts, topic_id=topic_id, correct=a.correct,
            confidence=a.confidence, dont_know=a.dont_know, grader="code",
            facet="understanding" if a.role in ("check", "probe") else None, label=_label(a.question), commit=False)
        if len(a.options) >= 2 and a.correct_options and not bank.has(conn, "lh", a.ref):
            try:
                bank.add_question(conn, origin="lh", ref=a.ref, prompt=a.question, now=now, trust="unverified",
                                  topic_id=topic_id, kind="choice",
                                  expected={"options": a.options, "correct": a.correct_options}, commit=False)
                out.questions += 1
            except ValueError:
                pass  # no question text, too many options: not a usable bank question
    for x in s.solved:
        out.outcomes += evidence.add(
            conn, source="lh-practice", ref=x.ref, ts=x.ts, topic_id=topic_id, score=x.score, grader="llm",
            facet="application", label=_label(x.statement), commit=False)
        if x.statement.strip() and x.solution.strip() and not bank.has(conn, "lh", x.ref):
            try:
                bank.add_question(conn, origin="lh", ref=x.ref, prompt=x.statement, answer=x.solution, now=now,
                                  trust="unverified", topic_id=topic_id, commit=False)
                out.questions += 1
            except ValueError:
                pass
    _retopic(conn, s.chat_id, topic_id)
    conn.execute("UPDATE lh_cards SET topic_id=? WHERE chat_id=?", (topic_id, s.chat_id))


def _refuse(conn, chat_id: str, mtime: float, size: int, message: str) -> None:
    conn.execute(
        "INSERT INTO lh_sessions(chat_id, title, kind, mtime, size, error) VALUES(?,?,?,?,?,?)"
        " ON CONFLICT(chat_id) DO UPDATE SET mtime=excluded.mtime, size=excluded.size, error=excluded.error",
        (chat_id, chat_id, "teach", mtime, size, message))


def sync(conn, now: datetime, root: Path | None = None) -> Sync:
    """Read new and changed sessions and the card file. Reads only; a file still being written waits."""
    root = root or data_dir(conn)
    if root is None:
        raise ValueError("LearnHarness data not found (pm set lh_dir <folder>)")
    out = Sync()
    try:
        files = sorted((root / "chats").glob("*.json"))
    except OSError as e:
        raise ValueError(f"can't read {root / 'chats'}: {e}") from None
    for path in files:
        try:
            st = path.stat()
        except OSError:
            continue
        if now.timestamp() - st.st_mtime < SETTLE_S:
            continue  # still being written: next time
        row = conn.execute("SELECT mtime, size FROM lh_sessions WHERE chat_id=?", (path.stem,)).fetchone()
        if row and row["mtime"] == st.st_mtime and row["size"] == st.st_size:
            continue
        if st.st_size > MAX_BYTES:
            out.skipped.append(f"{path.name}: too large")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # half-written or unreadable: retried next time, never recorded as broken
        try:
            session = parse_session(data)
            if session.chat_id != path.stem:
                raise ValueError("the session id doesn't match its file name")
        except ValueError as e:
            _refuse(conn, path.stem, st.st_mtime, st.st_size, str(e))
            conn.commit()
            out.skipped.append(f"{path.name}: {e}")
            continue
        try:
            _store(conn, session, st.st_mtime, st.st_size, now, out)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        out.sessions += 1
    _sync_cards(conn, root, out)
    return out


def _session(row) -> LhSession:
    return LhSession(row["chat_id"], row["title"], row["kind"], row["topic_id"], bool(row["tagged"]),
                     local(row["created"]), local(row["updated"]), row["minutes"], row["error"])


def sessions(conn) -> list[LhSession]:
    rows = conn.execute("SELECT * FROM lh_sessions ORDER BY updated IS NULL, updated DESC, chat_id")
    return [_session(r) for r in rows]


def map_session(conn, chat_id: str, topic_id: int | None) -> None:
    if conn.execute("SELECT 1 FROM lh_sessions WHERE chat_id=?", (chat_id,)).fetchone() is None:
        raise LookupError(f"no LearnHarness session {chat_id!r}")
    if topic_id is not None:
        get_topic(conn, topic_id)
    conn.execute("UPDATE lh_sessions SET topic_id=?, tagged=0 WHERE chat_id=?", (topic_id, chat_id))
    _retopic(conn, chat_id, topic_id)
    conn.execute("UPDATE lh_cards SET topic_id=? WHERE chat_id=?", (topic_id, chat_id))
    conn.commit()


def unsorted(conn) -> int:
    """Sessions read without a topic (and without an error)."""
    return conn.execute("SELECT count(*) FROM lh_sessions WHERE topic_id IS NULL AND error IS NULL").fetchone()[0]


def minutes_by_day(conn) -> dict[str, int]:
    return {r[0]: r[1] for r in conn.execute("SELECT day, sum(minutes) FROM lh_days GROUP BY day ORDER BY day")}


# --- flashcards ------------------------------------------------------------------------------------
# shortcut: LearnHarness's card file is undocumented, so any surprise skips cards; revisit if its docs describe it

def read_cards(data: dict) -> list[tuple[str, str | None, str, int, float | None, datetime | None, datetime | None]]:
    if (not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("propositions"), dict)
            or not isinstance(data.get("decks"), list)):
        raise ValueError("unsupported format")
    chat_of: dict[str, str | None] = {}
    for deck in data["decks"]:
        if not isinstance(deck, dict) or not isinstance(deck.get("propositionIds"), list):
            continue
        source = deck.get("sourceId")
        chat = source if isinstance(source, str) and source.startswith("chat_") else None
        for pid in deck["propositionIds"]:
            if isinstance(pid, str):
                chat_of.setdefault(pid, chat)
    cards = []
    for prop in data["propositions"].values():
        if not isinstance(prop, dict) or not isinstance(prop.get("id"), str):
            continue
        sched = prop.get("schedule")
        if not isinstance(sched, dict):
            continue
        state, stability = sched.get("state"), sched.get("stability")
        times = sched.get("last_review"), sched.get("due")
        if (not isinstance(state, int) or isinstance(state, bool) or not 0 <= state <= 3 or not _number(stability)
                or not all(t is None or _number(t) for t in times)):
            continue
        try:
            stability = float(stability)
        except OverflowError:
            continue
        if not math.isfinite(stability):
            continue
        name = prop.get("name") if isinstance(prop.get("name"), str) else ""
        cards.append((prop["id"], chat_of.get(prop["id"]), name, state, stability,
                      local(times[0]) if times[0] is not None else None,
                      local(times[1]) if times[1] is not None else None))
    return cards


def _sync_cards(conn, root: Path, out: Sync) -> None:
    path = root / CARDS
    try:
        if not path.is_file():
            return
        st = path.stat()
        seen = f"{st.st_mtime}:{st.st_size}"
        if st.st_size > MAX_BYTES or get_setting(conn, CARDS_SEEN, "") == seen:
            return
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        set_setting(conn, CARDS_SEEN, seen)  # half-written or broken: wait for it to change, don't reread it every tick
        return
    try:
        cards = read_cards(data)
    except ValueError:
        out.skipped.append("flashcards: unsupported format (skipped)")
        set_setting(conn, CARDS_SEEN, seen)
        return
    before = {r[0]: (r[1], r[2], r[3]) for r in conn.execute("SELECT prop_id, state, stability, due FROM lh_cards")}
    topics = {r[0]: r[1] for r in conn.execute("SELECT chat_id, topic_id FROM lh_sessions")}
    rows = [(pid, chat, topics.get(chat), name, state, stability, _iso(last), _iso(due))
            for pid, chat, name, state, stability, last, due in cards]
    try:
        conn.execute("DELETE FROM lh_cards")
        conn.executemany("INSERT OR REPLACE INTO lh_cards(prop_id, chat_id, topic_id, name, state, stability,"
                         " last_review, due) VALUES(?,?,?,?,?,?,?,?)", rows)
        conn.execute("INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (CARDS_SEEN, seen))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    out.cards += sum(1 for r in rows if before.get(r[0]) != (r[4], r[5], r[7]))


def summary_line(out: Sync) -> str:
    if not out.changed:
        return "learnharness: nothing new"
    return (f"learnharness: {out.sessions} sessions, {out.answers} answers, {out.outcomes} outcomes, "
            f"{out.questions} questions, {out.cards} cards")


# --- the plugin (pm-bridge) -------------------------------------------------------------------------

PLUGIN_FILES = ("manifest.json", "backend.cjs")
PLUGIN_ID = "pm-bridge"


def plugin_source() -> Path:
    return Path(__file__).parent / "lh_plugin" / "dist"


def _version(manifest: Path) -> tuple[str | None, str | None]:
    """(id, version) of a manifest; raises OSError or ValueError when it can't be read."""
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("not a manifest")
    return data.get("id"), data.get("version")


def plugin_status(conn) -> str:
    root = data_dir(conn)
    if root is None:
        return "no-app"
    try:
        _, installed = _version(root / "plugins" / PLUGIN_ID / "dist" / "manifest.json")
    except (OSError, ValueError):
        return "missing"
    return "ok" if installed == _version(plugin_source() / "manifest.json")[1] else "old"


def install_plugin(conn) -> tuple[Path, bool]:
    """Copy the two plugin files into LearnHarness's plugin folder; nothing else there is touched."""
    root = data_dir(conn)
    if root is None:
        raise ValueError("LearnHarness data not found (pm set lh_dir <folder>)")
    folder = root / "plugins" / PLUGIN_ID
    dist = folder / "dist"
    for part in (root / "plugins", folder, dist, *(dist / n for n in PLUGIN_FILES)):
        if part.is_symlink():
            raise ValueError(f"{part} is a symlink; pm won't write through it")
    manifest = dist / "manifest.json"
    replaced = manifest.exists()
    if replaced:
        try:
            found, _ = _version(manifest)
        except (OSError, ValueError):
            found = None
        if found != PLUGIN_ID:
            raise ValueError("another plugin is installed in that folder")
    try:
        dist.mkdir(parents=True, exist_ok=True)
        for name in PLUGIN_FILES:
            tmp = dist / f".{name}.pm-tmp"
            tmp.unlink(missing_ok=True)  # a planted symlink here would otherwise be written through
            tmp.write_bytes((plugin_source() / name).read_bytes())
            os.replace(tmp, dist / name)
    except OSError as e:
        raise ValueError(f"couldn't install the plugin: {e}") from None
    return folder, replaced


# --- the first message of a new session ------------------------------------------------------------

def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def opening(conn, topic_id: int, now: datetime, practice: bool = False) -> str:
    topic = get_topic(conn, topic_id)
    lines = [f'[pm:topic={topic.id}] I want to study "{topic.name}"' + (f" (course: {topic.course})." if topic.course
                                                                        else ".")]
    if topic.exam_date is not None:
        days = (topic.exam_date - now.date()).days
        if days == 0:
            lines.append(f"My exam is today, {topic.exam_date}.")
        elif days > 0:
            lines.append(f"My exam is on {topic.exam_date}, in {days} day{'s' if days != 1 else ''}.")
    f = facets(conn, topic.id, now)
    parts = [(f.memory, "Memory", "no items yet"), (f.understanding, "understanding", "no checks yet"),
             (f.application, "practice", "no practice yet")]
    if all(p is None for p, _, _ in parts):
        lines.append("From my planner: nothing recorded yet.")
    else:
        said = ", ".join(missing if p is None else f"{name} {_pct(p.value)}" for p, name, missing in parts)
        line = f"From my planner: mastery {_pct(f.mastery)}. {said[0].upper()}{said[1:]}."
        if f.total:
            line += f" I have covered {f.covered} of {f.total} sections of my notes."
        lines.append(line)
    missed = [r for r in evidence.misses(conn, limit=1000) if r.topic_id == topic.id][:5]
    if missed:
        lines.append("Recent answers I got wrong while being confident:")
        lines += [f"- {evidence.short_label(r.label)} (I said {_pct(r.confidence)})" for r in missed]
    notes = [r[0] for r in conn.execute("SELECT path FROM topic_files WHERE topic_id=? ORDER BY path", (topic.id,))
             if Path(r[0]).is_file()][:5]
    if notes:
        lines.append("My notes for this topic:")
        lines += [f"- {p}" for p in notes]
    lines.append("Please give me exam-style practice problems on this topic." if practice
                 else "Please check what I already know first, then teach what is missing.")
    return "\n".join(lines)


def cards_ready(conn, now: datetime) -> int:
    return conn.execute("SELECT count(*) FROM lh_cards WHERE state != 0 AND due IS NOT NULL AND due <= ?",
                        (_iso(now),)).fetchone()[0]
