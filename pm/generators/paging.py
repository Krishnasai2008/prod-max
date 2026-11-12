"""Page replacement: FIFO, LRU and OPT."""
from pm.generators import table

ID = "paging"
VERSION = 1
TITLE = "Page replacement"
VARIANTS = ("count", "final", "fewest")
NAMES = {"fifo": "FIFO", "lru": "LRU", "opt": "OPT"}
CONVENTION = "The frames start empty, and the first load of each page counts as a fault."
OPT_RULE = "OPT evicts the page used furthest in the future; a page never used again goes first."


def run(refs: list[int], frames: int, policy: str) -> tuple[int, list[int], list[tuple[int, list[int], bool]]]:
    if policy not in NAMES:
        raise ValueError(f"unknown policy {policy!r}")
    slots: list[int] = []
    loaded: dict[int, int] = {}
    used: dict[int, int] = {}
    faults = 0
    rows = []
    for i, page in enumerate(refs):
        fault = page not in slots
        if fault:
            faults += 1
            if len(slots) < frames:
                slots.append(page)
            else:
                if policy == "fifo":
                    victim = min(slots, key=lambda p: loaded[p])
                elif policy == "lru":
                    victim = min(slots, key=lambda p: used[p])
                else:
                    def next_use(p):
                        for j in range(i + 1, len(refs)):
                            if refs[j] == p:
                                return (0, -j)
                        return (-1, loaded[p])  # never used again: these go first, earliest loaded first
                    victim = min(slots, key=next_use)
                slots[slots.index(victim)] = page
            loaded[page] = i
        used[page] = i
        rows.append((page, list(slots), fault))
    return faults, list(slots), rows


def _steps(refs, frames, policy) -> str:
    faults, _, rows = run(refs, frames, policy)
    body = table(["Ref", "Frames", "Fault"],
                 [[p, " ".join(map(str, s)), "F" if f else ""] for p, s, f in rows])
    return f"{NAMES[policy]}:\n\n{body}\n\nFaults: {faults}"


def draw(rng, variant: str):
    frames = rng.choice((3, 4))
    refs = [rng.randrange(frames + 4) for _ in range(12)]
    policy = rng.choice(tuple(NAMES)) if variant != "fewest" else None
    counts = {p: run(refs, frames, p)[0] for p in NAMES}
    if len(set(counts.values())) == 1:
        return None
    head = f"Frames: {frames}. Reference string: {' '.join(map(str, refs))}"
    if variant == "fewest":
        if counts["fifo"] == counts["lru"] or min(counts["fifo"], counts["lru"]) < frames + 2:
            return None
        best = "FIFO" if counts["fifo"] < counts["lru"] else "LRU"
        text = f"{head}\n\nWhich gives fewer page faults here, FIFO or LRU?\n\n{CONVENTION}"
        steps = f"{_steps(refs, frames, 'fifo')}\n\n{_steps(refs, frames, 'lru')}\n\n{best} gives fewer faults."
        return text, "token", {"value": best}, steps
    if counts[policy] < frames + 2:
        return None
    name = NAMES[policy]
    rules = CONVENTION + (" " + OPT_RULE if policy == "opt" else "")
    if variant == "count":
        question, kind, key = f"How many page faults occur under {name}?", "number", {"value": counts[policy], "tol": 0}
    else:
        final = run(refs, frames, policy)[1]
        question, kind, key = (f"Which pages are in memory at the end under {name}?", "set",
                               {"value": [str(p) for p in sorted(final)]})
    return f"{head}\n\n{question}\n\n{rules}", kind, key, _steps(refs, frames, policy)
