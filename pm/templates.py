"""Formula templates: TOML files whose answer is an expression; one loads only if it reproduces its original answer."""
import math
import re
import threading
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from pm import generators
from pm.expr import evaluate

_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
_NAME = re.compile(r"[a-z][a-z0-9_]{0,20}")
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
MAX_PARAMS = 12


@dataclass
class Template:
    id: str
    version: int
    title: str
    text: str
    answer: str
    decimals: int
    steps: str
    params: dict[str, tuple]
    constraints: list[str]
    original_params: dict
    original_answer: float


def fill(text: str, values: dict) -> str:
    return _PLACEHOLDER.sub(lambda m: str(values[m[1]]) if m[1] in values else m[0], text)


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and abs(v) <= 1e12


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _param(name: str, spec) -> tuple:
    where = f"params.{name}"
    if not _NAME.fullmatch(name) or name == "answer":
        raise ValueError(f"params: {name!r} can't be a parameter name (start with a-z, then a-z, 0-9 and _; not 'answer')")
    if not isinstance(spec, dict) or len(spec) != 1:
        raise ValueError(f"{where}: give one of int = [lo, hi], choice = [...] or decimal = [lo, hi, places]")
    (kind, value), = spec.items()
    if kind == "int":
        if not (isinstance(value, list) and len(value) == 2 and all(map(_is_int, value)) and value[0] <= value[1]):
            raise ValueError(f"{where}: int needs [lo, hi] with whole numbers and lo <= hi")
        return ("int", value[0], value[1])
    if kind == "choice":
        if not (isinstance(value, list) and value and all(map(_is_number, value))):
            raise ValueError(f"{where}: choice needs a list of numbers")
        return ("choice", tuple(value))
    if kind == "decimal":
        if not (isinstance(value, list) and len(value) == 3 and all(map(_is_number, value[:2]))
                and value[0] <= value[1] and _is_int(value[2]) and 1 <= value[2] <= 4
                and math.ceil(value[0] * 10 ** value[2]) <= math.floor(value[1] * 10 ** value[2])):
            raise ValueError(f"{where}: decimal needs [lo, hi, places] with lo <= hi, places 1-4 and a value between")
        return ("decimal", value[0], value[1], value[2])
    raise ValueError(f"{where}: unknown kind {kind!r} (int, choice or decimal)")


def _text(data: dict, key: str, required: bool = True) -> str:
    value = data.get(key, None if required else "")
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{key}: needs some text")
    return value


def _rounded(value, decimals: int):
    return round(value, decimals) if decimals else round(value)


def parse(text: str) -> Template:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"not valid TOML: {e}") from None
    tid = data.get("id")
    if not isinstance(tid, str) or not _ID.fullmatch(tid):
        raise ValueError("id: use a-z, 0-9 and -, up to 41 characters")
    version = data.get("version")
    if not _is_int(version) or version < 1:
        raise ValueError("version: needs a positive whole number")
    title, body, answer = _text(data, "title"), _text(data, "text"), _text(data, "answer")
    steps = _text(data, "steps", required=False)
    decimals = data.get("decimals", 2)
    if not _is_int(decimals) or not 0 <= decimals <= 6:
        raise ValueError("decimals: needs a whole number 0-6")
    constraints = data.get("constraints", [])
    if not isinstance(constraints, list) or not all(isinstance(c, str) and c.strip() for c in constraints):
        raise ValueError("constraints: needs a list of expressions")
    raw = data.get("params")
    if not isinstance(raw, dict) or not raw:
        raise ValueError("params: a template needs at least one parameter")
    if len(raw) > MAX_PARAMS:
        raise ValueError(f"params: at most {MAX_PARAMS} parameters")
    params = {name: _param(name, spec) for name, spec in raw.items()}
    original = data.get("original")
    if not isinstance(original, dict):
        raise ValueError("a template needs the original problem it came from")
    given, expected = original.get("params"), original.get("answer")
    if not isinstance(given, dict) or not all(_is_number(v) for v in given.values()):
        raise ValueError("original.params: needs a number for each parameter")
    missing = [n for n in params if n not in given]
    if missing:
        raise ValueError(f"original.params: missing {', '.join(missing)}")
    if not _is_number(expected):
        raise ValueError("original.answer: needs a number")
    for c in constraints:
        try:
            ok = evaluate(c, given)
        except ValueError as e:
            raise ValueError(f"constraints: {c!r}: {e}") from None
        if not ok:
            raise ValueError(f"the original problem breaks the constraint {c!r}")
    try:
        got = evaluate(answer, given)
    except ValueError as e:
        raise ValueError(f"answer: {e}") from None
    if not _is_number(got):
        raise ValueError("answer: must give a number")
    got = _rounded(got, decimals)
    if abs(got - expected) > 0.5 / 10**decimals:
        raise ValueError(f"the template doesn't reproduce its original answer: got {got:g}, expected {expected:g}")
    return Template(tid, version, title.strip(), body, answer, decimals, steps, params, constraints,
                    dict(given), expected)


