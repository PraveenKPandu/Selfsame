"""Type-aware, deterministic mutation of captured input values.

Capture gives us *real* inputs (seeds) from a test run. To find divergences the
tests don't cover, we mutate around those seeds — small, boundary, and edge-case
perturbations — and replay both versions on the results. Mutations are
deterministic (fixed sets, no RNG) so a fuzz run is reproducible, and
type-preserving where possible so a mutated call doesn't just raise an identical
TypeError in both versions (which would be uninteresting).

`value_mutations(v)` -> variants of a single value.
`arg_set_mutations(args)` -> mutated argument tuples (one position perturbed at a
time), each a candidate input beyond what the tests exercised.
"""

from __future__ import annotations

import copy

_MAX_PER_VALUE = 12
_MAX_PER_ARGSET = 48

# Tokens worth trying for strings — common "magic" values that branch logic keys
# on but test suites often miss.
_STR_TOKENS = ["", "0", "1", "true", "false", "on", "off", "yes", "no",
               "none", "null", " ", "\n"]


def _dedup(variants, original):
    out = []
    seen = []
    for v in variants:
        try:
            if v == original or any(v == s for s in seen):
                continue
        except Exception:
            pass
        seen.append(v)
        out.append(v)
        if len(out) >= _MAX_PER_VALUE:
            break
    return out


def value_mutations(v):
    """Return a bounded list of mutated variants of `v` (excluding `v` itself)."""
    if isinstance(v, bool):
        return [not v]
    if isinstance(v, int):
        return _dedup([0, 1, -1, v + 1, v - 1, -v, v * 2,
                       2 ** 31 - 1, -(2 ** 31), 2 ** 63], v)
    if isinstance(v, float):
        return _dedup([0.0, -v, v * 2, v + 1.0, v - 1.0,
                       float("nan"), float("inf"), float("-inf")], v)
    if isinstance(v, str):
        base = [v + v, v.upper(), v.lower(), v.strip(), " " + v, v + " ",
                v[1:], v[:-1], v[::-1], v + "\x00"]
        return _dedup(base + _STR_TOKENS, v)
    if isinstance(v, bytes):
        return _dedup([b"", v + v, v[1:], v[::-1], v + b"\x00"], v)
    if isinstance(v, (list, tuple)):
        ctor = type(v)
        variants = [ctor()]
        if v:
            variants += [ctor(list(v)[1:]), ctor(list(v)[::-1]),
                         ctor(list(v) + [list(v)[-1]])]
            # mutate the first element in place
            for em in value_mutations(v[0])[:3]:
                lst = list(v)
                lst[0] = em
                variants.append(ctor(lst))
        return _dedup(variants, v)
    if isinstance(v, dict):
        variants = [{}]
        if v:
            k0 = next(iter(v))
            without = dict(v)
            without.pop(k0, None)
            variants.append(without)
            for vm in value_mutations(v[k0])[:3]:
                d = dict(v)
                d[k0] = vm
                variants.append(d)
        variants.append({**v, "__probe_extra__": 1})
        return _dedup(variants, v)
    # Objects with introspectable state: perturb one public-ish attribute at a
    # time (fuzz the receiver state of a method).
    state = getattr(v, "__dict__", None)
    if state:
        variants = []
        for attr, val in list(state.items())[:6]:
            for am in value_mutations(val)[:2]:
                try:
                    clone = copy.deepcopy(v)
                    setattr(clone, attr, am)
                    variants.append(clone)
                except Exception:
                    continue
        return variants[:_MAX_PER_VALUE]
    return []


def arg_set_mutations(args):
    """Given a captured positional arg tuple, return mutated arg tuples — each
    perturbs exactly one position. Bounded per arg-set."""
    args = list(args)
    out = []
    for i in range(len(args)):
        for m in value_mutations(args[i]):
            row = list(args)
            row[i] = m
            out.append(tuple(row))
            if len(out) >= _MAX_PER_ARGSET:
                return out
    return out
