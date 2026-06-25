"""Recorded, deterministic effect shims.

A unit that touches the outside world takes an `Effects` parameter instead of
calling the network / filesystem directly. Every call is appended to an ordered
trace, and responses come from canned fixtures. The trace *is* part of observed
behavior: a refactor that changes which effects fire, or their order, is a
divergence even when the return value is unchanged.

In the real probe (see README) these stubs are swapped for vcrpy-style
record/replay against real recorded responses; the interface stays the same.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

# A frozen, deterministic clock exposed through effects, distinct from the
# globally-patched `time` module. Units may use either; both are controlled.
FROZEN_NOW = 1_700_000_000.0


class Effects:
    def __init__(self, fixtures: Dict[Tuple, Any] = None):
        self.trace: List[Tuple] = []
        self._fixtures: Dict[Tuple, Any] = dict(fixtures or {})

    def _record(self, *call: Any) -> None:
        self.trace.append(call)

    # --- network ---
    def http_get(self, url: str) -> str:
        self._record("http_get", url)
        return self._fixtures.get(("http_get", url), "<response:%s>" % url)

    # --- filesystem ---
    def read(self, path: str) -> str:
        self._record("read", path)
        return self._fixtures.get(("read", path), "")

    def write(self, path: str, data: str) -> None:
        self._record("write", path, data)

    # --- observability ---
    def log(self, message: Any) -> None:
        self._record("log", message)

    # --- clock (recorded, frozen) ---
    def now(self) -> float:
        self._record("now")
        return FROZEN_NOW
