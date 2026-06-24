"""JSON-serializable canonical form of a value, for comparing observations
across processes.

The capture/replay pipeline runs each version of the code in its own subprocess
(two versions of the same package can't coexist in one interpreter), so behavior
has to cross a process boundary to be compared. This mirrors probe.equality's
structural rules but emits plain JSON, so two canonical forms are equal iff
`==` on the JSON says so (order-normalized for sets/dicts).
"""

from __future__ import annotations

import collections.abc
import datetime as _dt
import decimal as _decimal
import fractions as _fractions
import json
import math
import os
import pathlib as _pathlib
import re as _re
import types
from typing import Any

_MAX_DEPTH = 60
# materialize lazy iterators up to here; beyond -> refuse (configurable)
_ITER_CAP = int(os.environ.get("PROBE_ITER_CAP", "1000"))

_LAZY_TYPES = (types.GeneratorType, map, filter, zip, enumerate)


def _is_lazy_iterator(v: Any) -> bool:
    if isinstance(v, _LAZY_TYPES):
        return True
    if type(v).__module__ == "itertools":
        return True
    # a true iterator (has __next__) that isn't a plain container
    return isinstance(v, collections.abc.Iterator)


def _slots_state(obj: Any):
    names = []
    for cls in type(obj).__mro__:
        names.extend(getattr(cls, "__slots__", ()) or ())
    return {n: getattr(obj, n) for n in names if hasattr(obj, n)}


def _public_attrs(obj: Any):
    """Public (non-underscore) instance attributes, or None if there are none.

    Reads only from the object's own `__dict__`/`__slots__` storage (never
    descriptors/properties, which could compute or mutate), so this is
    side-effect-free and representation-only-as-named-by-the-author.
    """
    out = {}
    d = getattr(obj, "__dict__", None)
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(k, str) and not k.startswith("_"):
                out[k] = v
    for k in _slots_state(obj):
        if isinstance(k, str) and not k.startswith("_"):
            out[k] = getattr(obj, k)
    return out or None


def _public_snapshot(value: Any, _depth: int):
    """Representation-independent snapshot via the OBSERVABLE public interface,
    or None if no *side-effect-free* public view exists.

    Soundness rules:
    - Mappings are EXCLUDED here: materializing items calls `__getitem__`, which
      mutates LRU-style caches. They fall through to private-state comparison.
    - Only Sequence/Set are read, because for those `__iter__` is the contract
      for "the contents" and is side-effect-free; the contents are the behavior.
    - The class qualname is kept in the tag so two genuinely different container
      types never collide (no missed catch); a refactor that changes internals
      but keeps the same class + same contents still canonicalizes equal.
    """
    # A Mapping is iterable but reading its values is side-effecting for caches.
    # Never take the sequence/set path for one; let it fall back.
    if isinstance(value, collections.abc.Mapping):
        return None

    cls = type(value)
    contents = None
    kind = None
    if isinstance(value, collections.abc.Sequence):
        # str/bytes are handled earlier; anything reaching here is a real
        # sequence whose ordered contents are its observable behavior.
        kind = "seq"
        contents = ["seq-items", [canonical(x, _depth + 1) for x in value]]
    elif isinstance(value, collections.abc.Set):
        kind = "set-like"
        items = [canonical(x, _depth + 1) for x in value]
        items.sort(key=lambda c: json.dumps(c, sort_keys=True))
        contents = ["set-items", items]

    if contents is None:
        return None

    snap = [kind, contents]
    pub = _public_attrs(value)
    if pub is not None:
        snap.append(["public", canonical(pub, _depth + 1)])
    return ["pub-obj", cls.__qualname__, snap]


def _tzname(v):
    try:
        return v.tzname()
    except Exception:
        return None


