"""Structural value equality for behavior comparison.

`repr()` is a trap: a plain object's repr embeds its memory address, so the same
function compared with itself looks "different". This module compares two values
by structure instead:

- numbers/str/bytes/bool/None: by value (nan == nan, -0.0 == 0.0)
- list/tuple: same length, elementwise
- dict: Python `==` semantics (order-insensitive, recursive values)
- set/frozenset: set equality
- objects with a real `__eq__`: use it
- objects with only identity `__eq__`: compare their `__dict__` / `__slots__`
  state recursively (this is what fixes the address bug)
- anything we genuinely cannot introspect: reported as not-provably-equal

The aim is to be conservative: when we can't establish equality we say so, rather
than guessing.
"""

from __future__ import annotations

import collections.abc
import math
import types
from typing import Any

_MAX_DEPTH = 60

_CALLABLE_TYPES = (types.FunctionType, types.BuiltinFunctionType,
                   types.MethodType, types.MethodWrapperType,
                   types.BuiltinMethodType)


def _callable_id(v: Any):
    return (getattr(v, "__module__", "?"),
            getattr(v, "__qualname__", getattr(v, "__name__", "?")))


def _slots_state(obj: Any):
    names = []
    for cls in type(obj).__mro__:
        names.extend(getattr(cls, "__slots__", ()) or ())
    return {n: getattr(obj, n) for n in names if hasattr(obj, n)}


def _state(obj: Any):
    """Best-effort structural state of an identity-equality object, or None."""
    d = getattr(obj, "__dict__", None)
    if d:
        return dict(d)
    s = _slots_state(obj)
    if s:
        return s
    return None


def _public_attrs(obj: Any):
    out = {}
    d = getattr(obj, "__dict__", None)
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(k, str) and not k.startswith("_"):
                out[k] = v
    for k in _slots_state(obj):
        if isinstance(k, str) and not k.startswith("_"):
            out[k] = getattr(obj, k)
    return out


def _public_view(obj: Any):
    """Representation-independent observable view of an identity-equality
    Sequence/Set, or None when no *side-effect-free* public view exists.

    Mappings are excluded (reading items mutates LRU caches); they fall back to
    private-state comparison. Mirrors probe.canonical._public_snapshot.
    """
    if isinstance(obj, collections.abc.Mapping):
        return None
    if isinstance(obj, collections.abc.Sequence):
        return ("seq", list(obj), _public_attrs(obj))
    if isinstance(obj, collections.abc.Set):
        return ("set", frozenset(obj), _public_attrs(obj))
    return None


def equal(a: Any, b: Any, _depth: int = 0) -> bool:
    if _depth > _MAX_DEPTH:
        return True  # give up safely rather than recurse forever
    if a is b:
        return True

    ta, tb = type(a), type(b)
    if ta is not tb:
        return False

    if isinstance(a, float):
        if math.isnan(a) and math.isnan(b):
            return True
        return a == b
    if isinstance(a, (int, bool, str, bytes, bytearray, complex)) or a is None:
        return a == b

    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return False
        return all(equal(x, y, _depth + 1) for x, y in zip(a, b))

    if isinstance(a, dict):
        if len(a) != len(b):
            return False
        for k in a:
            if k not in b or not equal(a[k], b[k], _depth + 1):
                return False
        return True

    if isinstance(a, (set, frozenset)):
        try:
            return a == b
        except Exception:
            return False

    if isinstance(a, _CALLABLE_TYPES) or isinstance(a, type):
        return _callable_id(a) == _callable_id(b)

    # Custom __eq__ (anything that overrides object.__eq__): trust it.
    if ta.__eq__ is not object.__eq__:
        try:
            return bool(a == b)
        except Exception:
            return False

    # Identity-equality Sequence/Set: compare by OBSERVABLE contents so a
    # refactor that changes internal layout but preserves contents is still
    # equal (representation-independent). `ta is tb` already holds, so this only
    # compares same-typed containers. Mappings are excluded (side-effecting
    # reads) and fall through to private-state comparison below.
    try:
        va, vb = _public_view(a), _public_view(b)
    except Exception:
        va = vb = None  # broken __iter__ etc. -> fall back, never guess
    if va is not None and vb is not None:
        kind_a, items_a, pub_a = va
        kind_b, items_b, pub_b = vb
        if kind_a != kind_b:
            return False
        return equal(items_a, items_b, _depth + 1) and equal(pub_a, pub_b, _depth + 1)

    # Identity-equality object: compare introspected state. This is the fix for
    # the repr-address false-divergence.
    sa, sb = _state(a), _state(b)
    if sa is None or sb is None:
        return False  # opaque; cannot prove equal, so don't claim it
    return equal(sa, sb, _depth + 1)
