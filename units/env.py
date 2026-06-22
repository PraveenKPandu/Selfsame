"""Time/RNG units. Nondeterministic in the wild, but the harness freezes the
clock and seeds entropy, so they become verifiable. The refactors preserve
behavior *including* their use of those sources."""

import random
import time
from typing import List, Optional

from probe.model import Unit


# --- clock ---------------------------------------------------------------- #
def cache_key_orig(n: int) -> str:
    bucket = int(time.time()) // 60
    return "%d:%d" % (n, bucket)


def cache_key_ref(n: int) -> str:
    return str(n) + ":" + str(int(time.time()) // 60)


# --- entropy: same RNG draws, restyled ------------------------------------ #
def shuffle_pick_orig(xs: List[int]) -> Optional[int]:
    if not xs:
        return None
    ys = list(xs)
    random.shuffle(ys)
    return ys[0]


def shuffle_pick_ref(xs: List[int]) -> Optional[int]:
    if len(xs) == 0:
        return None
    ys = list(xs)
    random.shuffle(ys)
    return ys[0]


def jittered_backoff_orig(n: int) -> float:
    base = float(2 ** n)
    jitter = random.random()
    return base + jitter


def jittered_backoff_ref(n: int) -> float:
    jitter = random.random()
    return float(2 ** n) + jitter


UNITS = [
    Unit("cache_key", "time", cache_key_orig, cache_key_ref),
    Unit("shuffle_pick", "rng", shuffle_pick_orig, shuffle_pick_ref),
    Unit("jittered_backoff", "rng", jittered_backoff_orig, jittered_backoff_ref),
]
