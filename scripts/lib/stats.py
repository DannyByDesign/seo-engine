"""Small statistics helpers shared by the monitoring skills.

`wilson_interval` is the confidence interval every reported *rate* in the
publication/GEO monitoring layer carries. A normal approximation degenerates
at 0 successes or tiny n — exactly the regime a young publication lives in
for months — while Wilson stays honest: 0 hits out of 1 probe still admits a
~80% upper bound ("could easily be common"), 0 out of 30 does not.
"""

from __future__ import annotations

import math


def wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[float, float]:
    """(low, high) Wilson score interval for a binomial proportion.

    z defaults to 1.96 (95%). An empty sample returns (0.0, 1.0): total
    uncertainty, never a divide-by-zero.
    """
    if trials <= 0:
        return 0.0, 1.0
    hits = min(max(successes, 0), trials)
    p = hits / trials
    z2 = z * z
    denominator = 1 + z2 / trials
    centre = p + z2 / (2 * trials)
    margin = z * math.sqrt((p * (1 - p)) / trials + z2 / (4 * trials * trials))
    return max(0.0, (centre - margin) / denominator), min(1.0, (centre + margin) / denominator)


def rate(hits: int, asks: int) -> dict:
    """The one shape every rate is reported in: point estimate plus interval."""
    low, high = wilson_interval(hits, asks)
    return {
        "hits": hits,
        "asks": asks,
        "point": round(hits / asks, 4) if asks else 0.0,
        "lo": round(low, 4),
        "hi": round(high, 4),
    }
