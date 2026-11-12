import base64
import json
import math
import netrc
import random
import shlex
from datetime import datetime, timedelta
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pm import versus
from pm.bugs import episodes, summary
from pm.calibrate import Posterior, median_ratio, posteriors
from pm.db import get_setting, set_setting
from pm.excerpt import _LINES, _PAGE
from pm.inbox import done as inbox_done
from pm.notes import notes_dir, url_of
from pm.risk import TaskRisk, cap_min, forecast
from pm.study import calibration, get_topic, held, mastery, new_cap, queue, topics
from pm.tasks import Task, _minutes, finished_ratios, finished_tasks, worked_min
from pm.today import plan_day

MAX_REPLY = 5_000_000  # the site caps what it stores at 5 MB; more than that is not our backup
DAY_KEYS = ("min", "deep", "peak", "reviews", "recalled", "fails", "fixes")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise URLError(f"redirect to {newurl} refused")


def urlopen(request: Request, timeout: float = 20):
    return build_opener(_NoRedirect).open(request, timeout=timeout)


def _peak_minutes(start: datetime, end: datetime, peak: str) -> int:
    try:
        lo, hi = (int(part) for part in peak.split("-"))
    except ValueError:
        return 0
    if not (0 <= lo < hi <= 24):
        return 0
    midnight = start.replace(hour=0, minute=0, second=0, microsecond=0)
    window_start, window_end = midnight + timedelta(hours=lo), midnight + timedelta(hours=hi)  # hi=24 is next midnight
    overlap = min(end, window_end) - max(start, window_start)
    return max(0, int(overlap.total_seconds() // 60))


def _days(conn, now: datetime, peak: str) -> dict:
    days: dict[str, dict] = {}

    def cell(day: str) -> dict:
        return days.setdefault(day, dict.fromkeys(DAY_KEYS, 0))

    for s in conn.execute("SELECT s.start, s.end, t.energy FROM sessions s"
                          " JOIN tasks t ON t.id=s.task_id"):
        start = datetime.fromisoformat(s["start"])
        end = datetime.fromisoformat(s["end"]) if s["end"] else now
        # shortcut: sessions past midnight count on their start day, split them if late-night work matters
        day = cell(start.date().isoformat())
        day["min"] += _minutes(start, end)
        if s["energy"] == "deep":
            day["deep"] += _minutes(start, end)
            day["peak"] += _peak_minutes(start, end, peak)
    for r in conn.execute("SELECT ts, recalled FROM reviews"):
        day = cell(datetime.fromisoformat(r["ts"]).date().isoformat())
        day["reviews"] += 1
        day["recalled"] += r["recalled"]
    for r in conn.execute("SELECT start FROM runs WHERE code != 0"):
        cell(datetime.fromisoformat(r["start"]).date().isoformat())["fails"] += 1
    for r in conn.execute("SELECT closed FROM episodes"
                          " WHERE status='fixed' AND closed IS NOT NULL"):
        cell(datetime.fromisoformat(r["closed"]).date().isoformat())["fixes"] += 1
    return dict(sorted((d, c) for d, c in days.items() if any(c.values())))


def _time(conn, now: datetime) -> dict:
    today = now.date()
    lo = today - timedelta(days=27)
    by_course: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    by_energy: dict[str, int] = {}
    for s in conn.execute("SELECT s.start, s.end, t.course, t.kind, t.energy FROM sessions s"
                          " JOIN tasks t ON t.id=s.task_id"):
        start = datetime.fromisoformat(s["start"])
        if not lo <= start.date() <= today:
            continue
        end = datetime.fromisoformat(s["end"]) if s["end"] else now
        mins = _minutes(start, end)
        by_course[s["course"] or "other"] = by_course.get(s["course"] or "other", 0) + mins
        by_kind[s["kind"]] = by_kind.get(s["kind"], 0) + mins
        by_energy[s["energy"]] = by_energy.get(s["energy"], 0) + mins
    return {"by_course": dict(sorted(by_course.items())),
            "by_kind": dict(sorted(by_kind.items())),
            "by_energy": dict(sorted(by_energy.items()))}


def _estimates(conn, post: dict[str, Posterior]) -> dict:
    kinds = [
        {"kind": "all" if kind == "*" else kind, "n": p.n, "median": round(median_ratio(p), 2)}
        for kind, p in post.items() if p.n
    ]
    history = [
        {"done": t.done_at.date().isoformat(), "title": t.title, "kind": t.kind,
         "ratio": round(t.logged_min / t.est_min, 2)}
        for t in finished_tasks(conn) if t.logged_min > 0
    ][-30:]
    return {"kinds": kinds, "history": history}


def _deadlines(conn, tasks: list[Task], risks: list[TaskRisk], crunch: float) -> dict:
    finished = [t for t in finished_tasks(conn) if t.due]
    late = [t for t in finished if t.done_at.date() > t.due]
    by_id = {t.id: t for t in tasks}
    return {
        "crunch": round(crunch, 3),
        "open": [
            {"title": by_id[r.task_id].title, "course": by_id[r.task_id].course,
             "due": by_id[r.task_id].due.isoformat(), "p_late": round(r.p_late, 3),
             "start_by": r.start_by.isoformat(), "behind": r.behind}
            for r in risks
        ],
        "on_time": len(finished) - len(late),
        "late": len(late),
        "recent": [
            {"title": t.title, "due": t.due.isoformat(), "done": t.done_at.date().isoformat(),
             "late": t.done_at.date() > t.due}
            for t in reversed(finished[-10:])
        ],
    }


def _today(conn, now: datetime, tasks: list[Task], risks: list[TaskRisk],
           post: dict[str, Posterior]) -> dict:
    cap = cap_min(conn)
    by_id = {r.task_id: r for r in risks}
    plan = plan_day(tasks, by_id, post, cap)
    return {
        "cap_min": cap,
        "worked_min": worked_min(conn, now.date(), now),
        "plan": [
            {"id": t.id, "title": t.title, "course": t.course, "minutes": minutes,
             "energy": t.energy, "due": t.due.isoformat() if t.due else None,
             "behind": by_id[t.id].behind if t.id in by_id else False,
             "first": t.first_step}
            for t, minutes in plan
        ],
    }


def _item_title(item, url: str | None) -> str:
    if item.prompt:
        return item.prompt
    if item.locator and not _LINES.match(item.locator) and not _PAGE.match(item.locator):
        return item.locator
    if url is not None:
        return item.path.stem
    return f"item #{item.id}"


def _study(conn, now: datetime, base: Path | None) -> dict:
    cal = calibration(conn)
    cap = new_cap(conn)
    items = queue(conn, now, cap)
    due = []
    for item in items[:30]:
        url = url_of(item.path, item.locator, base)
        due.append({"id": item.id, "topic": get_topic(conn, item.topic_id).name,
                    "title": _item_title(item, url), "url": url})
    return {
        "reviews": cal.n,
        "brier": None if cal.n == 0 else round(cal.brier, 3),
        "due_now": len(items),
        "held": held(conn, now, cap),
        "due": due,
        "bins": [
            {"lo": lo, "hi": hi, "n": n, "said": round(said, 3), "recalled": round(recalled, 3)}
            for lo, hi, n, said, recalled in cal.bins
        ],
        "topics": [
            {"course": t.course, "name": t.name,
             "exam": t.exam_date.isoformat() if t.exam_date else None,
             "weight": t.weight, "mastery": round(mastery(conn, t.id, now), 3)}
            for t in topics(conn)
        ],
    }


def _prog(cmd: str) -> str:
    try:
        parts = shlex.split(cmd)
    except ValueError:
        parts = cmd.split()
    return Path(parts[0]).name if parts else ""


def _bugs(conn, today) -> dict:
    s = summary(conn, today)
    return {
        "fixed": s.fixed,
        "open": s.open,
        "abandoned": s.abandoned,
        "lost_min": round(s.lost_s / 60),
        "untagged": s.untagged,
        "tags": [[tag, n] for tag, n in s.tags],
        "bursts": [[tag, n] for tag, n in s.bursts],
        "recent": [
            {"id": ep.id, "prog": _prog(ep.cmd), "status": ep.status, "fails": ep.fails,
             "lost_min": round((ep.lost_s or 0) / 60), "tags": ep.tags,
             "opened": ep.opened.date().isoformat()}
            for ep in episodes(conn, 20)
        ],
    }


def summary_now(conn, now: datetime) -> dict:
    tasks, post, risks, crunch = forecast(conn, now, random.Random(0))
    return build(conn, now, tasks, risks, crunch, post)


def build(conn, now: datetime, tasks: list[Task], risks: list[TaskRisk], crunch: float,
          post: dict[str, Posterior] | None = None) -> dict:
    peak = get_setting(conn, "peak", "09-12")
    if post is None:
        post = posteriors(finished_ratios(conn))
    return {
        "version": 1,
        "generated": now.isoformat(timespec="seconds"),
        "settings": {
            "hours_per_day": float(get_setting(conn, "hours_per_day", "4")),
            "peak": peak,
        },
        "days": _days(conn, now, peak),
        "time": _time(conn, now),
        "estimates": _estimates(conn, post),
        "deadlines": _deadlines(conn, tasks, risks, crunch),
        "today": _today(conn, now, tasks, risks, post),
        "study": _study(conn, now, notes_dir(conn)),
        "bugs": _bugs(conn, now.date()),
        "inbox_done": inbox_done(conn),
        "versus": versus.cached(conn, now.date()),  # the scoreboard as of the last sync; None when it's off
    }


def request(url: str, path: str, netrc_path: Path | None, *, method: str = "GET",
            body: bytes | None = None, what: str = "push") -> bytes:
    if not url:
        raise ValueError("set notes_url first: pm set notes_url https://your-site.pages.dev")
    if not url.startswith("https://"):
        raise ValueError("notes_url must start with https://")
    parts = urlsplit(url)
    host = parts.hostname or parts.netloc
    try:
        auth = netrc.netrc(netrc_path or Path.home() / ".netrc").authenticators(host)
    except (OSError, netrc.NetrcParseError):
        auth = None
    if not auth or not auth[0] or not auth[2]:
        raise ValueError(f"add 'machine {host} login USER password PASS' to ~/.netrc (chmod 600)")
    token = base64.b64encode(f"{auth[0]}:{auth[2]}".encode()).decode()
    req = Request(
        url.rstrip("/") + path, data=body, method=method,
        headers={"Content-Type": "application/json", "Authorization": f"Basic {token}",
                 "User-Agent": "pm/0.1"},
    )
    try:
        with urlopen(req, timeout=20) as response:
            reply = response.read(MAX_REPLY + 1)
        if len(reply) > MAX_REPLY:
            raise ValueError(f"{what} failed: the reply is too large")
        return reply
    except HTTPError as e:
        raise ValueError(f"{what} failed: HTTP {e.code}"
                         + (" (check ~/.netrc)" if e.code == 401 else "")) from None
    except URLError as e:
        raise ValueError(f"{what} failed: {e.reason}") from None
    except (HTTPException, OSError) as e:
        raise ValueError(f"{what} failed: {e}") from None


def push(data: dict, url: str, netrc_path: Path | None = None) -> int:
    body = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()
    request(url, "/api/pm", netrc_path, method="PUT", body=body)
    return len(body)


def pull_notes(url: str, netrc_path: Path | None = None) -> dict[str, int]:
    body = request(url, "/api/backup", netrc_path, what="pull")
    try:
        backup = json.loads(body)
    except (json.JSONDecodeError, TypeError, RecursionError, UnicodeDecodeError):
        raise ValueError("pull failed: unexpected backup shape") from None
    if backup is None:
        return {}
    if not isinstance(backup, dict):
        raise ValueError("pull failed: unexpected backup shape")
    if "study.time" not in backup:
        return {}
    raw = backup["study.time"]
    if not isinstance(raw, str):
        raise ValueError("pull failed: unexpected backup shape")
    try:
        study = json.loads(raw)
    except (json.JSONDecodeError, TypeError, RecursionError, UnicodeDecodeError):
        raise ValueError("pull failed: unexpected backup shape") from None
    if not isinstance(study, dict):
        raise ValueError("pull failed: unexpected backup shape")
    days: dict[str, int] = {}
    for day, subjects in study.items():
        if not isinstance(subjects, dict):
            raise ValueError("pull failed: unexpected backup shape")
        total = 0.0
        for ms in subjects.values():
            if (isinstance(ms, bool) or not isinstance(ms, (int, float))
                    or not math.isfinite(ms) or ms < 0):
                raise ValueError("pull failed: unexpected backup shape")
            total += ms
        minutes = int(total // 60_000)
        if minutes:
            days[day] = minutes
    return dict(sorted(days.items())[-400:])


def fetch_inbox(url: str, netrc_path: Path | None = None) -> list:
    body = request(url, "/api/pm-inbox", netrc_path, what="inbox")
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError, RecursionError, UnicodeDecodeError):
        raise ValueError("inbox failed: unexpected shape") from None
    if data is None:
        return []
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise ValueError("inbox failed: unexpected shape")


def save_notes(conn, minutes: dict[str, int]) -> None:
    set_setting(conn, "notes_time", json.dumps(minutes, sort_keys=True))


def notes_minutes(conn) -> dict[str, int]:
    try:
        data = json.loads(get_setting(conn, "notes_time", ""))
    except (json.JSONDecodeError, TypeError, RecursionError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    for minutes in data.values():
        if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
            return {}
    return data
