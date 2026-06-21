#!/usr/bin/env python3
"""Entry point. Re-exec once with PYTHONHASHSEED=0 so hash/set ordering is fixed
for the whole run, then hand off to the runner."""

import os
import sys


def _ensure_fixed_hash_seed() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(sys.executable, [sys.executable] + sys.argv)


if __name__ == "__main__":
    _ensure_fixed_hash_seed()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from probe.runner import main
    raise SystemExit(main())
