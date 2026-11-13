"""The JSON API behind pm ui: one request in, one status and body out. No SQL, no clock."""
import math
import os
import random
import re
import shutil
import threading
import dataclasses
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from pm import agent, bank, generators, lh, mock, practice, spot, stats, suggest, templates, tutor, versus
from pm.bugs import (episodes as bug_episodes, get_episode, runs as bug_runs, set_tags,
                     summary as bug_summary)
from pm.calibrate import posteriors
from pm.db import DEFAULTS, get_setting, put_setting, settings
from pm.energy import suggest as suggest_peak
from pm.excerpt import (FULL, default_pick, excerpt, kind_of, outline, page_png,
                        split_answer)
from pm.files import (OPENABLE, courses as file_courses, find, open_file, recent, reveal,
                      total as file_total)
from pm.links import add_link, drop_link, links, open_link, open_links
from pm.llm import ask, available as llm_available
from pm.notes import notes_dir, url_of
from pm.risk import cap_min, simulate
from pm.evidence import misses, short_label
from pm.study import (add_items, add_topic, calibration, calibration_sources, edit_topic,
                      facets, gap, get_item, get_topic, held, locator_topics, new_cap, next_topic,
                      preview, queue, rank, ready_courses, record_review, suspend, topic_counts, topics,
                      suspended_items, track_file, untrack_file, utc)
from pm.tasks import (LONG_SESSION_MIN, add_task, done, drop_task, edit_task, finished_ratios,
                      finished_tasks, last_note, log_time, open_tasks, rate_session, running_session,
                      start, stop, unrated, worked_min)
from pm.today import plan_day
from pm.units import parse_due, parse_duration

OPERATIONS = ("edit", "start", "log", "done", "drop")
_CACHE: dict[tuple, tuple] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 16


@dataclass
class Raw:
    content_type: str
    data: bytes
    max_age: int = 0


def _text(body: dict, name: str) -> str | None:
    value = body.get(name)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    return value


def _title(value: str | None) -> str:
    if not isinstance(value, str):
        raise ValueError("title must be 1-200 characters")
    value = value.strip()
    if not 1 <= len(value) <= 200:
        raise ValueError("title must be 1-200 characters")
    return value


def _task_id(part: str) -> int:
    if not (part.isascii() and part.isdigit() and len(part) < 19):  # 19+ digits don't fit SQLite's integer
        raise LookupError("no such route")
    return int(part)


def _path(value) -> Path:
    if not isinstance(value, str):
        raise ValueError("path must be text")
    try:
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("give a full path")
        return path.resolve()
    except (OSError, RuntimeError) as e:
        raise ValueError(str(e)) from None


