"""The core: observe, self-check determinism, diff versions, classify causes.

Observation is the unit of truth. Running a function produces an Observation =
(return value | exception) + the ordered trace of recorded effects. Two
Observations are "the same" iff their values, exceptions, and traces are
structurally equal (see probe.equality — NOT repr).

Pipeline per unit:
  1. self_check  -- run `original` RUNS_PER_INPUT times per input under a
                    controlled environment. If the runs disagree, the unit is
                    UNVERIFIABLE and we classify why (concurrency /
                    uncontrolled-time / uncontrolled-entropy / unknown). Negative
                    control: stable code must never be flagged.
  2. diff        -- only for deterministic units: run original vs refactored on
                    the same inputs; any Observation mismatch is a caught
                    behavioral divergence.

The controlled environment freezes a broad set of clock sources and seeds a broad
set of entropy sources. It is deliberately honest about its limits: the
`from datetime import datetime` capture-at-import pattern cannot be intercepted
globally, and per-instance `random.Random(...)` objects keep their own state.
Those gaps surface as `uncontrolled-time` / `uncontrolled-entropy` verdicts
rather than silent false confidence.
"""

from __future__ import annotations

import builtins
import datetime as _datetime
import inspect
import os
import random
import secrets
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .effects import FROZEN_NOW, Effects
from .equality import equal
from .generators import effects_param

RUNS_PER_INPUT = 3  # self-check repetitions

# Causes for an unverifiable verdict.
CAUSE_CONCURRENCY = "concurrency"
CAUSE_IO = "uncontrolled-io"
CAUSE_TIME = "uncontrolled-time"
CAUSE_ENTROPY = "uncontrolled-entropy"
CAUSE_UNKNOWN = "unknown"

_FROZEN_DT = _datetime.datetime.utcfromtimestamp(FROZEN_NOW)


@dataclass
class Observation:
    returned: bool                 # True if it returned, False if it raised
    value: Any                     # the raw return value (for structural compare)
    exception: Optional[str]       # "ExcType: message", or None
    trace: Tuple                   # ordered recorded effects (raw)
    counts: Dict[str, int]         # threads / time / entropy calls seen
    summary: str = ""              # human-readable, for reports only

    def same_behavior(self, other: "Observation") -> bool:
        if self.exception != other.exception:
            return False
        if self.exception is None:
            if not equal(self.value, other.value):
                return False
        return equal(list(self.trace), list(other.trace))


def _summarize(returned: bool, value: Any, exception: Optional[str],
               trace: Tuple) -> str:
    try:
        head = ("raises %s" % exception) if not returned else repr(value)
    except Exception:
        head = "<unreprable>"
    if len(head) > 80:
        head = head[:77] + "..."
    if trace:
        head += "  effects=%d" % len(trace)
    return head


