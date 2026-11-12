"""Disk scheduling: FCFS, SSTF, SCAN, C-SCAN, LOOK and C-LOOK."""
ID = "disk"
VERSION = 1
TITLE = "Disk scheduling"
VARIANTS = ("movement", "order")
POLICIES = ("fcfs", "sstf", "scan", "cscan", "look", "clook")
NAMES = {"fcfs": "FCFS", "sstf": "SSTF", "scan": "SCAN", "cscan": "C-SCAN", "look": "LOOK", "clook": "C-LOOK"}
CONVENTION = ("SCAN and C-SCAN go to the end of the disk before turning; LOOK and C-LOOK turn at the last request. "
              "The return sweep of C-SCAN and C-LOOK counts as movement. SSTF ties go to the lower cylinder.")


def path(queue: list[int], head: int, policy: str, up: bool = True, size: int = 200) -> tuple[list[int], list[int]]:
    """The requests in service order, and every cylinder the head stops at (turns and jumps included)."""
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r}")
    if policy == "fcfs":
        return list(queue), list(queue)
    if policy == "sstf":
        left, order, pos = list(queue), [], head
        while left:
            nxt = min(left, key=lambda c: (abs(c - pos), c))
            left.remove(nxt)
            order.append(nxt)
            pos = nxt
        return order, list(order)
    ahead = sorted((c for c in queue if (c >= head if up else c <= head)), reverse=not up)
    behind = sorted((c for c in queue if (c < head if up else c > head)), reverse=not up)
    end, other = (size - 1, 0) if up else (0, size - 1)
    stops = list(ahead)
    if policy in ("scan", "look"):
        back = behind[::-1]
        if back and policy == "scan" and stops[-1:] != [end]:
            stops.append(end)
        return ahead + back, stops + back
    if behind and policy == "cscan":
        stops += ([end] if stops[-1:] != [end] else []) + [other]
    return ahead + behind, stops + behind


def service(queue: list[int], head: int, policy: str, up: bool = True, size: int = 200) -> tuple[list[int], int]:
    order, stops = path(queue, head, policy, up, size)
    total, pos = 0, head
    for c in stops:
        total += abs(c - pos)
        pos = c
    return order, total


def _steps(queue, head, policy, up) -> str:
    order, stops = path(queue, head, policy, up)
    lines, pos, total = [], head, 0
    served = set(order)
    for c in stops:
        note = "" if c in served else " (jump)" if abs(c - pos) == 199 else " (end of the disk)"
        lines.append(f"- {pos} → {c}: {abs(c - pos)}{note}")
        total += abs(c - pos)
        pos = c
    return f"{NAMES[policy]}:\n\n" + "\n".join(lines) + f"\n\nTotal head movement: {total}"


def draw(rng, variant: str):
    queue = rng.sample(range(200), 8)
    head = rng.randint(20, 180)
    up = rng.random() < 0.5
    policy = rng.choice(POLICIES)
    if head in queue or sum(c < head for c in queue) < 2 or sum(c > head for c in queue) < 2:
        return None
    order, total = service(queue, head, policy, up)
    text = (f"Cylinders 0–199. Head at {head}, moving toward {199 if up else 0}. "
            f"Queue: {', '.join(map(str, queue))}")
    if variant == "movement":
        question, kind, key = (f"What is the total head movement under {NAMES[policy]}, in cylinders?",
                               "number", {"value": total, "tol": 0})
    else:
        question, kind, key = (f"In what order are the requests served under {NAMES[policy]}?",
                               "sequence", {"value": [str(c) for c in order]})
    return f"{text}\n\n{question}\n\n{CONVENTION}", kind, key, _steps(queue, head, policy, up)
