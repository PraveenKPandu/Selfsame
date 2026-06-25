"""A small 'real' module — the BEFORE version. See calc_after.py for the
refactor. Run:  python3 -m probe.check examples/calc_before.py examples/calc_after.py
"""

import secrets


def tax(amount: float, rate: float) -> float:
    return amount + amount * rate


def apply_discount(price: int, pct: int) -> int:
    discount = price * pct // 100
    return price - discount


def slugify(title: str) -> str:
    return "-".join(title.lower().split())


def make_token(seed: int) -> str:
    return "%d-%s" % (seed, secrets.token_hex(4))


def score(data) -> int:        # intentionally unannotated parameter
    return len(data)


def summarize(items: list) -> int:
    return sum(items)
