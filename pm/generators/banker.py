"""The banker's algorithm: safe orders and resource requests."""
from pm.generators import table

ID = "banker"
VERSION = 1
TITLE = "Banker's algorithm"
VARIANTS = ("safe_order", "request")
RESOURCES = "ABC"
REASONS = {"exceeds need": "the request is more than the process said it might still need",
           "wait": "the request is more than is available, so the process waits",
           "unsafe": "after granting, no safe order exists",
           "grant": "after granting, the state is still safe"}


def need(maximum: list[list[int]], alloc: list[list[int]]) -> list[list[int]]:
    return [[m - a for m, a in zip(mr, ar)] for mr, ar in zip(maximum, alloc)]


def safe_orders(alloc: list[list[int]], need: list[list[int]], avail: list[int]) -> list[list[int]]:
    found: list[list[int]] = []

    def walk(order, work):
        if len(order) == len(alloc):
            found.append(list(order))
            return
        for i in range(len(alloc)):
            if i not in order and all(n <= w for n, w in zip(need[i], work)):
                walk(order + [i], [w + a for w, a in zip(work, alloc[i])])
    walk([], list(avail))
    return found


def request(alloc, maximum, avail, pid: int, req: list[int]) -> str:
    needs = need(maximum, alloc)
    if any(r > n for r, n in zip(req, needs[pid])):
        return "exceeds need"
    if any(r > a for r, a in zip(req, avail)):
        return "wait"
    after = [list(row) for row in alloc]
    after[pid] = [a + r for a, r in zip(alloc[pid], req)]
    left = [a - r for a, r in zip(avail, req)]
    return "grant" if safe_orders(after, need(maximum, after), left) else "unsafe"


def names(order) -> str:
    return " ".join(f"P{i}" for i in order)


def vec(v) -> str:
    return "(" + ", ".join(map(str, v)) + ")"


def _tables(alloc, maximum, avail) -> str:
    rows = lambda m: [[f"P{i}", *r] for i, r in enumerate(m)]  # noqa: E731
    head = ["Process", *RESOURCES]
    return (f"Allocation:\n\n{table(head, rows(alloc))}\n\nMax:\n\n{table(head, rows(maximum))}"
            f"\n\nAvailable: {vec(avail)}")


def _walk(alloc, avail, order) -> str:
    work, lines = list(avail), []
    for i in order:
        work = [w + a for w, a in zip(work, alloc[i])]
        lines.append(f"- P{i} finishes; available becomes {vec(work)}")
    return "\n".join(lines)


def draw(rng, variant: str):
    n = 4
    alloc = [[rng.randint(0, 3) for _ in RESOURCES] for _ in range(n)]
    needs = [[rng.randint(0, 4) for _ in RESOURCES] for _ in range(n)]
    avail = [rng.randint(1, 4) for _ in RESOURCES]
    maximum = [[a + d for a, d in zip(ar, dr)] for ar, dr in zip(alloc, needs)]
    orders = safe_orders(alloc, needs, avail)
    if not 2 <= len(orders) <= 12 or list(range(n)) in orders:
        return None
    need_table = "Need:\n\n" + table(["Process", *RESOURCES], [[f"P{i}", *r] for i, r in enumerate(needs)])
    if variant == "safe_order":
        text = f"{_tables(alloc, maximum, avail)}\n\nIs this state safe? Give one safe order of the processes."
        steps = (f"{need_table}\n\nOne safe order, {names(orders[0])}:\n\n{_walk(alloc, avail, orders[0])}"
                 f"\n\n{len(orders)} safe orders in all.")
        return text, "sequence", {"accept": [[f"P{i}" for i in o] for o in orders]}, steps
    tries = []
    for _ in range(4):
        pid = rng.randrange(n)
        req = [rng.randint(0, d) for d in needs[pid]]
        if any(req):
            tries.append((pid, req, request(alloc, maximum, avail, pid, req)))
    want = rng.choice(("grant", "deny"))
    picked = [t for t in tries if (t[2] == "grant") == (want == "grant")]
    if not picked:
        return None
    pid, req, outcome = picked[0]
    text = (f"{_tables(alloc, maximum, avail)}\n\nP{pid} requests {vec(req)}. "
            "Should the request be granted? Answer grant or deny.")
    steps = f"{need_table}\n\n{'Grant' if outcome == 'grant' else 'Deny'}: {REASONS[outcome]}."
    if outcome == "grant":
        after = [list(r) for r in alloc]
        after[pid] = [a + r for a, r in zip(alloc[pid], req)]
        left = [a - r for a, r in zip(avail, req)]
        order = safe_orders(after, need(maximum, after), left)[0]
        steps += f"\n\nAvailable after granting: {vec(left)}. A safe order, {names(order)}:\n\n{_walk(after, left, order)}"
    return text, "token", {"value": "grant" if outcome == "grant" else "deny"}, steps