def _file_kind(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return "pdf"
    return kind_of(path, None)


def _tilde(path: Path) -> str:
    home = Path.home()
    if path == home:
        return "~"
    try:
        return f"~/{path.relative_to(home)}"
    except ValueError:
        return str(path)


def _cwd(value: str) -> str:
    path = Path(value)
    try:
        path, home = path.resolve(), Path.home().resolve()
    except (OSError, RuntimeError):
        return value
    if path == home:
        return "~"
    try:
        return f"~/{path.relative_to(home)}"
    except ValueError:
        return value


def _int(body: dict, name: str, low: int, high: int) -> int:
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be {low}-{high}")
    return value


def _number(body: dict, name: str) -> int | float:
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    return value


def _names(body: dict, name: str) -> list[str]:
    value = body.get(name)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{name} must be a list of names")
    return value


def _page_number(locator) -> int | None:
    if isinstance(locator, str) and locator.startswith("p") and locator[1:].isdigit():
        return int(locator[1:])
    return None


def _add(conn, body: dict, now: datetime) -> int:
    title = _title(body.get("title"))
    est = _text(body, "est")
    due = _text(body, "due")
    course = _text(body, "course")
    kind = _text(body, "kind")
    energy = _text(body, "energy")
    first = _text(body, "first")
    if est is None:
        raise ValueError("give an estimate, like 90m or 2h")
    if kind is not None and not kind.strip():
        raise ValueError("kind can't be empty")
    return add_task(conn, title, parse_duration(est), now=now, course=course,
                    kind=kind.strip() if kind is not None else "task",
                    due=parse_due(due, now.date()) if due else None,
                    energy=energy if energy is not None else "deep",
                    first_step=first)


def _edit(conn, task_id: int, body: dict, now: datetime) -> None:
    values: dict[str, object] = {}
    clear = []
    title = body.get("title")
    est = _text(body, "est")
    due = _text(body, "due")
    course = _text(body, "course")
    kind = _text(body, "kind")
    energy = _text(body, "energy")
    first = _text(body, "first")
    if title is not None:
        values["title"] = _title(title)
    if est is not None:
        values["est_min"] = parse_duration(est)
    if due is not None:
        if due == "":
            clear.append("due")
        else:
            values["due"] = parse_due(due, now.date())
    if course is not None:
        if course == "":
            clear.append("course")
        else:
            values["course"] = course
    if kind is not None:
        if not kind.strip():
            raise ValueError("kind can't be empty")
        values["kind"] = kind
    if energy is not None:
        values["energy"] = energy
    if first is not None:
        if first == "":
            clear.append("first_step")
        else:
            values["first_step"] = first
    edit_task(conn, task_id, now, clear=tuple(clear), **values)


def _log(conn, task_id: int, body: dict, now: datetime) -> None:
    duration = _text(body, "duration")
    if duration is None:
        raise ValueError("give a duration, like 30m or 2h")
    log_time(conn, task_id, parse_duration(duration), now)


def _stop(conn, body: dict, now: datetime) -> dict:
    note = _text(body, "note")
    override = _text(body, "as")
    minutes = parse_duration(override) if override is not None else None
    energy = _int(body, "energy", 1, 5) if body.get("energy") is not None else None
    result = stop(conn, now, note=note, minutes=minutes, energy=energy)
    if result is None:
        raise ValueError("nothing running")
    task, mins = result
    return {"task_id": task.id, "minutes": mins,
            "long": mins > LONG_SESSION_MIN and "as" not in body}


def _finished(conn) -> dict:
    return {"tasks": [
        {
            "id": t.id,
            "title": t.title,
            "kind": t.kind,
            "est_min": t.est_min,
            "logged_min": t.logged_min,
            "ratio": round(t.logged_min / t.est_min, 2) if t.logged_min else None,
            "due": t.due.isoformat() if t.due else None,
            "done": t.done_at.isoformat(timespec="seconds") if t.done_at else None,
            "late": t.done_at.date() > t.due if t.due and t.done_at else None,
        }
        for t in reversed(finished_tasks(conn)[-10:])
    ]}


def _forecast(conn, now: datetime, cap: int, skip: int = 0):
    today = now.date() + timedelta(days=skip)
    tasks = open_tasks(conn, now)
    ratios = finished_ratios(conn)
    post = posteriors(ratios)
    key = (now.date(), skip, cap,
           tuple((t.id, t.kind, t.est_min, t.due, t.logged_min) for t in tasks),
           tuple(ratios))
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry is None:
            entry = simulate(tasks, post, cap, today, rng=random.Random(0))
            _CACHE[key] = entry
            if len(_CACHE) > _CACHE_MAX:
                del _CACHE[next(iter(_CACHE))]
    risks, crunch = entry
    return tasks, post, risks, crunch


def _risk(conn, query: dict[str, str], now: datetime) -> dict:
    setting = float(get_setting(conn, "hours_per_day", DEFAULTS["hours_per_day"]))
    raw_hours = query.get("hours")
    if raw_hours is None:
        hours = setting
    else:
        try:
            hours = float(raw_hours)
        except (TypeError, ValueError):
            raise ValueError("hours must be between 0.1 and 16") from None
        if not math.isfinite(hours) or not 0.1 <= hours <= 16:
            raise ValueError("hours must be between 0.1 and 16")
    raw_skip = query.get("skip")
    if raw_skip is None:
        skip = 0
    else:
        if (not isinstance(raw_skip, str) or not raw_skip.isascii()
                or not raw_skip.isdigit() or int(raw_skip) > 60):
            raise ValueError("skip must be between 0 and 60")
        skip = int(raw_skip)
    today = now.date() + timedelta(days=skip)
    base_crunch = _forecast(conn, now, cap_min(conn))[3]
    tasks, _, risks, crunch = _forecast(conn, now, round(hours * 60), skip)
    by_id = {t.id: t for t in tasks}
    queue_by = min((r.start_by for r in risks), default=None)
    return {
        "today": today.isoformat(),
        "hours": hours,
        "skip": skip,
        "set_hours": setting,
        "crunch": crunch,
        "base_crunch": base_crunch,
        "start_queue_by": queue_by.isoformat() if queue_by else None,
        "undated": sum(1 for t in tasks if t.due is None),
        "tasks": [
            {
                "id": r.task_id,
                "title": by_id[r.task_id].title,
                "course": by_id[r.task_id].course,
                "due": by_id[r.task_id].due.isoformat(),
                "p_late": r.p_late,
                "start_by": r.start_by.isoformat(),
                "behind": r.behind,
                "finish_p50": r.finish_p50.isoformat() if r.finish_p50 else None,
                "finish_p95": r.finish_p95.isoformat() if r.finish_p95 else None,
                "late_days": round(r.late_days, 1),
            }
            for r in risks
        ],
    }


def _stats(conn, now: datetime) -> dict:
    tasks, _, risks, crunch = _forecast(conn, now, cap_min(conn))
    summary = stats.build(conn, now, tasks, risks, crunch)
    return {**summary, "notes": stats.notes_minutes(conn), "lh": lh.minutes_by_day(conn)}


def _bug_row(ep) -> dict:
    return {
        "id": ep.id,
        "cmd": ep.cmd,
        "cwd": _cwd(ep.cwd),
        "status": ep.status,
        "opened": ep.opened.isoformat(timespec="seconds"),
        "closed": ep.closed.isoformat(timespec="seconds") if ep.closed else None,
        "fails": ep.fails,
        "lost_min": round((ep.lost_s or 0) / 60),
        "tags": ep.tags,
    }


def _bugs(conn, query: dict[str, str], now: datetime) -> dict:
    tag = query.get("tag") or None
    s = bug_summary(conn, now.date())
    return {
        "summary": {
            "fixed": s.fixed,
            "open": s.open,
            "abandoned": s.abandoned,
            "lost_min": round(s.lost_s / 60),
            "untagged": s.untagged,
            "tags": [[name, n] for name, n in s.tags],
            "bursts": [[name, n] for name, n in s.bursts],
        },
        "episodes": [_bug_row(ep) for ep in bug_episodes(conn, 50, tag)],
    }


def _bug(conn, episode_id: int) -> dict:
    ep = get_episode(conn, episode_id)
    body = _bug_row(ep)
    body["diff"] = ep.diff
    body["runs"] = [
        {"start": run.start.isoformat(timespec="seconds"), "dur_s": round(run.dur_s, 1),
         "code": run.code}
        for run in bug_runs(conn, episode_id)
    ]
    return body


def _bug_tags(conn, episode_id: int, body: dict) -> dict:
    ep = get_episode(conn, episode_id)
    tags = body.get("tags")
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ValueError("tags must be a list of names")
    return {"tags": set_tags(conn, ep.id, tags)}


def _study(conn, now: datetime) -> dict:
    cap = new_cap(conn)
    reviews = queue(conn, now, cap)
    due = Counter(item.topic_id for item in reviews)
    counts = topic_counts(conn, now)
    pick = next_topic(conn, now)
    cal = calibration(conn)
    parts = {topic.id: facets(conn, topic.id, now) for topic in topics(conn)}
    return {
        "topics": [
            {
                "id": topic.id, "course": topic.course, "name": topic.name,
                "exam": topic.exam_date.isoformat() if topic.exam_date else None,
                "weight": topic.weight,
                "mastery": parts[topic.id].mastery,
                "items": counts[topic.id][0],
                "due": due.get(topic.id, 0),
                "prereqs": topic.prereqs,
                "facets": _facets_json(parts[topic.id]),
            }
            for topic in topics(conn)
        ],
        "readiness": [
            {"course": course, "value": value, "exam": exam.isoformat(), "topics": n}
            for course, value, exam, n in ready_courses(conn, now)
        ],
        "misses": [
            {"when": row.ts.isoformat(timespec="seconds"), "topic_id": row.topic_id,
             "confidence": row.confidence, "source": row.source, "label": short_label(row.label)}
            for row in misses(conn, limit=10)
        ],
        "next": None if pick is None else {
            "topic_id": pick[0].id,
            "unblocks_id": None if pick[1] is None else pick[1].id,
        },
        "ranking": [
            {"topic_id": p.topic.id, "mastery": p.mastery, "score": p.score}
            for p in rank(conn, now)[:5]
        ],
        "calibration": {
            "n": cal.n,
            "brier": cal.brier if cal.n else None,
            "gap": gap(cal),
            "bins": [
                {"lo": lo, "hi": hi, "n": count, "said": said, "recalled": recalled}
                for lo, hi, count, said, recalled in cal.bins
            ],
            "sources": [
                {"source": name, "n": c.n, "brier": c.brier, "gap": gap(c)}
                for name, c in calibration_sources(conn)
            ],
        },
        "queue": {"due": len(reviews), "held": held(conn, now, cap)},
        "suspended": [{"id": item.id, "title": _item_title(item), "topic_id": item.topic_id}
                      for item in suspended_items(conn)],
        "suggestions": [{"id": s.id, "kind": s.kind, "text": s.text} for s in suggest.open_suggestions(conn)],
        "agent": {"budget": agent.budget(conn), "spent": agent.spent(conn, now), "queued": agent.queued(conn)},
    }


def _facets_json(f) -> dict:
    def rate(r):
        return None if r is None else {"value": r.value, "strength": r.strength, "n": r.n}
    return {"memory": rate(f.memory), "understanding": rate(f.understanding),
            "application": rate(f.application), "covered": f.covered, "total": f.total}


def _topic_file(conn, topic_id: int, body: dict, drop: bool) -> dict:
    get_topic(conn, topic_id)
    path = _path(body.get("path"))
    if drop:
        untrack_file(conn, topic_id, path)
        return {}
    if not path.is_file():
        raise ValueError(f"no such file: {path}")
    return {"sections": track_file(conn, topic_id, path)}


def _practice(conn, now: datetime) -> dict:
    errors = templates.sync(conn)
    gens: dict[int, list[str]] = {}
    for topic_id, gen in practice.linked(conn):
        gens.setdefault(topic_id, []).append(gen)
    tried = {t: (n, right) for t, n, right in practice.summary(conn, now)}
    return {
        "generators": [{"id": g, "title": generators.info(g).TITLE, "variants": list(generators.info(g).VARIANTS)}
                       for g in generators.ids()],
        "topics": [{"id": t.id, "name": t.name, "course": t.course, "gens": gens.get(t.id, []),
                    "attempts": tried.get(t.id, (0, 0))[0], "right": tried.get(t.id, (0, 0))[1]}
                   for t in topics(conn)],
        "errors": errors,
    }


CHAT_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")


def _chat(part: str) -> str:
    if not CHAT_ID.fullmatch(part):
        raise LookupError("no such route")
    return part


def _tutor(conn, now: datetime) -> dict | None:
    picked = next_topic(conn, now)
    if picked is None:
        return None
    t = picked[0]
    return {"topic_id": t.id, "topic": t.name, "course": t.course}


def _lh_state(conn, now: datetime) -> dict:
    return {"found": lh.data_dir(conn) is not None, "cards_ready": lh.cards_ready(conn, now), "unsorted": lh.unsorted(conn),
            "plugin": lh.plugin_status(conn)}


def _lh(conn) -> dict:
    found = lh.sessions(conn)
    return {
        "found": lh.data_dir(conn) is not None,
        "sessions": [{"chat_id": s.chat_id, "title": s.title, "kind": s.kind, "topic_id": s.topic_id,
                      "tagged": s.tagged, "updated": s.updated.isoformat(timespec="seconds") if s.updated else None,
                      "minutes": s.minutes, "error": s.error} for s in found[:50]],
        "skipped": [f"{s.chat_id}: {s.error}" for s in found if s.error],
    }


def _lh_map(conn, chat_id: str, body: dict) -> dict:
    if "topic_id" not in body:
        raise ValueError("give topic_id (a topic id or null)")
    topic_id = None if body["topic_id"] is None else _int(body, "topic_id", 1, 2**63 - 1)
    lh.map_session(conn, chat_id, topic_id)
    return {}


def _topic_query(query: dict) -> int:
    topic = query.get("topic") or ""
    if not (topic.isascii() and topic.isdigit() and len(topic) < 19):
        raise ValueError("topic must be a topic id")
    return int(topic)


def _lh_opening(conn, query: dict, now: datetime) -> dict:
    return {"text": lh.opening(conn, _topic_query(query), now, practice=query.get("practice") == "1")}


# The tutor's routes return answer keys: for the LearnHarness plugin only, never for pm/ui.
def _tutor_search(conn, query: dict) -> dict:
    q = query.get("q") or ""
    if not 1 <= len(q) <= 200:
        raise ValueError("q must be 1-200 characters")
    course = query.get("course") or None
    if course is not None and len(course) > 40:
        raise ValueError("course must be up to 40 characters")
    return {"hits": tutor.search(conn, q, course)}


def _tutor_questions(conn, query: dict) -> dict:
    n = query.get("n") or "5"
    if not (n.isascii() and n.isdigit() and 1 <= int(n) <= 8):
        raise ValueError("n must be 1-8")
    return {"questions": tutor.exam_questions(conn, _topic_query(query), int(n))}


def _practice_next(conn, query: dict, now: datetime) -> dict:
    topic = query.get("topic") or None
    if topic is not None and not topic.isdigit():
        raise ValueError("topic must be a topic id")
    served = practice.next_problem(conn, now, random.Random(now.isoformat()), int(topic) if topic else None)
    t, p = get_topic(conn, served.topic_id), served.problem
    # never the key or the steps: they go out only with the verdict
    return {"topic_id": t.id, "topic": t.name, "course": t.course, "gen": p.gen, "seed": p.seed,
            "variant": p.variant, "title": p.title, "text": p.text, "kind": p.kind}


def _practice_answer(conn, body: dict, now: datetime) -> dict:
    dont_know = body.get("dont_know") is True
    gen, variant, answer = body.get("gen"), body.get("variant"), body.get("answer", "")
    if not isinstance(gen, str) or not isinstance(variant, str):
        raise ValueError("give gen and variant")
    if not isinstance(answer, str) or len(answer) > mock.MAX_ANSWER:
        raise ValueError("answer must be text")
    confidence = None
    if not dont_know:
        if body.get("confidence") is None:
            raise ValueError("give a confidence")
        confidence = _int(body, "confidence", 0, 100) / 100
    seconds = _int(body, "seconds", 0, 86_400) if body.get("seconds") is not None else None
    verdict = practice.submit(conn, topic_id=_int(body, "topic_id", 1, 2**63 - 1), gen=gen,
                              seed=_int(body, "seed", 0, 2**31 - 1), variant=variant, answer=answer,
                              confidence=confidence, dont_know=dont_know, seconds=seconds, now=now)
    return {"correct": verdict.correct, "readable": verdict.readable, "key": verdict.key, "steps": verdict.steps}


def _practice_link(conn, body: dict, linking: bool) -> dict:
    gen = body.get("gen")
    if not isinstance(gen, str):
        raise ValueError("give gen")
    topic_id = _int(body, "topic_id", 1, 2**63 - 1)
    (practice.link if linking else practice.unlink)(conn, topic_id, gen)
    return {}


def _exam(conn) -> dict:
    counted: dict = {}
    for topic_id, trust, n in bank.counts(conn):
        counted.setdefault(topic_id, {})[trust] = n
    names = {t.id: t for t in topics(conn)}
    tests = []
    for m in mock.mocks(conn)[:20]:
        result = mock.result(conn, m.id) if m.status == "marked" else None
        tests.append({"id": m.id, "title": m.title, "course": m.course,
                      "questions": len(mock.items(conn, m.id)), "minutes": m.minutes, "status": m.status,
                      "pct": result.pct if result else None, "predicted": m.predicted})
    return {
        "courses": sorted({t.course for t in names.values() if t.course}),
        "topics": [{"id": t.id, "course": t.course, "name": t.name} for t in names.values()],
        "papers": [{"id": p.id, "course": p.course, "title": p.title,
                    "questions": len(bank.questions(conn, paper_id=p.id)), "minutes": p.minutes}
                   for p in bank.papers(conn)],
        "bank": [{"topic_id": tid, "topic": names[tid].name if tid in names else None,
                  "course": names[tid].course if tid in names else "", "n": sum(by.values()), "by_trust": by}
                 for tid, by in counted.items()],
        "mocks": tests,
        "open": mock.in_progress(conn),
        "to_check": [{"id": q.id, "flags": s.flags, "trust": q.trust, "attempts": s.attempts, "mean": s.mean,
                      "prompt": q.prompt.splitlines()[0][:200] if q.prompt else ""}
                     for q, s in bank.to_check(conn)],
    }


def _vary(conn, mock_id: int, now: datetime) -> dict:
    if mock.get(conn, mock_id).status != "marked":
        raise ValueError("that test isn't marked yet")
    queued = 0
    for qid in agent.vary_candidates(conn, now, mock_id):
        if not agent.is_queued(conn, "variants", str(qid)):
            agent.enqueue(conn, "variants", str(qid), now)
            queued += 1
    return {"queued": queued}


def _mock_json(conn, mock_id: int, now: datetime) -> dict:
    m = mock.get(conn, mock_id)
    left = None
    if m.started is not None:
        until = m.started + timedelta(minutes=m.minutes)
        left = int((until - (m.finished or now)).total_seconds())
    result = None
    if m.status == "marked":
        r = mock.result(conn, mock_id)
        names = {t.id: t.name for t in topics(conn)}
        result = {"got": r.got, "total": r.total, "pct": r.pct, "predicted": r.predicted,
                  "over_min": r.over_min, "said": r.said, "unread": r.unread, "missed": r.missed,
                  "by_topic": [{"topic_id": tid, "topic": names.get(tid), "got": got, "total": total}
                               for tid, got, total in r.by_topic]}
    return {"id": m.id, "title": m.title, "course": m.course, "minutes": m.minutes, "status": m.status,
            "left_s": left, "items": [mock.view(conn, mock_id, i.pos) for i in mock.items(conn, mock_id)],
            "result": result}


def _mock_new(conn, body: dict, now: datetime) -> dict:
    course = _text(body, "course")
    n = _int(body, "n", 1, 100) if body.get("n") is not None else 10
    minutes = _int(body, "minutes", 1, 600) if body.get("minutes") is not None else None
    paper_id = _int(body, "paper_id", 1, 2**62) if body.get("paper_id") is not None else None
    return {"id": mock.build(conn, course, now, random.Random(now.isoformat()), n=n, minutes=minutes,
                             paper_id=paper_id)}


def _mock_save(conn, mock_id: int, pos: int, body: dict) -> dict:
    kw: dict = {}
    if body.get("answer") is not None:
        kw["answer"] = _text(body, "answer")
    if body.get("confidence") is not None:
        kw["confidence"] = _int(body, "confidence", 0, 100) / 100
    if body.get("dont_know") is not None:
        if not isinstance(body["dont_know"], bool):
            raise ValueError("dont_know must be true or false")
        kw["dont_know"] = body["dont_know"]
    if body.get("seconds") is not None:
        kw["seconds"] = _int(body, "seconds", 0, 86_400)
    mock.save(conn, mock_id, pos, **kw)
    return {}


def _question_page(conn, question_id: int) -> tuple[int, Raw]:
    q = bank.get_question(conn, question_id)
    if q.path is None or q.locator is None or kind_of(q.path, q.locator) != "pdf":
        raise LookupError("no such route")
    if not q.path.is_file():
        raise LookupError("that file is gone")
    try:
        data = page_png(q.path, int(q.locator[1:]))
    except (OSError, ValueError) as e:
        raise LookupError(str(e)) from None
    if data is None:
        raise LookupError("pdftoppm is not installed")
    return 200, Raw("image/png", data, 3600)


def _question_import(conn, body: dict, now: datetime) -> dict:
    path = _path(body.get("path"))
    topic_id = _int(body, "topic_id", 1, 2**62)
    added, skipped = bank.import_note(conn, path, topic_id, now)
    return {"added": added, "skipped": skipped}


def _item_title(item) -> str:
    if item.prompt:
        return item.prompt
    if item.locator:
        return f"{item.path.name} › {item.locator}"
    return item.path.name


def _link_json(link) -> dict:
    short = link.target if link.kind == "url" else _tilde(Path(link.target))
    return {"id": link.id, "target": link.target, "short": short, "kind": link.kind}


def _start(conn, task_id: int, body: dict, now: datetime) -> dict:
    start(conn, task_id, now)
    if body.get("open") is not True:
        return {}
    opened, skipped = open_links(conn, task_id)  # after the start: a failing opener never undoes it
    return {"opened": opened, "skipped": skipped}


class _ModelError(ValueError):
    """The model command itself failed: stop the batch and say so, rather than blaming each item."""


def _spot_make(conn, body: dict, now: datetime) -> dict:
    n = _int(body, "n", 1, 10)

    def model(prompt: str) -> str:
        try:
            return ask(conn, prompt)
        except ValueError as e:
            raise _ModelError(str(e)) from None

    made, errors = 0, []
    for item_id in spot.candidates(conn, n):
        try:
            spot.make(conn, item_id, now, model)
            made += 1
        except _ModelError as e:
            if not made and not errors:
                raise ValueError(str(e)) from None
            errors.append(str(e))
            break
        except (LookupError, ValueError) as e:
            errors.append(f"#{item_id}: {e}")
    return {"made": made, "errors": errors}


def _spot_next(conn) -> dict:
    cards = spot.pending(conn)
    if not cards:
        return {"left": 0, "spot": None}
    card = cards[0]
    item = get_item(conn, card.item_id)
    topic = get_topic(conn, item.topic_id)
    # the changed text only: never the line number or the original before the pick
    return {"left": len(cards),
            "spot": {"id": card.id, "topic": topic.name, "course": topic.course,
                     "title": _item_title(item), "lines": card.mutated.rstrip("\n").split("\n")}}


def _spot_answer(conn, spot_id: int, body: dict, now: datetime) -> dict:
    if body.get("picked") is None or body.get("confidence") is None:
        raise ValueError("give picked and confidence")
    picked = _int(body, "picked", 1, 10_000)
    confidence = _int(body, "confidence", 0, 100)
    correct = spot.answer(conn, spot_id, picked, confidence / 100, now)
    card = spot.get(conn, spot_id)
    return {"correct": correct, "line": card.line,
            "was": card.original.split("\n")[card.line - 1],
            "shown": card.mutated.split("\n")[card.line - 1]}


def _review_next(conn, now: datetime) -> dict:
    cap = new_cap(conn)
    reviews = queue(conn, now, cap)
    if not reviews:
        return {"left": 0, "held": held(conn, now, cap), "item": None}
    item = reviews[0]
    kind = kind_of(item.path, item.locator)
    question = None
    if kind in ("markdown", "text"):
        try:
            split = split_answer(excerpt(item.path, item.locator, FULL))
        except (OSError, ValueError):
            split = None
        if split is not None:
            question = split[0]
    title = _item_title(item)
    topic = get_topic(conn, item.topic_id)
    return {
        "left": len(reviews),
        "held": held(conn, now, cap),
        "item": {"id": item.id, "topic": topic.name, "course": topic.course,
                 "title": title, "question": question, "kind": kind},
    }


def _excerpt(conn, item_id: int, now: datetime) -> dict:
    item = get_item(conn, item_id)
    kind = kind_of(item.path, item.locator)
    notes_url = get_setting(conn, "notes_url", DEFAULTS["notes_url"]).rstrip("/")
    address = url_of(item.path, item.locator, notes_dir(conn))
    body = {
        "kind": kind, "text": None, "question": None, "image": None,
        "path": _tilde(item.path), "locator": item.locator, "error": None,
        "site": f"{notes_url}{address}" if notes_url and address else None,
        "intervals": {
            str(grade): due.isoformat(timespec="seconds")
            for grade, due in preview(conn, item_id, now).items()
        },
    }
    try:
        if kind == "pdf":
            if shutil.which("pdftoppm"):
                if not item.path.is_file():
                    raise FileNotFoundError(f"no such file: {item.path}")
                pages = len(outline(item.path))
                page = _page_number(item.locator)
                if page is None or not 1 <= page <= pages:
                    raise ValueError(
                        f"no page {item.locator if page is None else page} in {item.path.name}")
                body["image"] = (f"/api/items/{item_id}/page.png"
                                 f"?v={item.path.stat().st_mtime_ns}")
            else:
                body["text"] = excerpt(item.path, item.locator, FULL)
        else:
            text = excerpt(item.path, item.locator, FULL)
            split = split_answer(text)
            if split is None:
                body["text"] = text
            else:
                body["question"], body["text"] = split
    except (OSError, ValueError) as e:
        body.update(kind="missing", text=None, question=None, image=None, error=str(e))
    return body


def _page(conn, item_id: int) -> tuple[int, Raw]:
    item = get_item(conn, item_id)
    if kind_of(item.path, item.locator) != "pdf":
        raise LookupError("no such route")
    page = int(item.locator[1:])
    try:
        data = page_png(item.path, page)
    except (OSError, ValueError) as e:
        raise LookupError(str(e)) from None
    if data is None:
        raise LookupError("pdftoppm is not installed")
    return 200, Raw("image/png", data, 3600)


def _review(conn, item_id: int, body: dict, now: datetime) -> dict:
    grade = _int(body, "grade", 1, 4)
    confidence = _int(body, "confidence", 0, 100)
    if get_item(conn, item_id).card.due > utc(now):  # graded a moment ago in another tab: a second grade would bend the schedule
        raise ValueError("that item isn't due any more")
    due = record_review(conn, item_id, grade, confidence / 100, now)
    return {"next_due": due.isoformat(timespec="seconds")}


def _suspend(conn, item_id: int, body: dict) -> dict:
    on = body.get("on", True)
    if not isinstance(on, bool):
        raise ValueError("on must be true or false")
    suspend(conn, item_id, on)
    return {}


def _topic_add(conn, body: dict, now: datetime) -> int:
    name = _text(body, "name")
    if name is None:
        raise ValueError("name must be text")
    course = _text(body, "course")
    exam = _text(body, "exam")
    weight = _number(body, "weight") if body.get("weight") is not None else None
    needs = _names(body, "needs")
    return add_topic(
        conn, name,
        course=course if course is not None else "",
        exam_date=parse_due(exam, now.date()) if exam else None,
        weight=weight if weight is not None else 1.0,
        needs=needs,
    )


def _topic_edit(conn, topic_id: int, body: dict, now: datetime) -> None:
    exam = _text(body, "exam")
    weight = _number(body, "weight") if body.get("weight") is not None else None
    values: dict[str, object] = {}
    clear = False
    if exam is not None:
        if exam == "":
            clear = True
        else:
            values["exam_date"] = parse_due(exam, now.date())
    if weight is not None:
        values["weight"] = weight
    edit_topic(conn, topic_id, clear_exam=clear, **values)


def _outline(conn, query: dict[str, str]) -> dict:
    path = _path(query.get("path"))
    try:
        sections = outline(path)
    except OSError as e:
        raise ValueError(str(e)) from None
    existing = locator_topics(conn, path)  # the dialog greys a section only for the topic that has it
    picked = {section.locator for section in default_pick(sections)}
    return {
        "path": str(path),
        "kind": _file_kind(path),
        "whole_file_exists": None in existing, "whole_file_topics": existing.get(None, []),
        "sections": [
            {
                "locator": s.locator, "title": s.title, "level": s.level,
                "lines": s.lines, "leaf": s.leaf, "pdf": s.pdf,
                "picked": s.locator in picked, "exists": s.locator in existing,
                "topics": existing.get(s.locator, []),
            }
            for s in sections
        ],
    }


def _items_add(conn, body: dict, now: datetime) -> dict:
    topic_id = body.get("topic_id")
    if isinstance(topic_id, bool) or not isinstance(topic_id, int) or not 0 < topic_id < 2**63:
        raise ValueError("topic_id must be an integer")
    path = _path(body.get("path"))
    locators = body.get("locators")
    if (not isinstance(locators, list) or not 1 <= len(locators) <= 500
            or any(v is not None and not isinstance(v, str) for v in locators)):
        raise ValueError("locators must be a list of 1-500 sections")
    if _file_kind(path) == "pdf":
        try:
            pages = len(outline(path))
        except OSError as e:
            raise ValueError(str(e)) from None
        for locator in locators:
            page = _page_number(locator)
            if page is None or not 1 <= page <= pages:
                raise ValueError(f"no page {locator if page is None else page} in {path.name}")
    else:
        # shortcut: re-reads the file per locator, fine for notes under MAX_BYTES; parse once if bulk adds get slow
        for locator in locators:
            try:
                excerpt(path, locator, FULL)
            except (OSError, ValueError) as e:
                raise ValueError(str(e)) from None
    added, skipped = add_items(conn, topic_id, path, locators, now=now)
    return {"added": added, "skipped": skipped}


def _settings(conn) -> dict:
    row = next((r for r in conn.execute("PRAGMA database_list") if r["name"] == "main"), None)
    file = row["file"] if row is not None else ""
    return {
        "values": settings(conn),
        "db": _tilde(Path(file)) if file else ":memory:",
        "files": conn.execute("SELECT COUNT(*) FROM files").fetchone()[0],
    }


def _file_hit(hit) -> dict:
    path = Path(hit.path)
    return {
        "id": hit.id,
        "path": hit.path,
        "short": _tilde(path),
        "name": path.name,
        "course": hit.course,
        "snippet": hit.snippet,
        "openable": path.suffix.lower() in OPENABLE,
    }


def _files(conn, query: dict[str, str]) -> dict:
    course = query.get("course") or None
    q = query.get("q") or ""
    if q.strip():
        hits = find(conn, q, course, 30, marks=("\x02", "\x03"))
    else:
        hits = recent(conn, 20, course)
    return {
        "hits": [_file_hit(hit) for hit in hits],
        "courses": file_courses(conn),
        "total": file_total(conn),
    }


def state(conn, now: datetime) -> dict:
    conn.execute("BEGIN")
    try:
        cap = cap_min(conn)
        tasks, post, risks, crunch = _forecast(conn, now, cap)
        by_id = {r.task_id: r for r in risks}
        peak = get_setting(conn, "peak", DEFAULTS["peak"])
        plan = plan_day(tasks, by_id, post, cap)
        session = running_session(conn)
        running = None
        if session is not None:
            task_id, began = session
            running = {"task_id": task_id, "start": began.isoformat(timespec="seconds"),
                       "elapsed_s": int((now - began).total_seconds())}
        finished = finished_tasks(conn)
        return {
            "now": now.isoformat(timespec="seconds"),
            "running": running,
            "tasks": [
                {
                    "id": t.id, "title": t.title, "course": t.course, "kind": t.kind,
                    "est_min": t.est_min, "due": t.due.isoformat() if t.due else None,
                    "energy": t.energy, "first_step": t.first_step, "logged_min": t.logged_min,
                    "running": t.running, "note": last_note(conn, t.id),
                    "p_late": by_id[t.id].p_late if t.id in by_id else None,
                    "start_by": by_id[t.id].start_by.isoformat() if t.id in by_id else None,
                    "behind": by_id[t.id].behind if t.id in by_id else None,
                    "links": [_link_json(link) for link in links(conn, t.id)],
                }
                for t in sorted(tasks, key=lambda t: (t.due or date.max, t.id))
            ],
            "today": {
                "cap_min": cap,
                "worked_min": worked_min(conn, now.date(), now),
                "peak": peak,
                "plan": [{"task_id": t.id, "minutes": minutes} for t, minutes in plan],
                "unrated": unrated(conn, now),
                "peak_hint": hint if (hint := suggest_peak(conn)) != peak else None,
            },
            "crunch": crunch,
            "reviews_due": len(queue(conn, now, new_cap(conn))),
            "new_per_day": new_cap(conn),
            "courses": sorted({t.course for t in tasks + finished if t.course}),
            "kinds": sorted({t.kind for t in tasks + finished if t.kind}),
            "llm": llm_available(conn),
            "spots": len(spot.pending(conn)),
            "exam": {"open": mock.in_progress(conn)},
            "lh": _lh_state(conn, now),
            "tutor": _tutor(conn, now),
        }
    finally:
        if conn.in_transaction:
            conn.rollback()


def _allowed(parts: list[str]) -> str | None:
    match parts:
        case (["api", "ping"] | ["api", "state"] | ["api", "finished"] | ["api", "risk"]
              | ["api", "stats"] | ["api", "bugs"]):
            return "GET"
        case ["api", "study"] | ["api", "review", "next"] | ["api", "outline"]:
            return "GET"
        case ["api", "items", item_id, "excerpt"] | ["api", "items", item_id, "page.png"]:
            return "GET" if item_id.isdigit() else None
        case ["api", "items", item_id, "review"] | ["api", "items", item_id, "suspend"]:
            return "POST" if item_id.isdigit() else None
        case ["api", "bugs", bug_id]:
            return "GET" if bug_id.isascii() and bug_id.isdigit() else None
        case ["api", "bugs", bug_id, "tags"]:
            return "POST" if bug_id.isascii() and bug_id.isdigit() else None
        case ["api", "files"]:
            return "GET"
        case ["api", "files", file_id, action] if action in ("open", "reveal"):
            return "POST" if file_id.isascii() and file_id.isdigit() else None
        case (["api", "tasks"] | ["api", "stop"] | ["api", "items"] | ["api", "topics"]
              | ["api", "energy"] | ["api", "spot", "make"]):
            return "POST"
        case ["api", "spot", "next"]:
            return "GET"
        case ["api", "spots", spot_id, "answer"]:
            return "POST" if spot_id.isdigit() else None
        case ["api", "tasks", task_id, "links"]:
            return "POST" if task_id.isdigit() else None
        case ["api", "tasks", task_id, "links", link_id, action] if action in ("drop", "open"):
            return "POST" if task_id.isdigit() and link_id.isdigit() else None
        case ["api", "tasks", task_id, action] if action in OPERATIONS:
            return "POST" if task_id.isdigit() else None
        case ["api", "topics", topic_id, "edit"] | ["api", "topics", topic_id, "files"]:
            return "POST" if topic_id.isdigit() else None
        case ["api", "topics", topic_id, "files", "drop"]:
            return "POST" if topic_id.isdigit() else None
        case ["api", "exam"] | ["api", "practice"] | ["api", "practice", "next"]:
            return "GET"
        case ["api", "practice", action] if action in ("answer", "link", "unlink"):
            return "POST"
        case ["api", "mocks"] | ["api", "questions", "import"]:
            return "POST"
        case ["api", "mocks", mock_id]:
            return "GET" if mock_id.isdigit() else None
        case ["api", "suggestions", suggestion_id, action] if action in ("accept", "reject"):
            return "POST" if suggestion_id.isdigit() else None
        case ["api", "mocks", mock_id, action] if action in ("start", "finish", "retry", "vary"):
            return "POST" if mock_id.isdigit() else None
        case ["api", "mocks", mock_id, "items", pos] | ["api", "mocks", mock_id, "items", pos, "mark"]:
            return "POST" if mock_id.isdigit() and pos.isdigit() else None
        case ["api", "questions", question_id, "page.png"]:
            return "GET" if question_id.isdigit() else None
        case ["api", "questions", question_id, "retire"]:
            return "POST" if question_id.isdigit() else None
        case (["api", "lh"] | ["api", "lh", "opening"] | ["api", "lh", "context"] | ["api", "lh", "search"]
              | ["api", "lh", "exam-questions"] | ["api", "lh", "problem"]):
            return "GET"
        case ["api", "lh", "sync"]:
            return "POST"
        case ["api", "lh", "sessions", chat_id, "map"]:
            return "POST" if CHAT_ID.fullmatch(chat_id) else None
        case ["api", "settings"]:
            return "GET or POST"
        case ["api", "versus"]:
            return "GET"
        case ["api", "versus", "sync"]:
            return "POST"
    return None


def _versus(conn, now: datetime) -> dict:
    return {"on": bool(get_setting(conn, "versus_url", "")), "board": versus.cached(conn, now.date())}


def _versus_sync(conn, now: datetime) -> dict:
    url = get_setting(conn, "versus_url", "")
    if not url:
        raise ValueError("set the scoreboard address in Settings first")
    netrc_path = os.environ.get("PM_NETRC")
    netrc = Path(netrc_path) if netrc_path else None
    versus.sync(conn, now, url, netrc)
    # the site's Versus box shows what was last pushed, which the daemon does hourly: send the fresh board now.
    # site: "" with no notes site, "updated", or why the push failed (the sync itself still worked)
    site, notes = "", get_setting(conn, "notes_url", "")
    if notes:
        try:
            stats.push(stats.summary_now(conn, now), notes, netrc)
            site = "updated"
        except ValueError as error:
            site = str(error)
    return {**_versus(conn, now), "site": site}


def handle(conn, method: str, path: str, query: dict[str, str], body: dict,
           now: datetime) -> tuple[int, dict | Raw]:
    body = body or {}
    parts = [part for part in path.split("/") if part]
    try:
        match (method, parts):
            case ("GET", ["api", "ping"]):
                return 200, {"pm": True}
            case ("GET", ["api", "state"]):
                return 200, state(conn, now)
            case ("GET", ["api", "finished"]):
                return 200, _finished(conn)
            case ("GET", ["api", "risk"]):
                return 200, _risk(conn, query, now)
            case ("GET", ["api", "stats"]):
                return 200, _stats(conn, now)
            case ("GET", ["api", "bugs"]):
                return 200, _bugs(conn, query, now)
            case ("GET", ["api", "bugs", bug_id]):
                return 200, _bug(conn, _task_id(bug_id))
            case ("POST", ["api", "bugs", bug_id, "tags"]):
                return 200, _bug_tags(conn, _task_id(bug_id), body)
            case ("GET", ["api", "versus"]):
                return 200, _versus(conn, now)
            case ("POST", ["api", "versus", "sync"]):
                return 200, _versus_sync(conn, now)
            case ("GET", ["api", "settings"]):
                return 200, _settings(conn)
            case ("POST", ["api", "settings"]):
                put_setting(conn, body.get("key"), body.get("value"))
                return 200, {}
            case ("GET", ["api", "files"]):
                return 200, _files(conn, query)
            case ("POST", ["api", "files", file_id, "open"]):
                open_file(conn, _task_id(file_id))
                return 200, {}
            case ("POST", ["api", "files", file_id, "reveal"]):
                reveal(conn, _task_id(file_id))
                return 200, {}
            case ("GET", ["api", "study"]):
                return 200, _study(conn, now)
            case ("GET", ["api", "review", "next"]):
                return 200, _review_next(conn, now)
            case ("GET", ["api", "items", item_id, "excerpt"]):
                return 200, _excerpt(conn, _task_id(item_id), now)
            case ("GET", ["api", "items", item_id, "page.png"]):
                return _page(conn, _task_id(item_id))
            case ("POST", ["api", "items", item_id, "review"]):
                return 200, _review(conn, _task_id(item_id), body, now)
            case ("POST", ["api", "items", item_id, "suspend"]):
                return 200, _suspend(conn, _task_id(item_id), body)
            case ("POST", ["api", "topics"]):
                return 200, {"id": _topic_add(conn, body, now)}
            case ("POST", ["api", "topics", topic_id, "edit"]):
                _topic_edit(conn, _task_id(topic_id), body, now)
                return 200, {}
            case ("POST", ["api", "topics", topic_id, "files"]):
                return 200, _topic_file(conn, _task_id(topic_id), body, drop=False)
            case ("POST", ["api", "topics", topic_id, "files", "drop"]):
                return 200, _topic_file(conn, _task_id(topic_id), body, drop=True)
            case ("GET", ["api", "exam"]):
                return 200, _exam(conn)
            case ("GET", ["api", "lh"]):
                return 200, _lh(conn)
            case ("POST", ["api", "lh", "sync"]):
                return 200, dataclasses.asdict(lh.sync(conn, now))
            case ("POST", ["api", "lh", "sessions", chat_id, "map"]):
                return 200, _lh_map(conn, _chat(chat_id), body)
            case ("GET", ["api", "lh", "opening"]):
                return 200, _lh_opening(conn, query, now)
            case ("GET", ["api", "lh", "context"]):
                return 200, tutor.context(conn, _topic_query(query), now)
            case ("GET", ["api", "lh", "search"]):
                return 200, _tutor_search(conn, query)
            case ("GET", ["api", "lh", "exam-questions"]):
                return 200, _tutor_questions(conn, query)
            case ("GET", ["api", "lh", "problem"]):
                return 200, tutor.problem(conn, _topic_query(query), now, random.Random(now.isoformat()))
            case ("GET", ["api", "practice"]):
                return 200, _practice(conn, now)
            case ("GET", ["api", "practice", "next"]):
                return 200, _practice_next(conn, query, now)
            case ("POST", ["api", "practice", "answer"]):
                return 200, _practice_answer(conn, body, now)
            case ("POST", ["api", "practice", "link"]):
                return 200, _practice_link(conn, body, True)
            case ("POST", ["api", "practice", "unlink"]):
                return 200, _practice_link(conn, body, False)
            case ("POST", ["api", "mocks"]):
                return 200, _mock_new(conn, body, now)
            case ("GET", ["api", "mocks", mock_id]):
                return 200, _mock_json(conn, _task_id(mock_id), now)
            case ("POST", ["api", "mocks", mock_id, "start"]):
                mock.start(conn, _task_id(mock_id), now)
                return 200, {}
            case ("POST", ["api", "mocks", mock_id, "finish"]):
                return 200, {"to_mark": mock.finish(conn, _task_id(mock_id), now)}
            case ("POST", ["api", "mocks", mock_id, "vary"]):
                return 200, _vary(conn, _task_id(mock_id), now)
            case ("POST", ["api", "suggestions", suggestion_id, "accept"]):
                return 200, {"text": suggest.accept(conn, _task_id(suggestion_id))}
            case ("POST", ["api", "suggestions", suggestion_id, "reject"]):
                suggest.reject(conn, _task_id(suggestion_id))
                return 200, {}
            case ("POST", ["api", "mocks", mock_id, "retry"]):
                return 200, {"id": mock.retry(conn, _task_id(mock_id), now, random.Random(now.isoformat()))}
            case ("POST", ["api", "mocks", mock_id, "items", pos]):
                return 200, _mock_save(conn, _task_id(mock_id), _task_id(pos), body)
            case ("POST", ["api", "mocks", mock_id, "items", pos, "mark"]):
                got = _number(body, "got")
                return 200, {"to_mark": mock.mark(conn, _task_id(mock_id), _task_id(pos), got, now)}
            case ("GET", ["api", "questions", question_id, "page.png"]):
                return _question_page(conn, _task_id(question_id))
            case ("POST", ["api", "questions", question_id, "retire"]):
                reason = _text(body, "reason") or ""
                bank.retire(conn, _task_id(question_id), reason)
                return 200, {}
            case ("POST", ["api", "questions", "import"]):
                return 200, _question_import(conn, body, now)
            case ("GET", ["api", "outline"]):
                return 200, _outline(conn, query)
            case ("POST", ["api", "items"]):
                return 200, _items_add(conn, body, now)
            case ("POST", ["api", "tasks"]):
                return 200, {"id": _add(conn, body, now)}
            case ("POST", ["api", "tasks", task_id, "edit"]):
                _edit(conn, _task_id(task_id), body, now)
                return 200, {}
            case ("POST", ["api", "tasks", task_id, "start"]):
                return 200, _start(conn, _task_id(task_id), body, now)
            case ("POST", ["api", "tasks", task_id, "links"]):
                target = body.get("target")
                if not isinstance(target, str):
                    raise ValueError("give a full path or an http(s) address")
                return 200, {"id": add_link(conn, _task_id(task_id), target, now)}
            case ("POST", ["api", "tasks", task_id, "links", link_id, "drop"]):
                drop_link(conn, _task_id(task_id), _task_id(link_id))
                return 200, {}
            case ("POST", ["api", "tasks", task_id, "links", link_id, "open"]):
                opened, skipped = open_link(conn, _task_id(task_id), _task_id(link_id))
                return 200, {"opened": opened, "skipped": skipped}
            case ("POST", ["api", "energy"]):
                rate_session(conn, _int(body, "energy", 1, 5), now)
                return 200, {}
            case ("GET", ["api", "spot", "next"]):
                return 200, _spot_next(conn)
            case ("POST", ["api", "spots", spot_id, "answer"]):
                return 200, _spot_answer(conn, _task_id(spot_id), body, now)
            case ("POST", ["api", "spot", "make"]):
                return 200, _spot_make(conn, body, now)
            case ("POST", ["api", "tasks", task_id, "log"]):
                _log(conn, _task_id(task_id), body, now)
                return 200, {}
            case ("POST", ["api", "tasks", task_id, "done"]):
                done(conn, _task_id(task_id), now)
                return 200, {}
            case ("POST", ["api", "tasks", task_id, "drop"]):
                drop_task(conn, _task_id(task_id), now)
                return 200, {}
            case ("POST", ["api", "stop"]):
                return 200, _stop(conn, body, now)
            case _:
                allowed = _allowed(parts)
                if allowed is None:
                    raise LookupError("no such route")
                return 405, {"error": f"use {allowed}"}
    except LookupError as e:
        return 404, {"error": str(e)}
    except ValueError as e:
        return 400, {"error": str(e)}
