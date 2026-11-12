"""Estimate bias: log(actual/estimate) ~ Normal(mu, sigma^2) with a normal-inverse-gamma prior."""
import math
import random
from dataclasses import dataclass

MIN_PER_KIND = 3
CLAMP = (0.2, 10.0)


@dataclass(frozen=True)
class Posterior:
    mu: float
    kappa: float
    alpha: float
    beta: float
    n: int


PRIOR = Posterior(math.log(1.5), 1.0, 2.0, 0.25, 0)


def update(prior: Posterior, log_ratios: list[float]) -> Posterior:
    n = len(log_ratios)
    if n == 0:
        return prior
    xbar = sum(log_ratios) / n
    ss = sum((x - xbar) ** 2 for x in log_ratios)
    kappa = prior.kappa + n
    return Posterior(
        mu=(prior.kappa * prior.mu + n * xbar) / kappa,
        kappa=kappa,
        alpha=prior.alpha + n / 2,
        beta=prior.beta + ss / 2 + prior.kappa * n * (xbar - prior.mu) ** 2 / (2 * kappa),
        n=prior.n + n,
    )


def posteriors(ratios: list[tuple[str, float]]) -> dict[str, Posterior]:
    by_kind: dict[str, list[float]] = {}
    for kind, r in ratios:
        by_kind.setdefault(kind, []).append(math.log(r))
    post = {"*": update(PRIOR, [x for xs in by_kind.values() for x in xs])}
    post.update({k: update(PRIOR, xs) for k, xs in by_kind.items() if len(xs) >= MIN_PER_KIND})
    return post


def for_kind(post: dict[str, Posterior], kind: str) -> Posterior:
    return post.get(kind, post["*"])


def sample_ratio(p: Posterior, rng: random.Random) -> float:
    """One draw from the Student-t posterior predictive, back on the ratio scale."""
    scale = math.sqrt(p.beta * (p.kappa + 1) / (p.alpha * p.kappa))
    t = rng.gauss(0, 1) / math.sqrt(rng.gammavariate(p.alpha, 2) / (2 * p.alpha))
    x = min(p.mu + scale * t, 50.0)  # heavy-tailed t can exceed exp's range; e^50 is far past the clamp
    return min(max(math.exp(x), CLAMP[0]), CLAMP[1])


def median_ratio(p: Posterior) -> float:
    return math.exp(p.mu)
