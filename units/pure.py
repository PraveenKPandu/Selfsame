"""Pure units: no clock, no entropy, no I/O. Equivalent refactors."""

from typing import List

from probe.model import Unit


def sum_list_orig(xs: List[int]) -> int:
    total = 0
    for x in xs:
        total += x
    return total


def sum_list_ref(xs: List[int]) -> int:
    return sum(xs)


def factorial_orig(n: int) -> int:
    r = 1
    for i in range(2, n + 1):
        r *= i
    return r


def factorial_ref(n: int) -> int:
    if n <= 1:
        return 1
    return n * factorial_ref(n - 1)


def normalize_orig(s: str) -> str:
    return " ".join(s.split())


def normalize_ref(s: str) -> str:
    import re
    return re.sub(r"\s+", " ", s).strip()


def dedup_orig(xs: List[int]) -> List[int]:
    seen = set()
    out = []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def dedup_ref(xs: List[int]) -> List[int]:
    return list(dict.fromkeys(xs))


UNITS = [
    Unit("sum_list", "pure", sum_list_orig, sum_list_ref),
    Unit("factorial", "pure", factorial_orig, factorial_ref),
    Unit("normalize_whitespace", "pure", normalize_orig, normalize_ref),
    Unit("dedup_preserve_order", "pure", dedup_orig, dedup_ref),
]