def _leaf_value(value, _depth):
    """Sound canonical form for common stdlib value types that otherwise have no
    comparable structure (datetime, Decimal, Path, re.Match, ...).

    Each uses the value's OBSERVABLE form, so two values canonicalize equal iff
    they are observationally indistinguishable. That gives both guarantees at
    once: observationally-identical values never read as a divergence (no false
    divergence), and observationally-different values never read as equivalent
    (no false equivalence). Returns None for anything that isn't a known leaf
    type, so the caller falls through to the existing object/opaque handling.
    """
    # datetime must be checked before date (datetime subclasses date).
    if isinstance(value, _dt.datetime):
        return ["datetime", value.isoformat(), value.fold, _tzname(value)]
    if isinstance(value, _dt.date):
        return ["date", value.isoformat()]
    if isinstance(value, _dt.time):
        return ["time", value.isoformat(), value.fold, _tzname(value)]
    if isinstance(value, _dt.timedelta):
        return ["timedelta", value.days, value.seconds, value.microseconds]
    if isinstance(value, _dt.tzinfo):
        off = value.utcoffset(None)
        return ["tzinfo", value.tzname(None),
                off.total_seconds() if off is not None else None]
    if isinstance(value, _decimal.Decimal):
        if value.is_nan():
            return ["decimal", "nan"]
        if value.is_infinite():
            return ["decimal", "inf" if value > 0 else "-inf"]
        return ["decimal", str(value)]
    if isinstance(value, complex):
        return ["complex", canonical(value.real, _depth + 1),
                canonical(value.imag, _depth + 1)]
    if isinstance(value, _fractions.Fraction):
        return ["fraction", value.numerator, value.denominator]
    if isinstance(value, _pathlib.PurePath):
        return ["path", str(value)]
    if isinstance(value, _re.Match):
        return ["match", canonical(value.re.pattern, _depth + 1),
                list(value.span()), canonical(value.groups(), _depth + 1),
                canonical(sorted(value.groupdict().items()), _depth + 1)]
    if isinstance(value, _re.Pattern):
        return ["pattern", canonical(value.pattern, _depth + 1), value.flags]
    if value is NotImplemented:
        return ["singleton", "NotImplemented"]
    if value is Ellipsis:
        return ["singleton", "Ellipsis"]
    return None


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

    # Callables/classes can't be compared by value; identify them by
    # module+qualname. Two versions referencing the same function compare equal;
    # a changed reference is a divergence. Fixes "opaque" state/values that hold
    # functions (e.g. caches storing function values).
    if isinstance(value, (types.FunctionType, types.BuiltinFunctionType,
                          types.MethodType, types.MethodWrapperType,
                          types.BuiltinMethodType)):
        return ["callable", getattr(value, "__module__", "?"),
                getattr(value, "__qualname__", getattr(value, "__name__", "?"))]
    if isinstance(value, type):
        return ["class", getattr(value, "__module__", "?"), value.__qualname__]

    # range: exact and lazy — represent by its bounds, not by materializing.
    if isinstance(value, range):
        return ["range", value.start, value.stop, value.step]

    # Common stdlib leaf value types (datetime, Decimal, Path, re.Match, ...) by
    # their observable form. Guarded: a pathological tzinfo/object that raises
    # falls through to the existing object/opaque handling, never breaking a run.
    try:
        leaf = _leaf_value(value, _depth)
    except Exception:
        leaf = None
    if leaf is not None:
        return leaf

    # Lazy iterators/generators: the behavior IS the sequence they yield, so
    # materialize (bounded) and compare that. Unbounded -> refuse (opaque).
    if _is_lazy_iterator(value):
        items = []
        for i, x in enumerate(value):
            if i >= _ITER_CAP:
                return ["opaque", "iterator-truncated"]
            items.append(canonical(x, _depth + 1))
        return ["iter", items]

    # Public-interface snapshot: compare a stateful object by its OBSERVABLE
    # contents (Sequence/Set) so the comparison is representation-independent
    # (a refactor that swaps internal layout but preserves contents stays
    # equivalent). Never used for Mappings (side-effecting reads). Falls back to
    # private state below when no safe public view exists, so classes that the
    # private path already handles (e.g. SortedList) never regress.
    try:
        snap = _public_snapshot(value, _depth)
    except Exception:
        snap = None  # broken __iter__/__len__ etc. -> fall back, never guess
    if snap is not None:
        return snap

    cls = type(value)
    d = getattr(value, "__dict__", None)
    slots = _slots_state(value)
    # An object with a real (even EMPTY) __dict__ or __slots__ is introspectable:
    # compare it by that state. An empty __dict__ is empty state, NOT "no state"
    # — two stateless instances of the same class are observationally equal, so a
    # method on a stateless receiver must be comparable, not refused as opaque.
    if isinstance(d, dict) or slots:
        state = dict(d) if isinstance(d, dict) else {}
        state.update(slots)
        return ["obj", cls.__qualname__, canonical(state, _depth + 1)]
    # No introspectable state at all (e.g. object(), some C types): cannot be
    # compared structurally. Tag uniquely so two opaque values never compare
    # equal (forces an honest "can't tell").
    return ["opaque", cls.__qualname__, "<unrepresentable>"]
