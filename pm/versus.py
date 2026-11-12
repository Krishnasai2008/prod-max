"""The versus scoreboard: a numbers-only card per player, synced through one hub site, scored the same everywhere.

Cards from the hub are other people's data: `parse` keeps only well-formed numbers, and scoring never raises.
"""
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path

from pm.db import get_setting, set_setting
from pm.study import mastery, topics
from pm.tasks import _minutes

CARD_DAYS = 400  # shortcut: the tally is recomputed from the cards, so it covers 400 days; store results if a season outlives that
CACHE = "versus_cards"  # internal: the hub's last reply, so the board works offline
CATEGORIES = (("min", "minutes studied"), ("reviews", "reviews done"), ("quiz", "quiz answers right"),
              ("test", "test answers right"), ("syllabus", "syllabus gained"))
COUNTS = {"min": 1440, "reviews": 100_000, "quiz": 100_000, "test": 100_000}  # the most a day can honestly hold
MAX_PLAYERS, MAX_NAME, RECENT = 50, 40, 14
PENALTY_MIN = 30  # a day with this many minutes or fewer costs the player a point of overall score


def syllabus(conn, now: datetime) -> float | None:
    """Mean topic mastery in percent; None with no topics."""
    values = [mastery(conn, t.id, now) for t in topics(conn)]
    return round(100 * sum(values) / len(values), 1) if values else None


def card(conn, now: datetime) -> dict:
    """This player's numbers per day. Records today's syllabus, so a day's gain can be read later."""
    today = now.date()
    lo = (today - timedelta(days=CARD_DAYS - 1)).isoformat()
    level = syllabus(conn, now)
    if level is not None:
        conn.execute("INSERT INTO versus_days(day, syllabus) VALUES(?, ?)"
                     " ON CONFLICT(day) DO UPDATE SET syllabus=excluded.syllabus", (today.isoformat(), level))
        conn.commit()
    days: dict[str, dict] = {}

    def add(day: str, key: str, n) -> None:
        if lo <= day <= today.isoformat():
            cell = days.setdefault(day, {"min": 0, "reviews": 0, "quiz": 0, "test": 0})
            cell[key] = cell.get(key, 0) + n

    # the same rule as stats._days: a session counts on the day it started
    for s in conn.execute("SELECT start, end FROM sessions"):
        start = datetime.fromisoformat(s["start"])
        add(start.date().isoformat(), "min", _minutes(start, datetime.fromisoformat(s["end"]) if s["end"] else now))
    for r in conn.execute("SELECT substr(ts, 1, 10) AS day, source, count(*) AS n, sum(correct = 1) AS right"
                          " FROM evidence_v WHERE ts IS NOT NULL GROUP BY day, source"):
        if r["source"] == "review":
            add(r["day"], "reviews", r["n"])
        else:
            add(r["day"], "test" if r["source"] == "test" else "quiz", r["right"] or 0)
    for r in conn.execute("SELECT day, syllabus FROM versus_days"):
        add(r["day"], "syllabus", r["syllabus"])
    for cell in days.values():
        cell["min"] = min(cell["min"], COUNTS["min"])
    return {"version": 1, "generated": now.isoformat(timespec="seconds"),
            "days": dict(sorted((d, c) for d, c in days.items() if any(c.values())))}


def _day(key, cell) -> dict | None:
    try:
        date.fromisoformat(key)
    except (TypeError, ValueError):
        return None
    if not isinstance(cell, dict) or len(key) != 10:
        return None
    out = {}
    for name, top in COUNTS.items():
        n = cell.get(name, 0)
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= top:
            return None
        out[name] = n
    level = cell.get("syllabus")
    if level is not None:
        if isinstance(level, bool) or not isinstance(level, (int, float)) or not math.isfinite(level) \
                or not 0 <= level <= 100:
            return None
        out["syllabus"] = float(level)
    return out


def _card(data) -> dict | None:
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("days"), dict):
        return None
    try:
        generated = datetime.fromisoformat(data["generated"])
    except (KeyError, TypeError, ValueError):
        return None
    if generated.tzinfo is not None or len(data["days"]) > CARD_DAYS:
        return None
    days = {key: day for key, cell in data["days"].items() if (day := _day(key, cell)) is not None}
    return {"generated": generated.isoformat(timespec="seconds"), "days": dict(sorted(days.items()))}


def parse(data) -> tuple[str | None, dict[str, dict]]:
    """(who the hub says we are, the usable cards by player). A card or a day that isn't well-formed is left out."""
    if not isinstance(data, dict) or not isinstance(data.get("cards"), dict):
        raise ValueError("the scoreboard's reply is not a set of cards")
    cards = {}
    for name, raw in list(data["cards"].items())[:MAX_PLAYERS]:
        if 0 < len(name) <= MAX_NAME and name.isprintable() and (good := _card(raw)) is not None:
            cards[name] = good
    you = data.get("you")
    return (you if isinstance(you, str) and you in cards else None), dict(sorted(cards.items()))


def _values(cards: dict[str, dict], day: str) -> dict[str, dict]:
    """Each player's five numbers for a day; syllabus is the gain over their last recorded day before it."""
    out = {}
    for name, c in cards.items():
        cell = c["days"].get(day, {})
        gain = 0.0
        if "syllabus" in cell:
            before = [v["syllabus"] for d, v in c["days"].items() if d < day and "syllabus" in v]
            gain = round(cell["syllabus"] - before[-1], 1) if before else 0.0
        out[name] = {**{k: cell.get(k, 0) for k in COUNTS}, "syllabus": gain}
    return out


