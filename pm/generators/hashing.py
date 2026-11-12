"""Hashing with open addressing: linear and quadratic probing."""
ID = "hashing"
VERSION = 1
TITLE = "Hashing with open addressing"
VARIANTS = ("table", "probes")
RULES = {"linear": "The i-th probe looks at (h + i) mod m", "quadratic": "The i-th probe looks at (h + i²) mod m"}


def _place(table, key: int, m: int, probing: str) -> list[int]:
    tried = []
    for i in range(m):
        slot = (key % m + (i if probing == "linear" else i * i)) % m
        tried.append(slot)
        if table[slot] is None:
            table[slot] = key
            return tried
    raise ValueError(f"no free slot for {key}")


def insert_all(keys: list[int], m: int, probing: str) -> tuple[list[int | None], int]:
    if probing not in RULES:
        raise ValueError(f"unknown probing {probing!r}")
    table: list[int | None] = [None] * m
    return table, sum(len(_place(table, k, m, probing)) for k in keys)


def draw(rng, variant: str):
    m = rng.choice((7, 11, 13))
    keys = rng.sample(range(1, 100), m - rng.choice((3, 2)))
    probing = rng.choice(tuple(RULES))
    try:
        table, total = insert_all(keys, m, probing)
    except ValueError:
        return None
    if total < len(keys) + 2:
        return None
    text = (f"Table size {m}, h(k) = k mod {m}, {probing} probing. "
            f"Insert in this order: {', '.join(map(str, keys))}")
    if variant == "table":
        question, kind, key = (f"Give the table from slot 0 to slot {m - 1}, writing - for an empty slot.",
                               "sequence", {"value": ["-" if v is None else str(v) for v in table]})
    else:
        question, kind, key = "How many probes do the insertions take in total?", "number", {"value": total, "tol": 0}
    lines, scratch = [], [None] * m
    for k in keys:
        tried = _place(scratch, k, m, probing)
        lines.append(f"- {k}: h = {k % m}; tried {', '.join(map(str, tried))} → slot {tried[-1]}"
                     f" ({len(tried)} {'probe' if len(tried) == 1 else 'probes'})")
    shown = " ".join("-" if v is None else str(v) for v in table)
    steps = "\n".join(lines) + f"\n\nTable: {shown}\n\nTotal probes: {total}"
    return (f"{text}\n\n{question}\n\n{RULES[probing]}. A probe is one slot looked at, the home slot included.",
            kind, key, steps)
