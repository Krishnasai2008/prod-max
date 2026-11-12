"""Once-a-day start nudges for tasks that are due to begin."""
import json
import shutil
import subprocess
import sys
from datetime import datetime

from pm.db import get_setting, set_setting
from pm.risk import TaskRisk
from pm.tasks import Task, worked_on


def _window(conn) -> tuple[int, int] | None:
    value = get_setting(conn, "nudge_hours", "08-22")
    try:
        lo, hi = (int(part) for part in value.split("-"))
    except ValueError:
        return None
    return (lo, hi) if 0 <= lo < hi <= 24 else None


def due(conn, now: datetime, tasks: list[Task], risks: list[TaskRisk]) -> list[str]:
    window = _window(conn)
    if window is None or not window[0] <= now.hour < window[1]:
        return []
    today = now.date().isoformat()
    try:
        nudged = json.loads(get_setting(conn, "nudged", "{}"))
    except ValueError:
        nudged = {}
    by_id = {task.id: task for task in tasks}
    messages = []
    for risk in risks:
        task = by_id.get(risk.task_id)
        if task is None or risk.start_by > now.date():
            continue
        if nudged.get(str(task.id)) == today or worked_on(conn, task.id, now.date()):
            continue
        percent = round(risk.p_late * 100)
        if risk.behind:
            messages.append(f"behind on #{task.id} {task.title}: {percent}% late risk, due {task.due}")
        else:
            messages.append(f"start #{task.id} {task.title} today: {percent}% late risk, due {task.due}")
        nudged[str(task.id)] = today
    if messages:
        set_setting(conn, "nudged", json.dumps(nudged))
    return messages


def _notify(message: str) -> list[str] | None:
    if sys.platform == "darwin":
        exe = shutil.which("osascript")  # the message is an argument, never part of the script
        return exe and [exe, "-e", "on run argv", "-e",
                        'display notification (item 1 of argv) with title "pm"', "-e", "end run", message]
    exe = shutil.which("notify-send")
    return exe and [exe, "-a", "pm", "pm", message]


def send(messages: list[str]) -> None:
    for message in messages:
        argv = _notify(message)
        if argv:
            try:
                subprocess.run(argv)
            except (OSError, subprocess.SubprocessError):
                pass
        print(f"nudge: {message}", flush=True)
