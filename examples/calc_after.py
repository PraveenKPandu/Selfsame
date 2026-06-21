"""The AFTER version — a mix of safe refactors and one real bug."""

import re
import secrets


def tax(amount: float, rate: float) -> float:
    surcharge = amount * rate          # restyle, same arithmetic
    return amount + surcharge


def apply_discount(price: int, pct: int) -> int:
    discount = price * pct / 100       # BUG: '/' makes this float, not int
    return price - discount


def slugify(title: str) -> str:
    return re.sub(r"\s+", "-", title.strip().lower())   # regex rewrite


def make_token(seed: int) -> str:
    token = secrets.token_hex(4)       # same entropy use, restructured
    return str(seed) + "-" + token


def score(data) -> int:
    return len(data)


def summarize(items: list, ndigits: int = 2) -> int:   # signature changed
    return sum(items)
