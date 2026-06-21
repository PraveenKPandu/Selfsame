"""Phase-3 real-coverage corpus — AFTER versions.

Behavior-preserving refactors ("refactor, preserve behavior"), the task an LLM
is given. One deliberate behavior change (parse_bool drops the "on" token) is
included to confirm divergence-catching still works on real-style code.
Coverage measures how many of these the probe can make a trustworthy verdict
about — independent of whether that verdict is equivalent or divergent.
"""

from typing import List


class LineItem:
    def __init__(self, price, qty):
        self.price = price
        self.qty = qty


def clamp(x: int, lo: int, hi: int) -> int:
    return max(lo, min(x, hi))                       # equivalent restyle


def to_snake_case(name: str) -> str:
    import re
    return re.sub(r"([A-Z])", r"_\1", name).lower().lstrip("_")  # equivalent


def parse_bool(s: str) -> bool:
    return s.strip().lower() in ("1", "true", "yes")  # BUG: dropped "on"


def running_total(xs: List[int]) -> int:
    return sum(xs)                                    # equivalent


def capwords(s, sep=None):
    parts = s.split(sep)
    return (sep or ' ').join(p.capitalize() for p in parts)  # equivalent


def commonprefix(m):
    if not m:
        return ''
    s1, s2 = min(m), max(m)
    i = 0
    while i < len(s1) and s1[i] == s2[i]:
        i += 1
    return s1[:i]                                     # equivalent


def order_total(items: List[LineItem]) -> float:
    total = 0.0
    for it in items:
        total += it.price * it.qty
    return total                                      # equivalent


def session_token(uid: int) -> str:
    import secrets
    suffix = secrets.token_hex(6)
    return str(uid) + "." + suffix                   # equivalent


def backoff_delay(attempt: int) -> float:
    import random
    jitter = random.random()
    return min(60.0, float(2 ** attempt)) + jitter   # equivalent


def read_first_line(path: str) -> str:
    f = open(path)
    try:
        return f.readline()
    finally:
        f.close()                                    # equivalent


def fetch_status(url: str) -> int:
    from urllib.request import urlopen
    resp = urlopen(url)
    return resp.getcode()                            # equivalent


def parallel_sum(n: int) -> int:
    import threading
    box = {"v": 0}
    lock = threading.Lock()

    def worker():
        for _ in range(n):
            with lock:                               # "fix" — but still threaded
                box["v"] += 1

    ts = [threading.Thread(target=worker) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return box["v"]
