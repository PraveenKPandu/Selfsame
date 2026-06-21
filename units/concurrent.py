"""Concurrent units. Even with the clock frozen and entropy seeded, thread
scheduling makes these flicker across runs, so the harness must flag them
UNVERIFIABLE with cause=concurrency. This is the engine refusing to vouch for
code it cannot pin down — the opposite failure mode from a false positive.

Both units release all their threads from a Barrier at once, so the contended
section is genuinely raced rather than run in launch order. The observable is the
scheduling-dependent *order* (an N! space), which makes the flicker reliable
instead of a probabilistic counter race that the GIL can mask.
"""

import threading

from probe.effects import Effects
from probe.harness import CAUSE_CONCURRENCY
from probe.model import EXPECT_UNVERIFIABLE, Unit

_PARTIES = 64  # threads released together; 64! orderings -> 3 runs never agree


def race_counter(n: int) -> tuple:
    """Unsynchronized appends to shared state: the result order races."""
    if n < 2:
        return tuple(range(max(n, 0)))
    out = []
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()        # all workers released simultaneously
        out.append(i)         # unsynchronized; final order depends on scheduler

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return tuple(out)


def concurrent_logger(n: int, fx: Effects) -> int:
    """Effect ordering depends on the scheduler, so the recorded trace flickers."""
    if n < 2:
        for i in range(max(n, 0)):
            fx.log(i)
        return n
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()
        fx.log(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return n


UNITS = [
    # refactored == original: these never reach the diff stage; the point is that
    # self-check refuses to certify them at all.
    Unit("race_counter", "concurrent", race_counter, race_counter,
         expect=EXPECT_UNVERIFIABLE, expect_cause=CAUSE_CONCURRENCY,
         seeds=[(_PARTIES,)]),
    Unit("concurrent_logger", "concurrent", concurrent_logger, concurrent_logger,
         expect=EXPECT_UNVERIFIABLE, expect_cause=CAUSE_CONCURRENCY,
         seeds=[(_PARTIES,)]),
]
