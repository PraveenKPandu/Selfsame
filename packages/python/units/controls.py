"""Controls.

Positive controls: refactors that deliberately change behavior. The engine must
catch all three, or it is not earning its verdict.
Negative control: an A-vs-A pair (refactored IS original) that must verify
equivalent and never flicker.
"""

from typing import List

from probe.model import EXPECT_DIVERGENT, Unit


# --- positive control 1: off-by-one --------------------------------------- #
def range_sum_orig(n: int) -> int:
    total = 0
    for i in range(1, n + 1):  # inclusive of n
        total += i
    return total


def range_sum_bug(n: int) -> int:
    total = 0
    for i in range(1, n):      # BUG: drops the final term
        total += i
    return total


# --- positive control 2: dropped zero-guard ------------------------------- #
def safe_divide_orig(n: int) -> float:
    if n == 0:
        return 0.0
    return 100 / n


def safe_divide_bug(n: int) -> float:
    return 100 / n            # BUG: raises on n == 0 instead of guarding


# --- positive control 3: changed default ---------------------------------- #
def greet_orig(name: str, greeting: str = "Hello") -> str:
    return "%s, %s!" % (greeting, name)


def greet_bug(name: str, greeting: str = "Hi") -> str:  # BUG: default changed
    return "%s, %s!" % (greeting, name)


# --- negative control: A vs A --------------------------------------------- #
def stable_transform(xs: List[int]) -> List[int]:
    return sorted(set(xs))


UNITS = [
    Unit("range_sum_offbyone", "control", range_sum_orig, range_sum_bug,
         expect=EXPECT_DIVERGENT, seeds=[(1,), (5,)]),
    Unit("safe_divide_noguard", "control", safe_divide_orig, safe_divide_bug,
         expect=EXPECT_DIVERGENT, seeds=[(0,)]),
    Unit("greet_changed_default", "control", greet_orig, greet_bug,
         expect=EXPECT_DIVERGENT),
    Unit("identity_a_vs_a", "control", stable_transform, stable_transform),
]