def _score(cards: dict[str, dict], day: str) -> dict:
    values = _values(cards, day)
    points = dict.fromkeys(cards, 0)
    rows = []
    for key, label in CATEGORIES:
        col = {name: v[key] for name, v in values.items()}
        top = max(col.values(), default=0)
        ahead = [name for name, n in col.items() if n == top]
        leader = ahead[0] if top > 0 and len(ahead) == 1 else None  # a point needs a sole leader with something done
        if leader:
            points[leader] += 1
        rows.append({"key": key, "label": label, "values": col, "leader": leader})
    best = max(points.values(), default=0)
    first = [name for name, n in points.items() if n == best]
    leader = first[0] if best > 0 and len(first) == 1 else None
    played = any(n > 0 for row in rows for n in row["values"].values())  # a day nobody studied is not a draw
    slack = [name for name, v in values.items() if v["min"] <= PENALTY_MIN]
    return {"day": day, "rows": rows, "points": points, "leader": leader, "draw": leader is None and played,
            "penalty": slack}


def board(cards: dict[str, dict], you: str | None, today: date) -> dict:
    """Today so far, and the tally over every final day. A day is final once every card was made after it ended.

    Overall score: +1 for a day won, -1 for a penalty day (a final day with PENALTY_MIN minutes or less), never below 0.
    """
    tally, draws, recent, streak = dict.fromkeys(cards, 0), 0, [], None
    penalties, score = dict.fromkeys(cards, 0), dict.fromkeys(cards, 0)
    firsts = [min(c["days"]) for c in cards.values() if c["days"]]
    if len(cards) > 1 and len(firsts) == len(cards):
        # shortcut: days are each player's local dates, and a new player moves the start for everyone; store results if either matters
        day = date.fromisoformat(max(firsts))  # count from the first day everyone had started
        end = min(min(date.fromisoformat(c["generated"][:10]) for c in cards.values()), today)
        day = max(day, end - timedelta(days=CARD_DAYS))
        open_streak = True
        finals = []
        while day < end:
            finals.append(_score(cards, day.isoformat()))
            day += timedelta(days=1)
        for s in finals:  # oldest first: a win adds a point, a penalty day takes one, and the score stops at zero
            if s["leader"]:
                score[s["leader"]] += 1
            for name in s["penalty"]:
                score[name] = max(0, score[name] - 1)
        for s in reversed(finals):
            if s["leader"]:
                tally[s["leader"]] += 1
            draws += s["draw"]
            for name in s["penalty"]:
                penalties[name] += 1
            if len(recent) < RECENT:
                recent.append({"day": s["day"], "winner": s["leader"], "points": s["points"],
                               "penalty": s["penalty"]})
            if open_streak and s["leader"] and (streak is None or streak["name"] == s["leader"]):
                streak = {"name": s["leader"], "days": (streak["days"] if streak else 0) + 1}
            else:
                open_streak = False
    return {"you": you, "players": list(cards), "today": _score(cards, today.isoformat()), "tally": tally,
            "draws": draws, "streak": streak, "recent": recent, "penalties": penalties,
            "score": score,
            "synced": {name: c["generated"] for name, c in cards.items()}}


def sync(conn, now: datetime, url: str, netrc_path: Path | None = None) -> int:
    """Send this player's card to the hub and keep everyone's; returns how many players the hub holds."""
    from pm.stats import request  # stats imports this module for the push
    request(url, "/api/versus", netrc_path, method="PUT", body=json.dumps(card(conn, now)).encode(),
            what="versus")
    reply = request(url, "/api/versus", netrc_path, what="versus")
    try:
        data = json.loads(reply)
    except ValueError:
        raise ValueError("the scoreboard's reply is not JSON") from None
    _, cards = parse(data)
    set_setting(conn, CACHE, json.dumps(data))
    return len(cards)


def cached(conn, today: date) -> dict | None:
    """The board from the last sync; None before the first one."""
    try:
        you, cards = parse(json.loads(get_setting(conn, CACHE, "null")))
    except ValueError:
        return None
    return board(cards, you, today) if cards else None


def text(b: dict) -> list[str]:
    """The board as lines for the terminal."""
    def who(name: str) -> str:
        return "you" if name == b["you"] else name

    players = b["players"]
    width = max([6, *(len(who(p)) for p in players)]) + 2
    lines = [f"versus · {b['today']['day']} (live)",
             " " * 20 + "".join(who(p).rjust(width) for p in players)]
    for row in b["today"]["rows"]:
        cells = (f"{row['values'][p]:+.1f}" if row["key"] == "syllabus" else str(row["values"][p]) for p in players)
        lines.append(row["label"].ljust(20) + "".join(c.rjust(width) for c in cells)
                     + (f"  {who(row['leader'])}" if row["leader"] else ""))
    lines.append("today: " + " · ".join(f"{who(p)} {b['today']['points'][p]}" for p in players))
    if len(players) < 2:
        lines.append("waiting for another player")
        return lines
    lines.append("wins: " + " · ".join(f"{who(p)} {b['tally'][p]}" for p in players) + f" · draws {b['draws']}")
    lines.append(f"days of {PENALTY_MIN}m or less: " + " · ".join(f"{who(p)} {b['penalties'][p]}" for p in players))
    lines.append("score: " + " · ".join(f"{who(p)} {b['score'][p]}" for p in players))
    if b["streak"]:
        n = b["streak"]["days"]
        lines.append(f"streak: {who(b['streak']['name'])}, {n} day{'' if n == 1 else 's'}")
    return lines
