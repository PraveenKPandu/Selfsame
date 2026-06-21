"""The core: observe, self-check determinism, diff versions, classify causes.

Observation is the unit of truth. Running a function produces an Observation =
(return value | exception) + the ordered trace of recorded effects. Two runs are
"the same" iff their Observations are equal.

Pipeline per unit:
  1. self_check  -- run `original` 3x per input under a controlled environment.
                    If the three disagree, the unit is UNVERIFIABLE and we
                    classify why (concurrency / uncontrolled-time /
                    uncontrolled-entropy / unknown). Negative control: stable
                    code must never be flagged.
  2. diff        -- only for deterministic units: run original vs refactored on
                    the same inputs; any Observation mismatch is a caught
                    behavioral divergence.
"""

from __future__ import annotations

import inspect
import os
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from .effects import FROZEN_NOW, Effects
from .generators import effects_param

RUNS_PER_INPUT = 3  # self-check repetitions

# Causes for an unverifiable verdict.
CAUSE_CONCURRENCY = "concurrency"
CAUSE_TIME = "uncontrolled-time"
CAUSE_ENTROPY = "uncontrolled-entropy"
CAUSE_UNKNOWN = "unknown"


@dataclass
class Observation:
    result: Optional[str]          # repr of the return value
    exception: Optional[str]       # "ExcType: message", or None
    trace: Tuple                   # ordered recorded effects
    counts: Dict[str, int]         # threads / time / entropy calls seen

    def key(self) -> Tuple:
        """What defines behavioral identity (counts are diagnostics, not behavior)."""
        return (self.result, self.exception, self.trace)


class _Controlled:
    """Context manager freezing the clock, seeding entropy, and counting the
    nondeterminism sources a unit reaches into."""

    def __init__(self) -> None:
        self.counts = {"threads": 0, "time": 0, "entropy": 0}

    def __enter__(self) -> "_Controlled":
        c = self.counts
        self._saved: Dict[str, Any] = {}

        # --- freeze clock, count reads ---
        for name in ("time", "monotonic", "perf_counter"):
            self._saved[("time", name)] = getattr(time, name)

        def _frozen(_n=None):
            c["time"] += 1
            return FROZEN_NOW

        time.time = _frozen
        time.monotonic = _frozen
        time.perf_counter = _frozen

        # --- seed entropy so the sequence is identical every run, count reads ---
        random.seed(0)
        self._saved["urandom"] = os.urandom
        for fname in ("random", "randint", "randrange", "choice",
                      "shuffle", "uniform", "sample"):
            self._saved[("random", fname)] = getattr(random, fname)

        def _wrap_entropy(fn):
            def inner(*a, **k):
                c["entropy"] += 1
                return fn(*a, **k)
            return inner

        for fname in ("random", "randint", "randrange", "choice",
                      "shuffle", "uniform", "sample"):
            setattr(random, fname, _wrap_entropy(self._saved[("random", fname)]))

        def _det_urandom(n):
            c["entropy"] += 1
            return bytes((i * 37 + 11) & 0xFF for i in range(n))

        os.urandom = _det_urandom

        # --- count threads started (still really run them) ---
        self._saved["thread_start"] = threading.Thread.start
        real_start = self._saved["thread_start"]

        def _counting_start(thread_self, *a, **k):
            c["threads"] += 1
            return real_start(thread_self, *a, **k)

        threading.Thread.start = _counting_start
        return self

    def __exit__(self, *exc) -> None:
        for name in ("time", "monotonic", "perf_counter"):
            setattr(time, name, self._saved[("time", name)])
        for fname in ("random", "randint", "randrange", "choice",
                      "shuffle", "uniform", "sample"):
            setattr(random, fname, self._saved[("random", fname)])
        os.urandom = self._saved["urandom"]
        threading.Thread.start = self._saved["thread_start"]


def _build_call(fn: Callable, args: Tuple, fx: Effects):
    """Map generated args onto the signature, inserting fx at the Effects slot."""
    ep = effects_param(fn)
    if ep is None:
        return args, {}
    params = list(inspect.signature(fn).parameters)
    kwargs = {ep: fx}
    return args, kwargs


def observe(fn: Callable, args: Tuple, fixtures: Dict = None) -> Observation:
    """Run `fn(*args)` once under control; capture result/exception + effects."""
    fx = Effects(fixtures)
    with _Controlled() as ctrl:
        call_args, call_kwargs = _build_call(fn, args, fx)
        result: Optional[str] = None
        exception: Optional[str] = None
        try:
            value = fn(*call_args, **call_kwargs)
            result = repr(value)
        except Exception as e:  # behavior includes how it fails
            exception = "%s: %s" % (type(e).__name__, e)
    return Observation(result, exception, tuple(fx.trace), dict(ctrl.counts))


def classify(observations: List[Observation]) -> str:
    """Name the dominant nondeterminism source behind disagreeing runs."""
    agg = {"threads": 0, "time": 0, "entropy": 0}
    for o in observations:
        for k in agg:
            agg[k] += o.counts.get(k, 0)
    if agg["threads"] > 0:
        return CAUSE_CONCURRENCY
    if agg["time"] > 0:
        return CAUSE_TIME
    if agg["entropy"] > 0:
        return CAUSE_ENTROPY
    return CAUSE_UNKNOWN


@dataclass
class SelfCheck:
    deterministic: bool
    cause: Optional[str] = None          # set when not deterministic
    witness: Optional[Tuple] = None      # the input that exposed the flicker


def self_check(fn: Callable, inputs: List[Tuple], fixtures: Dict = None) -> SelfCheck:
    """Run `fn` RUNS_PER_INPUT times per input; flag if any input flickers."""
    for args in inputs:
        runs = [observe(fn, args, fixtures) for _ in range(RUNS_PER_INPUT)]
        keys = {r.key() for r in runs}
        if len(keys) > 1:
            return SelfCheck(False, classify(runs), args)
    return SelfCheck(True)


@dataclass
class Diff:
    equivalent: bool
    witness: Optional[Tuple] = None      # input where they diverged
    original: Optional[Observation] = None
    refactored: Optional[Observation] = None


def diff(original: Callable, refactored: Callable,
         inputs: List[Tuple], fixtures: Dict = None) -> Diff:
    """Compare original vs refactored Observation by Observation."""
    for args in inputs:
        o = observe(original, args, fixtures)
        r = observe(refactored, args, fixtures)
        if o.key() != r.key():
            return Diff(False, args, o, r)
    return Diff(True)
