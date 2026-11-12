"""Monte Carlo deadline risk: sample each open task's true length, work the queue earliest deadline first."""
import math
import random
from dataclasses import dataclass
from datetime import date, timedelta

from pm.calibrate import Posterior, for_kind, posteriors, sample_ratio
from pm.db import get_setting
from pm.tasks import Task, finished_ratios, open_tasks

ON_TIME = 0.95


@dataclass
class TaskRisk:
    task_id: int
    p_late: float
    start_by: date
    behind: bool
    finish_p50: date | None = None
    finish_p95: date | None = None
    late_days: float = 0.0


def _days(work_min: float, cap_min: int) -> int:
    return math.ceil(max(1, round(work_min)) / cap_min)  # whole minutes, so float noise can't spill into a new day


def _finish(today: date, work_min: float, cap_min: int) -> date:
    return today + timedelta(days=_days(work_min, cap_min) - 1)


def simulate(tasks: list[Task], post: dict[str, Posterior], cap_min: int, today: date,
             n: int = 10_000, rng: random.Random | None = None) -> tuple[list[TaskRisk], float]:
    rng = rng or random.Random()
    dated = sorted((t for t in tasks if t.due), key=lambda t: (t.due, t.id))
    if not dated:
        return [], 0.0
    cums = [[] for _ in dated]
    late = [0] * len(dated)
    late_days = [0.0] * len(dated)
    any_late = 0
    for _ in range(n):
        total, run_late = 0.0, False
        for j, t in enumerate(dated):
            r = sample_ratio(for_kind(post, t.kind), rng)
            # shortcut: a task already past its sampled length keeps 10% left; fine until we model overruns
            total += max(t.est_min * r - t.logged_min, 0.1 * t.est_min)
            cums[j].append(total)
            finish = _finish(today, total, cap_min)
            if finish > t.due:
                late[j] += 1
                late_days[j] += (finish - t.due).days
                run_late = True
        any_late += run_late
    risks = []
    for j, t in enumerate(dated):
        column = sorted(cums[j])
        w = column[min(n - 1, int(ON_TIME * n))]
        start_by = t.due - timedelta(days=_days(w, cap_min) - 1)
        risks.append(TaskRisk(t.id, late[j] / n, start_by, start_by < today,
                              finish_p50=_finish(today, column[n // 2], cap_min),
                              finish_p95=_finish(today, w, cap_min),
                              late_days=late_days[j] / late[j] if late[j] else 0.0))
    return risks, any_late / n


def cap_min(conn) -> int:
    return round(float(get_setting(conn, "hours_per_day", "4")) * 60)


def forecast(conn, now, rng=None):
    tasks = open_tasks(conn, now)
    post = posteriors(finished_ratios(conn))
    risks, crunch = simulate(tasks, post, cap_min(conn), now.date(), rng=rng)
    return tasks, post, risks, crunch
