"""Type-hint-driven input generation.

Given a callable, build a deterministic set of argument tuples from each
parameter's annotation, then take the Cartesian-ish product (bounded). Any
parameter annotated `Effects` is skipped here — the harness injects it. Authors
can add `seeds` on a Unit to force specific inputs (boundaries, the case a
positive control trips); seeds are merged ahead of the generated inputs.

Hypothesis is the production upgrade; this is the deterministic stand-in.
"""

from __future__ import annotations

import ast
import inspect
import typing
from typing import Any, Callable, Dict, List, Tuple

from .effects import Effects


class UnsupportedSignature(Exception):
    """Raised when a parameter's type can't be generated for. The honest
    alternative to silently feeding `0` and reporting a meaningless verdict."""


# Small, fixed, boundary-heavy value pools per type. Order is fixed so runs are
# reproducible under PYTHONHASHSEED=0.
_POOLS = {
    int: [0, 1, -1, 2, 7, 100],
    float: [0.0, 1.5, -2.25, 10.0],
    bool: [False, True],
    str: ["", "a", "hello world", "  pad  ", "aAbB", "x,y,z"],
}

_LIST_ELEMS = {
    int: [[], [1], [1, 2, 3], [3, 1, 2], [0, 0, 1], [-1, 5, 5]],
    str: [[], ["a"], ["a", "b", "a"], ["z", "y", "x"]],
    float: [[], [1.0], [2.5, 2.5, 1.0]],
}

# Cap on generated combinations per unit, before seeds are added.
_MAX_COMBOS = 12


def _pool_for(annotation: Any) -> List[Any]:
    """Return a candidate value pool for a single annotation."""
    if annotation in _POOLS:
        return list(_POOLS[annotation])

    # Bare (unsubscripted) containers default to int-element shapes.
    if annotation is list:
        return [list(v) for v in _LIST_ELEMS[int]]
    if annotation is tuple:
        return [tuple(v) for v in _LIST_ELEMS[int]]
    if annotation is dict:
        return [{}, {"k": 1}, {"a": 1, "b": 2}]

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    if origin in (list, typing.List):
        elem = args[0] if args else int
        if elem not in _LIST_ELEMS:
            raise UnsupportedSignature("no generator for list element %r" % (elem,))
        return [list(v) for v in _LIST_ELEMS[elem]]

    if origin in (tuple, typing.Tuple):
        elem = args[0] if args else int
        if elem not in _LIST_ELEMS:
            raise UnsupportedSignature("no generator for tuple element %r" % (elem,))
        return [tuple(v) for v in _LIST_ELEMS[elem]]

    if origin in (dict, typing.Dict):
        # Only primitive key/value types; a domain-typed dict is unsupported.
        if args and any(a not in (int, float, str, bool) for a in args):
            raise UnsupportedSignature("no generator for dict types %r" % (args,))
        return [{}, {"k": 1}, {"a": 1, "b": 2}]

    # typing.Optional[T] -> include None alongside T's pool.
    if origin is typing.Union:
        pools: List[Any] = []
        for a in args:
            if a is type(None):
                pools.append(None)
            else:
                pools.extend(_pool_for(a))
        return pools

    # A type we have no strategy for. Refuse rather than fabricate inputs.
    raise UnsupportedSignature("no generator for annotation %r" % (annotation,))


def _bounded_product(pools: List[List[Any]]) -> List[Tuple]:
    """Cartesian product, capped at _MAX_COMBOS, deterministic order."""
    combos: List[Tuple] = [()]
    for pool in pools:
        combos = [c + (v,) for c in combos for v in pool]
        if len(combos) > _MAX_COMBOS:
            combos = combos[:_MAX_COMBOS]
    return combos


def _generatable_params(fn: Callable) -> List[Tuple[str, Any]]:
    """(name, annotation) for each parameter we must generate a value for.

    Skips the Effects parameter, *args/**kwargs, and defaulted parameters
    (defaults are left as-is so changed-default refactors are exercised). Raises
    UnsupportedSignature for an unannotated parameter.
    """
    sig = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn)
    except Exception:
        hints = {}
    out: List[Tuple[str, Any]] = []
    for name, param in sig.parameters.items():
        annotation = hints.get(name, param.annotation)
        if annotation is Effects:
            continue
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        if param.default is not inspect.Parameter.empty:
            continue
        if annotation is inspect.Parameter.empty:
            raise UnsupportedSignature("parameter %r is unannotated" % name)
        out.append((name, annotation))
    return out


def generate(fn: Callable) -> List[Tuple]:
    """Build argument tuples for `fn`, excluding any Effects parameter."""
    params = _generatable_params(fn)
    if not params:
        return [()]
    pools = [_pool_for(ann) for _, ann in params]
    return _bounded_product(pools)


def mine_literals(source: str, func_name: str) -> Dict[type, List[Any]]:
    """Collect str/int/float constants used inside `func_name`'s body.

    Feeding these back as inputs catches bugs that hinge on a specific magic
    value (e.g. a parser that special-cases "on") which a fixed value pool would
    never produce. A lightweight stand-in for what a smart generator would mine.
    """
    found: Dict[type, List[Any]] = {str: [], int: [], float: []}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant):
                    v = sub.value
                    if isinstance(v, bool):
                        continue
                    for t in (str, int, float):
                        if type(v) is t and v not in found[t]:
                            found[t].append(v)
    return found


def literal_seeds(fn: Callable, literals: Dict[type, List[Any]]) -> List[Tuple]:
    """Build seed inputs that set one primitive parameter at a time to a mined
    literal (others at their first pool value)."""
    try:
        params = _generatable_params(fn)
        base = [_pool_for(ann)[0] for _, ann in params]
    except UnsupportedSignature:
        return []
    if not params:
        return []
    seeds: List[Tuple] = []
    for i, (_name, ann) in enumerate(params):
        for lit in literals.get(ann, []):
            row = list(base)
            row[i] = lit
            seeds.append(tuple(row))
    return seeds


def effects_param(fn: Callable) -> "str | None":
    """Name of the parameter annotated `Effects`, if any."""
    sig = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn)
    except Exception:
        hints = {}
    for name, param in sig.parameters.items():
        if hints.get(name, param.annotation) is Effects:
            return name
    return None
