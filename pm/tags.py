import re

TAG = re.compile(r"^[a-z0-9][a-z0-9-]*$")

_SKIP = ("diff ", "index ", "--- ", "+++ ")
_SWAP = {"<": "<=", "<=": "<", ">": ">=", ">=": ">"}
_PLUS_MINUS_ONE = re.compile(r"\s*[+-]\s*1\b")


def _collapse(line: str) -> str:
    return " ".join(line.split())


def _parse(diff: str) -> tuple[list[tuple[str, str]], list[str]]:
    pairs: list[tuple[str, str]] = []
    added_all: list[str] = []
    removed: list[str] = []
    added: list[str] = []

    def flush() -> None:
        pairs.extend(zip(removed, added))
        added_all.extend(added)
        removed.clear()
        added.clear()

    for raw in diff.splitlines():
        if raw.startswith(_SKIP) or raw.startswith("@@"):
            flush()
        elif raw.startswith("-"):
            if added:
                flush()
            removed.append(_collapse(raw[1:]))
        elif raw.startswith("+"):
            added.append(_collapse(raw[1:]))
        else:
            flush()
    flush()
    return pairs, added_all


def _swaps(line: str) -> list[str]:
    if len(line) > 500:  # minified code: a copy per < would eat memory, and it is no off-by-one fix anyway
        return []
    out = []
    for m in re.finditer(r"<=|>=|<|>", line):
        out.append(line[:m.start()] + _SWAP[m.group()] + line[m.end():])
    return out


def _off_by_one_pair(removed: str, added: str) -> bool:
    if added in _swaps(removed) or removed in _swaps(added):
        return True
    rparts = re.split(r"(\d+)", removed)
    aparts = re.split(r"(\d+)", added)
    if len(rparts) == len(aparts) and all(rparts[i] == aparts[i] for i in range(0, len(rparts), 2)):
        changed = [(int(rparts[i]), int(aparts[i])) for i in range(1, len(rparts), 2)
                   if rparts[i] != aparts[i]]
        if len(changed) == 1 and abs(changed[0][0] - changed[0][1]) == 1:
            return True
    for m in _PLUS_MINUS_ONE.finditer(removed):
        if removed[:m.start()] + removed[m.end():] == added:
            return True
    for m in _PLUS_MINUS_ONE.finditer(added):
        if added[:m.start()] + added[m.end():] == removed:
            return True
    return False


def _overflow_pair(removed: str, added: str) -> bool:
    if re.search(r"\bint\b", removed) and re.search(r"long long|int64_t|uint64_t|__int128|\blong\b", added):
        return True
    return bool(re.search(r"\d+(?:LL|ll)\b", added) and not re.search(r"\d+(?:LL|ll)\b", removed))


def _uninit_pair(removed: str, added: str) -> bool:
    stem = removed[:-1] if removed.endswith(";") else removed
    if not added.startswith(stem):
        return False
    rest = added[len(stem):]
    return bool(re.fullmatch(r"\s*(=\s*[^;]+|\{[^}]*\})\s*;\s*", rest))


def _null_check(added: str) -> bool:
    return bool(re.search(r"(==|!=)\s*(NULL|nullptr|null)\b|\bis (not )?None\b", added))


def _bounds(added: str) -> bool:
    return bool(re.search(r"\b(if|while)\b.*(\.size\(\)|\blen\(|\.length\b)", added))


RULES = [
    ("off-by-one", _off_by_one_pair, None),
    ("overflow", _overflow_pair, None),
    ("uninit", _uninit_pair, None),
    ("null-check", None, _null_check),
    ("bounds", None, _bounds),
]


def suggest(diff: str, codes: list[int]) -> list[str]:
    pairs, added = _parse(diff or "")
    tags = {tag for tag, pair_rule, added_rule in RULES
            if (pair_rule and any(pair_rule(r, a) for r, a in pairs))
            or (added_rule and any(added_rule(a) for a in added))}
    if -11 in codes or 139 in codes:
        tags.add("segfault")
    if -6 in codes or 134 in codes:
        tags.add("abort")
    if 124 in codes:
        tags.add("timeout")
    return sorted(tags)
