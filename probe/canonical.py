"""JSON-serializable canonical form of a value, for comparing observations
across processes.

The capture/replay pipeline runs each version of the code in its own subprocess
(two versions of the same package can't coexist in one interpreter), so behavior
has to cross a process boundary to be compared. This mirrors probe.equality's
structural rules but emits plain JSON, so two canonical forms are equal iff
`==` on the JSON says so (order-normalized for sets/dicts).
"""

from __future__ import annotations

import json
import math
from typing import Any

_MAX_DEPTH = 60


def _slots_state(obj: Any):
    names = []
    for cls in type(obj).__mro__:
        names.extend(getattr(cls, "__slots__", ()) or ())
    return {n: getattr(obj, n) for n in names if hasattr(obj, n)}


def canonical(value: Any, _depth: int = 0) -> Any:
    if _depth > _MAX_DEPTH:
        return ["maxdepth"]
    if value is None:
        return ["none"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", value]
    if isinstance(value, float):
        if math.isnan(value):
            return ["float", "nan"]
        if value == 0.0:
            return ["float", 0.0]
        return ["float", value]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, (bytes, bytearray)):
        return ["bytes", list(value)]
    if isinstance(value, (list, tuple)):
        tag = "list" if isinstance(value, list) else "tuple"
        return [tag, [canonical(x, _depth + 1) for x in value]]
    if isinstance(value, (set, frozenset)):
        items = [canonical(x, _depth + 1) for x in value]
        items.sort(key=lambda c: json.dumps(c, sort_keys=True))
        return ["set", items]
    if isinstance(value, dict):
        items = [[canonical(k, _depth + 1), canonical(v, _depth + 1)]
                 for k, v in value.items()]
        items.sort(key=lambda c: json.dumps(c, sort_keys=True))
        return ["dict", items]

    cls = type(value)
    state = getattr(value, "__dict__", None)
    if not state:
        state = _slots_state(value)
    if state:
        return ["obj", cls.__qualname__, canonical(dict(state), _depth + 1)]
    # No introspectable state: cannot be compared structurally. Tag uniquely so
    # two opaque values never compare equal (forces an honest "can't tell").
    return ["opaque", cls.__qualname__, "<unrepresentable>"]
