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


class Vec:
    """A plain object with only identity equality (no __eq__). Pre-fix, the
    harness compared by repr and saw the memory address, so this unit was a
    guaranteed false divergence even when behavior was identical."""

    def __init__(self, x, y):
        self.x = x
        self.y = y


def build_vec_orig(n: int) -> Vec:
    return Vec(n, n * 2)


def build_vec_ref(n: int) -> Vec:
    v = Vec(n, 0)
    v.y = n * 2  # same end state, reached differently
    return v


UNITS = [
    Unit("sum_list", "pure", sum_list_orig, sum_list_ref),
    Unit("factorial", "pure", factorial_orig, factorial_ref),
    Unit("normalize_whitespace", "pure", normalize_orig, normalize_ref),
    Unit("dedup_preserve_order", "pure", dedup_orig, dedup_ref),
    Unit("build_vector_object", "pure", build_vec_orig, build_vec_ref),
]