class _Controlled:
    """Freeze the clock, seed entropy, and count the nondeterminism sources a
    unit reaches into. Restores everything on exit."""

    def __init__(self) -> None:
        self.counts = {"threads": 0, "io": 0, "time": 0, "entropy": 0}

    def __enter__(self) -> "_Controlled":
        c = self.counts
        self._saved: Dict[Any, Any] = {}

        def time_hit(value):
            def inner(*a, **k):
                c["time"] += 1
                return value
            return inner

        # --- clock sources ---
        self._time_patches = {
            "time": time_hit(FROZEN_NOW),
            "monotonic": time_hit(FROZEN_NOW),
            "perf_counter": time_hit(FROZEN_NOW),
            "process_time": time_hit(0.0),
            "time_ns": time_hit(int(FROZEN_NOW * 1e9)),
            "monotonic_ns": time_hit(int(FROZEN_NOW * 1e9)),
            "perf_counter_ns": time_hit(int(FROZEN_NOW * 1e9)),
        }
        for name, fn in self._time_patches.items():
            if hasattr(time, name):
                self._saved[("time", name)] = getattr(time, name)
                setattr(time, name, fn)

        # datetime: best-effort. Patches `datetime.datetime`/`datetime.date` on
        # the module so `import datetime; datetime.datetime.now()` is frozen.
        # Cannot catch `from datetime import datetime` (reference captured at
        # import) — that path stays live and will trip the time classifier.
        self._saved["dt.datetime"] = _datetime.datetime
        self._saved["dt.date"] = _datetime.date

        frozen_dt = _FROZEN_DT

        class _FrozenDateTime(_datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                c["time"] += 1
                return frozen_dt if tz is None else frozen_dt.replace(tzinfo=tz)

            @classmethod
            def utcnow(cls):
                c["time"] += 1
                return frozen_dt

            @classmethod
            def today(cls):
                c["time"] += 1
                return frozen_dt

        class _FrozenDate(_datetime.date):
            @classmethod
            def today(cls):
                c["time"] += 1
                return frozen_dt.date()

        _datetime.datetime = _FrozenDateTime
        _datetime.date = _FrozenDate

        # --- entropy sources (seed so the sequence is identical each run) ---
        random.seed(0)
        for fname in ("random", "randint", "randrange", "choice", "choices",
                      "shuffle", "uniform", "sample", "getrandbits"):
            if hasattr(random, fname):
                self._saved[("random", fname)] = getattr(random, fname)

        def wrap_entropy(fn):
            def inner(*a, **k):
                c["entropy"] += 1
                return fn(*a, **k)
            return inner

        for fname in ("random", "randint", "randrange", "choice", "choices",
                      "shuffle", "uniform", "sample", "getrandbits"):
            if ("random", fname) in self._saved:
                setattr(random, fname, wrap_entropy(self._saved[("random", fname)]))

        # os.urandom is the entropy floor for secrets, uuid4, and unseeded
        # random.Random — making it deterministic controls all of them.
        self._saved["urandom"] = os.urandom

        def det_urandom(n):
            c["entropy"] += 1
            return bytes((i * 37 + 11) & 0xFF for i in range(n))

        os.urandom = det_urandom

        # `random` (and therefore `random.SystemRandom`, which backs the whole
        # `secrets` module) captured `urandom` at import as `random._urandom`, so
        # patching os.urandom alone does NOT reach it. Patch the captured name
        # too — this is the subtle bit that makes secrets/SystemRandom honest.
        self._saved["random_urandom"] = getattr(random, "_urandom", None)
        if hasattr(random, "_urandom"):
            random._urandom = det_urandom

        # uuid: deterministic sequence + counted.
        self._saved["uuid4"] = uuid.uuid4
        self._saved["uuid1"] = uuid.uuid1
        _uuid_seq = {"n": 0}

        def det_uuid4():
            c["entropy"] += 1
            _uuid_seq["n"] += 1
            return uuid.UUID(int=_uuid_seq["n"], version=4)

        def det_uuid1(node=None, clock_seq=None):
            c["entropy"] += 1
            c["time"] += 1
            _uuid_seq["n"] += 1
            return uuid.UUID(int=_uuid_seq["n"])

        uuid.uuid4 = det_uuid4
        uuid.uuid1 = det_uuid1

        # secrets: route through counted, deterministic primitives.
        for fname in ("token_bytes", "token_hex", "token_urlsafe",
                      "randbelow", "randbits", "choice"):
            if hasattr(secrets, fname):
                self._saved[("secrets", fname)] = getattr(secrets, fname)
        if hasattr(secrets, "randbelow"):
            secrets.randbelow = wrap_entropy(self._saved[("secrets", "randbelow")])
        if hasattr(secrets, "choice"):
            secrets.choice = wrap_entropy(self._saved[("secrets", "choice")])
        if hasattr(secrets, "token_bytes"):
            secrets.token_bytes = wrap_entropy(self._saved[("secrets", "token_bytes")])
        if hasattr(secrets, "token_hex"):
            secrets.token_hex = wrap_entropy(self._saved[("secrets", "token_hex")])
        if hasattr(secrets, "token_urlsafe"):
            secrets.token_urlsafe = wrap_entropy(self._saved[("secrets", "token_urlsafe")])

        # --- threads: count starts, still really run them ---
        self._saved["thread_start"] = threading.Thread.start
        real_start = self._saved["thread_start"]

        def counting_start(thread_self, *a, **k):
            c["threads"] += 1
            return real_start(thread_self, *a, **k)

        threading.Thread.start = counting_start

        # --- uncontrolled real I/O: count file + network access. We cannot make
        # the real filesystem/network deterministic, so any hit here means the
        # unit is not verifiable (the sound stance: refuse, don't certify). Code
        # that routes I/O through the recorded Effects shim is unaffected.
        self._saved["open"] = builtins.open
        real_open = self._saved["open"]

        def counting_open(*a, **k):
            c["io"] += 1
            return real_open(*a, **k)

        builtins.open = counting_open

        self._saved["os_open"] = os.open
        real_os_open = self._saved["os_open"]

        def counting_os_open(*a, **k):
            c["io"] += 1
            return real_os_open(*a, **k)

        os.open = counting_os_open

        self._saved["sock_connect"] = socket.socket.connect
        real_connect = self._saved["sock_connect"]

        def counting_connect(sk, *a, **k):
            c["io"] += 1
            return real_connect(sk, *a, **k)

        socket.socket.connect = counting_connect
        return self

    def __exit__(self, *exc) -> None:
        for name in self._time_patches:
            if ("time", name) in self._saved:
                setattr(time, name, self._saved[("time", name)])
        _datetime.datetime = self._saved["dt.datetime"]
        _datetime.date = self._saved["dt.date"]
        for key, val in self._saved.items():
            if isinstance(key, tuple) and key[0] in ("random", "secrets"):
                setattr(globals()[key[0]] if key[0] == "secrets" else random,
                        key[1], val)
        os.urandom = self._saved["urandom"]
        if self._saved.get("random_urandom") is not None:
            random._urandom = self._saved["random_urandom"]
        uuid.uuid4 = self._saved["uuid4"]
        uuid.uuid1 = self._saved["uuid1"]
        threading.Thread.start = self._saved["thread_start"]
        builtins.open = self._saved["open"]
        os.open = self._saved["os_open"]
        socket.socket.connect = self._saved["sock_connect"]


def _build_call(fn: Callable, args: Tuple, fx: Effects):
    ep = effects_param(fn)
    if ep is None:
        return args, {}
    return args, {ep: fx}


def observe(fn: Callable, args: Tuple, fixtures: Dict = None) -> Observation:
    """Run `fn(*args)` once under control; capture result/exception + effects."""
    fx = Effects(fixtures)
    with _Controlled() as ctrl:
        call_args, call_kwargs = _build_call(fn, args, fx)
        returned = True
        value: Any = None
        exception: Optional[str] = None
        try:
            value = fn(*call_args, **call_kwargs)
        except (Exception, SystemExit) as e:  # SystemExit: argparse etc. exiting
            returned = False
            exception = "%s: %s" % (type(e).__name__, e)
    trace = tuple(fx.trace)
    return Observation(returned, value, exception, trace, dict(ctrl.counts),
                       _summarize(returned, value, exception, trace))


def classify(observations: List[Observation]) -> str:
    """Name the dominant nondeterminism source behind disagreeing runs."""
    agg = {"threads": 0, "io": 0, "time": 0, "entropy": 0}
    for o in observations:
        for k in agg:
            agg[k] += o.counts.get(k, 0)
    if agg["threads"] > 0:
        return CAUSE_CONCURRENCY
    if agg["io"] > 0:
        return CAUSE_IO
    if agg["time"] > 0:
        return CAUSE_TIME
    if agg["entropy"] > 0:
        return CAUSE_ENTROPY
    return CAUSE_UNKNOWN


@dataclass
class SelfCheck:
    deterministic: bool
    cause: Optional[str] = None
    witness: Optional[Tuple] = None


def self_check(fn: Callable, inputs: List[Tuple], fixtures: Dict = None) -> SelfCheck:
    """Run `fn` RUNS_PER_INPUT times per input; refuse to certify if it flickers
    OR touches an uncontrolled effect (threads / real I/O) even when it happens
    to be stable on the sampled runs. The latter is the soundness rule: a race
    that didn't manifest, or I/O that returned the same thing this time, is not a
    guarantee — so we refuse rather than emit a confident verdict.
    """
    if inputs:
        # Warm up lazy imports so import-driven file reads aren't mistaken for
        # the function's own I/O. This observation is discarded.
        try:
            observe(fn, inputs[0], fixtures)
        except Exception:
            pass

    for args in inputs:
        runs = [observe(fn, args, fixtures) for _ in range(RUNS_PER_INPUT)]
        if not all(runs[0].same_behavior(r) for r in runs[1:]):
            return SelfCheck(False, classify(runs), args)
        threads = sum(r.counts.get("threads", 0) for r in runs)
        io = sum(r.counts.get("io", 0) for r in runs)
        if threads > 0:
            return SelfCheck(False, CAUSE_CONCURRENCY, args)
        if io > 0:
            return SelfCheck(False, CAUSE_IO, args)
    return SelfCheck(True)


@dataclass
class Diff:
    equivalent: bool
    witness: Optional[Tuple] = None
    original: Optional[Observation] = None
    refactored: Optional[Observation] = None


def diff(original: Callable, refactored: Callable,
         inputs: List[Tuple], fixtures: Dict = None) -> Diff:
    """Compare original vs refactored Observation by Observation."""
    for args in inputs:
        o = observe(original, args, fixtures)
        r = observe(refactored, args, fixtures)
        if not o.same_behavior(r):
            return Diff(False, args, o, r)
    return Diff(True)
