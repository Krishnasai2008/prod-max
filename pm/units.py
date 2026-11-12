import re
from datetime import date, timedelta

_DURATION = re.compile(r"^(?:(\d+(?:\.\d+)?)h)?(?:(\d+)m)?$")
MAX_MINUTES = 1000 * 60  # bigger is a typo (a date in the estimate box) and would push the forecast past year 9999
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MAX_DAYS = 3660  # due dates within ten years of today, for the same reason


def parse_duration(s: str) -> int:
    """'90m', '4h', '1h30m' or '2.5h' -> minutes. A bare number is refused: 90 could mean minutes or hours."""
    s = s.strip()
    if len(s) > 20:
        raise ValueError(f"bad duration {s[:20]!r}... (try 90m, 4h, 1h30m)")
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        raise ValueError(f"give a unit: {s}m or {s}h")
    m = _DURATION.match(s)
    if not s or not m:
        raise ValueError(f"bad duration {s!r} (try 90m, 4h, 1h30m)")
    minutes = round(float(m[1] or 0) * 60) + int(m[2] or 0)
    if minutes <= 0:
        raise ValueError(f"duration must be positive: {s!r}")
    if minutes > MAX_MINUTES:
        raise ValueError(f"duration too long: {s!r} (at most 1000h)")
    return minutes


def fmt_duration(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    if h and m:
        return f"{h}h{m}m"
    return f"{h}h" if h else f"{m}m"


def parse_due(s: str, today: date) -> date:
    """'YYYY-MM-DD', '+N' days from today, 'today', 'tomorrow', or a weekday ('fri': the next one after today)."""
    word = s.strip().lower()
    if re.fullmatch(r"\+\d{1,6}", s):
        when = today + timedelta(days=int(s[1:]))
    elif word in ("today", "tomorrow"):
        when = today + timedelta(days=word == "tomorrow")
    elif len(word) >= 3 and any(day.startswith(word) for day in _WEEKDAYS):
        target = next(i for i, day in enumerate(_WEEKDAYS) if day.startswith(word))
        when = today + timedelta(days=(target - today.weekday() - 1) % 7 + 1)
    else:
        try:
            when = date.fromisoformat(s)
        except ValueError:
            raise ValueError(f"bad date {s[:40]!r} (try 2026-11-20, +3 or fri)") from None
    if abs((when - today).days) > MAX_DAYS:
        raise ValueError(f"due date must be within ten years: {s!r}")
    return when
