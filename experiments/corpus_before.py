"""Phase-3 real-coverage corpus — BEFORE versions.

A stratified sample meant to mirror the mix found in real Python code, NOT to be
tractable: typed-primitive, untyped (real stdlib style), domain-typed, time/rng,
direct I/O, and concurrent. capwords/commonprefix are ~verbatim from the stdlib.
Imports are inside functions so the module loads even where deps are missing.
"""

from typing import List


class LineItem:
    def __init__(self, price, qty):
        self.price = price
        self.qty = qty


# --- pure, typed, primitive (probe sweet spot) --------------------------- #
def clamp(x: int, lo: int, hi: int) -> int:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def to_snake_case(name: str) -> str:
    out = []
    for ch in name:
        if ch.isupper():
            out.append("_" + ch.lower())
        else:
            out.append(ch)
    return "".join(out).lstrip("_")


def parse_bool(s: str) -> bool:
    return s.strip().lower() in ("1", "true", "yes", "on")


def running_total(xs: List[int]) -> int:
    total = 0
    for x in xs:
        total += x
    return total


# --- pure, UNTYPED (real stdlib style) ----------------------------------- #
def capwords(s, sep=None):
    return (sep or ' ').join(x.capitalize() for x in s.split(sep))


def commonprefix(m):
    if not m:
        return ''
    s1 = min(m)
    s2 = max(m)
    for i, c in enumerate(s1):
        if c != s2[i]:
            return s1[:i]
    return s1


# --- pure, DOMAIN-typed (custom element type) ---------------------------- #
def order_total(items: List[LineItem]) -> float:
    return sum(it.price * it.qty for it in items)


# --- time / rng (typed) -------------------------------------------------- #
def session_token(uid: int) -> str:
    import secrets
    return "%d.%s" % (uid, secrets.token_hex(6))


def backoff_delay(attempt: int) -> float:
    import random
    return min(60.0, 2 ** attempt) + random.random()


# --- direct I/O, unmodified (the interception gap) ----------------------- #
def read_first_line(path: str) -> str:
    with open(path) as f:
        return f.readline()


def fetch_status(url: str) -> int:
    from urllib.request import urlopen
    return urlopen(url).getcode()


# --- concurrency --------------------------------------------------------- #
def parallel_sum(n: int) -> int:
    import threading
    box = {"v": 0}

    def worker():
        for _ in range(n):
            box["v"] += 1

    ts = [threading.Thread(target=worker) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return box["v"]