def _value(rng, spec):
    if spec[0] == "int":
        return rng.randint(spec[1], spec[2])
    if spec[0] == "choice":
        return rng.choice(spec[1])
    scale = 10 ** spec[3]
    return round(rng.randint(math.ceil(spec[1] * scale), math.floor(spec[2] * scale)) / scale, spec[3])


def as_generator(template: Template):
    t = template

    def draw(rng, variant):
        values = {name: _value(rng, spec) for name, spec in t.params.items()}
        try:
            if not all(evaluate(c, values) for c in t.constraints):
                return None
            value = evaluate(t.answer, values)
        except ValueError:
            return None
        if not _is_number(value):
            return None
        value = _rounded(value, t.decimals)
        shown = f"{value:.{t.decimals}f}"
        text = fill(t.text, values)
        if t.decimals:
            text += f"\n\nGive the answer to {t.decimals} decimal places."
        return (text, "number", {"value": value, "tol": 0.5 / 10**t.decimals},
                fill(t.steps, {**values, "answer": shown}))

    return SimpleNamespace(ID=f"t:{t.id}", VERSION=t.version, TITLE=t.title, VARIANTS=("answer",),
                           draw=draw, template=t)


def folder_of(conn) -> Path | None:
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main":
            return Path(row[2]).parent / "templates" if row[2] else None
    return None


# shortcut: one templates folder per process (another folder replaces it), upgrade if one process serves two databases
_LOCK = threading.Lock()
_loaded: dict = {"key": None, "ids": [], "errors": []}


def sync(conn) -> list[str]:
    with _LOCK:  # pm ui serves on threads; a reload must not be seen half done
        return _sync(conn)


def _sync(conn) -> list[str]:
    folder = folder_of(conn)
    if folder is None:
        return []
    try:
        files = sorted(folder.glob("*.toml")) if folder.is_dir() else []
        signature = tuple((f.name, f.stat().st_mtime_ns) for f in files)
    except OSError as e:
        return [f"{folder}: {e}"]
    if _loaded["key"] == (folder, signature):
        return list(_loaded["errors"])
    for gen_id in _loaded["ids"]:
        generators.unregister(gen_id)
    loaded, errors = [], []
    for f in files:
        try:
            g = as_generator(parse(f.read_text(encoding="utf-8")))
            if g.ID in loaded:
                raise ValueError(f"id {g.template.id!r} is already used by another file")
        except (OSError, UnicodeDecodeError, ValueError) as e:
            errors.append(f"{f.name}: {e}")
            continue
        generators.register(g)
        loaded.append(g.ID)
    _loaded.update(key=(folder, signature), ids=loaded, errors=errors)
    return list(errors)


def check_file(path: Path, seeds: int = 200) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(str(e)) from None
    g = as_generator(parse(text))
    good = 0
    for seed in range(seeds):
        try:
            generators.build(g, seed)
            good += 1
        except ValueError:
            pass
    if not good:
        raise ValueError(f"{g.template.id} reproduces its original answer, but no seed gave a problem "
                         "(the constraints may never hold for the parameter ranges)")
    return f"ok: {g.template.id} reproduces its original answer; {good} of {seeds} seeds gave a problem"
