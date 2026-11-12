"""How your rated sessions spread over the clock, and which three hours look best."""
from datetime import datetime, timedelta

from pm.tasks import LONG_SESSION_MIN

MIN_SESSIONS = 10
MIN_MINUTES = 300
WIDTH = 3


def _rated(conn) -> list[tuple[datetime, datetime, int]]:
    out = []
    for row in conn.execute("SELECT start, end, energy FROM sessions"
                            " WHERE end IS NOT NULL AND energy IS NOT NULL"):
        start, end = datetime.fromisoformat(row["start"]), datetime.fromisoformat(row["end"])
        if timedelta(0) < end - start <= timedelta(minutes=LONG_SESSION_MIN):
            out.append((start, end, row["energy"]))
    return out


def _by_hour(sessions) -> dict[int, tuple[float, float]]:
    weighted: dict[int, float] = {}
    minutes: dict[int, float] = {}
    for start, end, energy in sessions:
        at = start
        while at < end:
            next_hour = at.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            stop = min(end, next_hour)
            m = (stop - at).total_seconds() / 60
            weighted[at.hour] = weighted.get(at.hour, 0.0) + energy * m
            minutes[at.hour] = minutes.get(at.hour, 0.0) + m
            at = stop
    return {h: (weighted[h] / minutes[h], minutes[h]) for h in sorted(minutes) if minutes[h] > 0}


def by_hour(conn) -> dict[int, tuple[float, float]]:
    """Clock hour -> (minute-weighted mean energy, rated minutes); sessions over LONG_SESSION_MIN are left out."""
    return _by_hour(_rated(conn))


def suggest(conn) -> str | None:
    sessions = _rated(conn)
    if len(sessions) < MIN_SESSIONS:
        return None
    hours = _by_hour(sessions)
    best = None
    for start in range(0, 24 - WIDTH + 1):
        if start not in hours:
            continue
        span = [hours[h] for h in range(start, start + WIDTH) if h in hours]
        total = sum(m for _, m in span)
        if total < MIN_MINUTES:
            continue
        score = sum(mean * m for mean, m in span) / total
        key = (round(score, 9), total, -start)  # float noise must not break a tie
        if best is None or key > best[0]:
            best = (key, start)
    if best is None:
        return None
    start = best[1]
    return f"{start:02d}-{start + WIDTH:02d}"
