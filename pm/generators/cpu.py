"""CPU scheduling: FCFS, SJF, SRTF and round robin."""
from collections import deque

from pm.generators import table

ID = "cpu"
VERSION = 1
TITLE = "CPU scheduling"
VARIANTS = ("avg_wait", "order", "which")
POLICIES = ("fcfs", "sjf", "srtf", "rr")
CONVENTION = ("Waiting time is completion minus arrival minus burst. "
              "Ties go to the process that arrived first, then to the lower number.")
RR_RULE = "A process that arrives at the instant a quantum ends joins the queue before the preempted process."


def _add(gantt, name, start, end):
    if gantt and gantt[-1][0] == name and gantt[-1][2] == start:
        gantt[-1] = (name, gantt[-1][1], end)
    else:
        gantt.append((name, start, end))


def schedule(procs: list[tuple[str, int, int]], policy: str, quantum: int | None = None) -> list[tuple[str, int, int]]:
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r}")
    if policy == "rr" and (quantum is None or quantum < 1):
        raise ValueError("round robin needs a quantum")
    n = len(procs)
    rem = [b for _, _, b in procs]
    first = sorted(range(n), key=lambda i: (procs[i][1], i))
    gantt: list = []
    t = 0
    if policy == "rr":
        queue, k = deque(), 0

        def admit(upto):
            nonlocal k
            while k < n and procs[first[k]][1] <= upto:
                queue.append(first[k])
                k += 1
        admit(0)
        while any(rem):
            if not queue:
                t = max(t, procs[first[k]][1])
                admit(t)
                continue
            i = queue.popleft()
            run = min(quantum, rem[i])
            _add(gantt, procs[i][0], t, t + run)
            t += run
            rem[i] -= run
            admit(t)
            if rem[i]:
                queue.append(i)
        return gantt
    current = None
    while any(rem):
        ready = [i for i in range(n) if procs[i][1] <= t and rem[i]]
        if not ready:
            t = min(procs[i][1] for i in range(n) if rem[i])
            continue
        if policy == "fcfs":
            pick = min(ready, key=lambda i: (procs[i][1], i))
        elif policy == "sjf":
            pick = min(ready, key=lambda i: (procs[i][2], procs[i][1], i))
        else:
            pick = min(ready, key=lambda i: (rem[i], procs[i][1], i))
            if current in ready and rem[current] <= rem[pick]:
                pick = current  # preempt only for a strictly shorter remaining time
        if policy == "srtf":
            _add(gantt, procs[pick][0], t, t + 1)
            t += 1
            rem[pick] -= 1
            current = pick
        else:
            _add(gantt, procs[pick][0], t, t + rem[pick])
            t += rem[pick]
            rem[pick] = 0
    return gantt


def waits(procs: list[tuple[str, int, int]], gantt: list[tuple[str, int, int]]) -> dict[str, int]:
    done = {}
    for name, _, end in gantt:
        done[name] = max(done.get(name, 0), end)
    return {name: done[name] - arrival - burst for name, arrival, burst in procs}


def finish_order(gantt) -> list[str]:
    last = {}
    for name, _, end in gantt:
        last[name] = end
    return sorted(last, key=last.get)


def chart(gantt) -> str:
    parts, t = [], 0
    for name, start, end in gantt:
        if start > t:
            parts.append(f"idle {t}–{start}")
        parts.append(f"{name} {start}–{end}")
        t = end
    return " | ".join(parts)


def _name(policy, quantum) -> str:
    return f"round robin (quantum {quantum})" if policy == "rr" else policy.upper()


def _steps(procs, policy, quantum) -> str:
    gantt = schedule(procs, policy, quantum)
    w = waits(procs, gantt)
    lines = [f"{_name(policy, quantum)}: {chart(gantt)}", ""]
    lines += [f"- {name} waits {w[name]}" for name, _, _ in procs]
    mean = sum(w.values()) / len(w)
    lines += ["", f"Average waiting time: {sum(w.values())} / {len(w)} = {mean:.2f}"]
    return "\n".join(lines)


def draw(rng, variant: str):
    procs = [("P1", 0, rng.randint(2, 9))] + [(f"P{i}", rng.randint(0, 6), rng.randint(2, 9)) for i in (2, 3, 4)]
    quantum = rng.randint(2, 4)
    head = table(["Process", "Arrival", "Burst"], [list(p) for p in procs])
    if variant == "which":
        charts = {p: schedule(procs, p) for p in ("fcfs", "sjf", "srtf")}
        if len({tuple(c) for c in charts.values()}) < 3:
            return None
        policy = rng.choice(("fcfs", "sjf", "srtf"))
        text = (f"{head}\n\n{chart(charts[policy])}\n\nWhich policy produced this: FCFS, SJF or SRTF?"
                f"\n\n{CONVENTION}")
        return text, "token", {"value": policy.upper()}, _steps(procs, policy, None)
    policy = rng.choice(POLICIES)
    q = quantum if policy == "rr" else None
    gantt = schedule(procs, policy, q)
    if policy in ("srtf", "rr") and all(a == 0 for _, a, _ in procs):
        return None
    if policy == "srtf" and len(gantt) == len({g[0] for g in gantt}):
        return None
    if policy == "rr" and all(b <= quantum for _, _, b in procs):
        return None
    rules = CONVENTION + (" " + RR_RULE if policy == "rr" else "")
    if variant == "avg_wait":
        w = waits(procs, gantt)
        question = f"What is the average waiting time under {_name(policy, q)}? Give it to 2 decimal places."
        kind, key = "number", {"value": round(sum(w.values()) / len(w), 2), "tol": 0.005}
    else:
        question = f"In what order do the processes finish under {_name(policy, q)}?"
        kind, key = "sequence", {"value": finish_order(gantt)}
    return f"{head}\n\n{question}\n\n{rules}", kind, key, _steps(procs, policy, q)
