"""The Unit dataclass: one original/refactored pair to be checked."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

# What the corpus author expects the probe to conclude about a unit. The probe
# validates its own verdicts against these so the demo can prove it is honest
# (no silent passes, no false alarms).
EXPECT_EQUIVALENT = "equivalent"      # deterministic + behavior preserved
EXPECT_DIVERGENT = "divergent"        # deterministic + behavior changed (caught)
EXPECT_UNVERIFIABLE = "unverifiable"  # not deterministic -> no trustworthy verdict


@dataclass
class Unit:
    """A single refactor under test.

    `original` and `refactored` share a signature. Every parameter is generated
    from its type hint (see probe.generators) except parameters annotated with
    `Effects`, which the harness injects so external I/O is recorded, not real.
    """

    name: str
    stratum: str  # pure | time | rng | io | stateful | concurrent | control
    original: Callable
    refactored: Callable
    expect: str = EXPECT_EQUIVALENT

    # Explicit inputs the author wants exercised (e.g. the boundary that trips a
    # positive control). Each is a tuple of the *generated* args, in signature
    # order, excluding any Effects parameter. Merged with type-hint generation.
    seeds: List[Tuple] = field(default_factory=list)

    # Canned responses for recorded effects, keyed by the call tuple
    # e.g. {("http_get", "https://x"): '{"ok": true}'}.
    fixtures: dict = field(default_factory=dict)

    # For concurrent/nondeterministic units, the cause the classifier must name.
    expect_cause: Optional[str] = None
