"""Stateful units: build up internal state then return it. Deterministic given
the same inputs; equivalent refactors."""

from collections import Counter
from typing import List, Tuple

from probe.model import Unit


def running_stats_orig(xs: List[int]) -> Tuple[int, int, float]:
    count = 0
    total = 0
    for x in xs:
        count += 1
        total += x
    avg = total / count if count else 0.0
    return (count, total, avg)


def running_stats_ref(xs: List[int]) -> Tuple[int, int, float]:
    if not xs:
        return (0, 0, 0.0)
    return (len(xs), sum(xs), sum(xs) / len(xs))


def counter_dict_orig(xs: List[str]) -> dict:
    counts = {}
    for x in xs:
        counts[x] = counts.get(x, 0) + 1
    return counts


def counter_dict_ref(xs: List[str]) -> dict:
    return dict(Counter(xs))


UNITS = [
    Unit("running_stats", "stateful", running_stats_orig, running_stats_ref),
    Unit("word_frequency", "stateful", counter_dict_orig, counter_dict_ref),
]
