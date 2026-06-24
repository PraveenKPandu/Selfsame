#!/usr/bin/env bash
# Recreate the throwaway project the README demo GIF records.
# Run this BEFORE `vhs demo/selfsame.tape`.
#
# It freezes an accepted build (off-camera), then applies a "harmless" AI
# refactor that keeps the tests green but silently changes behavior — so the
# GIF only has to show the payoff: green tests, caught regression.
set -e
DEMO="${1:-/tmp/selfsame-demo}"
rm -rf "$DEMO"; mkdir -p "$DEMO/shop"; cd "$DEMO"

: > shop/__init__.py

cat > shop/pricing.py <<'PY'
def apply_discount(price, pct):
    """Return price after a percent discount, rounded to cents."""
    return round(price * (1 - pct / 100), 2)
PY

cat > test_pricing.py <<'PY'
from shop.pricing import apply_discount

def test_discounts_are_sane():
    # Exercises the function, but only checks a loose property — like real tests do
    for price, pct in [(100, 10), (19.99, 15), (250.0, 33), (5.55, 50)]:
        out = apply_discount(price, pct)
        assert 0 <= out <= price
PY

# Freeze the accepted build (not shown in the GIF).
selfsame snapshot --modules shop -- pytest -q >/dev/null 2>&1

# The "AI refactor": floor instead of round. Tests still pass (output stays in
# [0, price]) but the cents change on real inputs.
cat > shop/pricing.py <<'PY'
import math

def apply_discount(price, pct):
    """Return price after a percent discount, rounded to cents."""
    return math.floor(price * (1 - pct / 100) * 100) / 100
PY

echo "demo ready in $DEMO"
