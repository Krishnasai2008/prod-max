"""Read and check typed answers. User text is only ever matched with regular expressions; nothing is evaluated."""
import math
import re
from fractions import Fraction

KINDS = ("number", "token", "sequence", "set", "choice")

_DASHES = str.maketrans({"−": "-", "–": "-", "—": "-"})
_SPLIT = re.compile(r"\s*(?:->|→|>|[,;\s])\s*")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_UNIT = re.compile(r"(?:%|[A-Za-z°/% ]|\^-?\d)*")


def clean(text: str) -> str:
    text = " ".join(str(text).translate(_DASHES).split())
    return text.rstrip(".;,").strip()


def tokens(text: str) -> list[str]:
    return [part.casefold() for part in _SPLIT.split(clean(text)) if part]


def number(text: str) -> Fraction:
    """6.25 ms, 6,250, 25/4, −3, 40% → a Fraction; anything else → ValueError."""
    raw = text
    text = _THOUSANDS.sub("", clean(text))
    match = re.match(r"([-+]?\d+(?:\.\d+)?)(?:/(\d+))?", text)
    if match is None or not _UNIT.fullmatch(text[match.end():]):
        raise ValueError(f"couldn't read {raw!r} as a number")
    value = Fraction(match[1])
    if match[2] is not None:
        if int(match[2]) == 0:
            raise ValueError(f"couldn't read {raw!r} as a number")
        value /= int(match[2])
    return value


def _strings(value) -> list[str] | None:
    if isinstance(value, list) and value and all(isinstance(v, str) and v.strip() for v in value):
        return [v.strip() for v in value]
    return None


def parse_expected(kind: str, raw: dict) -> dict:
    """Check an answer key and return it normalised; ValueError when it can't be used."""
    if kind not in KINDS:
        raise ValueError(f"unknown answer kind {kind!r}")
    if not isinstance(raw, dict):
        raise ValueError(f"a {kind} answer needs a value")
    if kind == "number":
        value, tol = raw.get("value"), raw.get("tol", 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("a number answer needs a value")
        if isinstance(tol, bool) or not isinstance(tol, (int, float)) or not 0 <= tol < math.inf:
            raise ValueError("a number answer's tol must be 0 or more")
        return {"value": value, "tol": tol}
    if kind == "token":
        value = raw.get("value")
        if not isinstance(value, str) or not tokens(value):
            raise ValueError("a token answer needs a value")
        return {"value": value.strip()}
    if kind in ("sequence", "set"):
        if kind == "sequence" and "accept" in raw:
            accept = raw["accept"]
            lists = [_strings(a) for a in accept] if isinstance(accept, list) and accept else [None]
            if any(a is None for a in lists):
                raise ValueError("a sequence answer needs a value")
            return {"accept": lists}
        value = _strings(raw.get("value"))
        if value is None:
            raise ValueError(f"a {kind} answer needs a value")
        return {"value": value}
    options, correct = raw.get("options"), raw.get("correct")
    if _strings(options) is None or not 2 <= len(options) <= 8:
        raise ValueError("a choice answer needs 2-8 options")
    if (not isinstance(correct, list) or not correct
            or not all(isinstance(c, int) and not isinstance(c, bool) for c in correct)):
        raise ValueError("a choice answer needs its correct options")
    if not all(1 <= c <= len(options) for c in correct):
        raise ValueError(f"correct must name options 1-{len(options)}")
    return {"options": _strings(options), "correct": sorted(set(correct))}


def _choices(answer: str, count: int) -> set[int] | None:
    picked = set()
    for part in tokens(answer):
        if part.isascii() and part.isdigit():  # '²' is a digit to isdigit and an error to int
            n = int(part)
        elif len(part) == 1 and "a" <= part <= "z":
            n = ord(part) - ord("a") + 1
        else:
            return None
        if not 1 <= n <= count:
            return None
        picked.add(n)
    return picked or None


def readable(kind: str, expected: dict, answer: str) -> bool:
    if kind == "number":
        try:
            number(answer)
        except ValueError:
            return False
        return True
    if kind == "choice":
        return _choices(answer, len(expected["options"])) is not None
    return bool(tokens(answer))


def check(kind: str, expected: dict, answer: str) -> bool:
    """Whether the answer is right; text that can't be read is simply wrong."""
    if not isinstance(answer, str):
        return False
    if kind == "number":
        try:
            got = number(answer)
        except ValueError:
            return False
        return abs(got - Fraction(str(expected["value"]))) <= Fraction(str(expected.get("tol", 0))) + Fraction(1, 10**9)
    if kind == "token":
        return bool(tokens(answer)) and tokens(answer) == tokens(expected["value"])
    if kind == "sequence":
        accepted = expected.get("accept") or [expected["value"]]
        got = tokens(answer)
        return any(got == [t.casefold() for item in a for t in tokens(item)] for a in accepted)
    if kind == "set":
        want = sorted(t for item in expected["value"] for t in tokens(item))
        return sorted(tokens(answer)) == want
    if kind == "choice":
        return _choices(answer, len(expected["options"])) == set(expected["correct"])
    return False


def show(kind: str, expected: dict) -> str:
    """The answer key as text, for the reveal after a test."""
    if kind == "number":
        tol = expected.get("tol", 0)
        return f"{expected['value']:g} (±{tol:g})" if tol else f"{expected['value']:g}"
    if kind == "token":
        return expected["value"]
    if kind == "sequence":
        accepted = expected.get("accept") or [expected["value"]]
        text = " ".join(accepted[0])
        return text + (f" (one of {len(accepted)} accepted orders)" if len(accepted) > 1 else "")
    if kind == "set":
        return "{" + ", ".join(expected["value"]) + "}"
    if kind == "choice":
        return "; ".join(f"{chr(ord('A') + c - 1)}: {expected['options'][c - 1]}" for c in expected["correct"])
    return ""
