import math
from datetime import date

from pm.calibrate import Posterior, for_kind, median_ratio
from pm.risk import TaskRisk
from pm.tasks import Task


def plan_day(tasks: list[Task], risks: dict[int, TaskRisk], post: dict[str, Posterior],
             cap_min: int) -> list[tuple[Task, int]]:
    """Fill today's capacity earliest deadline first (the order risk.simulate assumes); deep before shallow."""
    def urgency(t: Task):
        return (t.due or date.max, t.id)  # exactly simulate's order; its start-by dates assume it

    plan, left = [], cap_min
    for t in sorted(tasks, key=urgency):
        if left <= 0:
            break
        remaining = max(round(t.est_min * median_ratio(for_kind(post, t.kind)) - t.logged_min),
                        math.ceil(0.1 * t.est_min))
        minutes = min(remaining, left)
        plan.append((t, minutes))
        left -= minutes
    return sorted(plan, key=lambda p: p[0].energy != "deep")
