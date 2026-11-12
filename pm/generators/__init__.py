"""Seeded problem generators: the same id, version, seed and variant always give the same problem."""
import random
from dataclasses import dataclass

from pm import grade

MAX_TRIES = 200


@dataclass(frozen=True)
class Problem:
    gen: str
    version: int
    seed: int
    variant: str
    title: str
    text: str
    kind: str
    expected: dict
    steps: str
    marks: float = 2.0


_REGISTRY: dict = {}


def register(generator) -> None:
    _REGISTRY[generator.ID] = generator


def unregister(gen_id: str) -> None:
    _REGISTRY.pop(gen_id, None)


def ids() -> list[str]:
    return sorted(_REGISTRY)


def info(gen_id: str):
    try:
        return _REGISTRY[gen_id]
    except KeyError:
        raise LookupError(f"no generator {gen_id!r}") from None


def make(gen_id: str, seed: int, variant: str | None = None) -> Problem:
    return build(info(gen_id), seed, variant)


def build(g, seed: int, variant: str | None = None) -> Problem:
    """make() for a generator object that may not be registered (templates.check_file)."""
    gen_id = g.ID
    rng = random.Random(f"{gen_id}/{g.VERSION}/{seed}")
    picked = rng.choice(g.VARIANTS)
    if variant is not None:
        if variant not in g.VARIANTS:
            raise ValueError(f"{gen_id} has no variant {variant!r}")
        picked = variant
    for _ in range(MAX_TRIES):
        drawn = g.draw(rng, picked)
        if drawn is not None:
            text, kind, expected, steps = drawn
            return Problem(gen_id, g.VERSION, seed, picked, g.TITLE, text, kind,
                           grade.parse_expected(kind, expected), steps)
    raise ValueError(f"{gen_id} found no good problem for seed {seed}")


def table(head: list[str], rows: list[list]) -> str:
    """A Markdown table."""
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


from pm.generators import banker, cpu, disk, hashing, paging  # noqa: E402

for _module in (paging, cpu, disk, banker, hashing):
    register(_module)
