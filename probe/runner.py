"""Orchestration, metrics, thresholds, verdict.

Runs every unit through the harness, computes verifiable coverage, and validates
the probe's own verdicts against each unit's declared expectation so the run is
self-auditing: any false positive, missed catch, or misclassification fails the
integrity check loudly instead of inflating the headline number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from . import harness
from .generators import generate
from .model import (EXPECT_DIVERGENT, EXPECT_EQUIVALENT, EXPECT_UNVERIFIABLE,
                    Unit)

# Real-probe band from the README: a result here means "promising, confirm in a
# typed language". Shown for context; not a pass/fail gate on the stand-in corpus.
CONFIRM_BAND = (0.40, 0.65)


@dataclass
class UnitResult:
    unit: Unit
    verdict: str            # equivalent | divergent | unverifiable
    cause: Optional[str] = None
    witness: Optional[tuple] = None
    # integrity flags
    false_positive: bool = False    # said divergent, author expected equivalent
    missed_catch: bool = False      # said equivalent, author expected divergent
    cause_mismatch: bool = False    # unverifiable but wrong/unexpected cause
    unexpected_unverifiable: bool = False


def _inputs_for(unit: Unit) -> List[tuple]:
    seeds = list(unit.seeds)
    generated = generate(unit.original)
    seen = set()
    inputs = []
    for args in seeds + generated:
        marker = repr(args)  # args may contain unhashable values (lists, dicts)
        if marker not in seen:
            seen.add(marker)
            inputs.append(args)
    return inputs


def run_unit(unit: Unit) -> UnitResult:
    inputs = _inputs_for(unit)

    sc = harness.self_check(unit.original, inputs, unit.fixtures)
    if not sc.deterministic:
        res = UnitResult(unit, "unverifiable", cause=sc.cause, witness=sc.witness)
        res.unexpected_unverifiable = unit.expect != EXPECT_UNVERIFIABLE
        res.cause_mismatch = (unit.expect_cause is not None
                              and sc.cause != unit.expect_cause)
        return res

    d = harness.diff(unit.original, unit.refactored, inputs, unit.fixtures)
    if d.equivalent:
        res = UnitResult(unit, "equivalent")
        res.missed_catch = unit.expect == EXPECT_DIVERGENT
        return res

    res = UnitResult(unit, "divergent", witness=d.witness)
    res.false_positive = unit.expect == EXPECT_EQUIVALENT
    return res


@dataclass
class Report:
    results: List[UnitResult]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def verifiable(self) -> int:
        return sum(1 for r in self.results if r.verdict != "unverifiable")

    @property
    def coverage(self) -> float:
        return self.verifiable / self.total if self.total else 0.0

    @property
    def caught(self) -> int:
        return sum(1 for r in self.results if r.verdict == "divergent")

    @property
    def false_positives(self) -> int:
        return sum(1 for r in self.results if r.false_positive)

    @property
    def missed_catches(self) -> int:
        return sum(1 for r in self.results if r.missed_catch)

    @property
    def misclassified(self) -> int:
        return sum(1 for r in self.results
                   if r.cause_mismatch or r.unexpected_unverifiable)

    @property
    def integrity_ok(self) -> bool:
        return (self.false_positives == 0 and self.missed_catches == 0
                and self.misclassified == 0)


def evaluate(units: List[Unit]) -> Report:
    return Report([run_unit(u) for u in units])


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

_GLYPH = {"equivalent": "=", "divergent": "x", "unverifiable": "?"}


def _line(r: UnitResult) -> str:
    g = _GLYPH[r.verdict]
    detail = ""
    if r.verdict == "unverifiable":
        detail = "cause=%s" % r.cause
    elif r.verdict == "divergent":
        detail = "caught @ %r" % (r.witness,)
    flag = ""
    if r.false_positive:
        flag = "  <-- FALSE POSITIVE"
    elif r.missed_catch:
        flag = "  <-- MISSED CATCH"
    elif r.cause_mismatch or r.unexpected_unverifiable:
        flag = "  <-- MISCLASSIFIED"
    return "  [%s] %-22s %-11s %s%s" % (g, r.unit.name, r.unit.stratum, detail, flag)


def render(report: Report) -> str:
    out: List[str] = []
    out.append("Coverage Probe — behavior-equivalence verifier")
    out.append("=" * 60)

    by_stratum: dict = {}
    for r in report.results:
        by_stratum.setdefault(r.unit.stratum, []).append(r)
    for stratum in sorted(by_stratum):
        out.append("")
        out.append("%s:" % stratum)
        for r in by_stratum[stratum]:
            out.append(_line(r))

    out.append("")
    out.append("-" * 60)
    out.append("Units                : %d" % report.total)
    out.append("Verifiable coverage  : %.0f%%  (%d/%d deterministic)"
               % (report.coverage * 100, report.verifiable, report.total))
    out.append("Divergences caught   : %d" % report.caught)
    out.append("False positives      : %d" % report.false_positives)
    out.append("Missed catches       : %d" % report.missed_catches)
    out.append("Misclassified        : %d" % report.misclassified)

    lo, hi = CONFIRM_BAND
    note = ("in %.0f-%.0f%% confirm band -> re-run in a typed language (Go)"
            % (lo * 100, hi * 100)) if lo <= report.coverage <= hi else \
           "outside confirm band (corpus is a tractable stand-in, not a real estimate)"
    out.append("Coverage note        : %s" % note)

    out.append("")
    verdict = "PASS — controls fired, zero false positives" if report.integrity_ok \
        else "FAIL — integrity check tripped (see flags above)"
    out.append("VERDICT: %s" % verdict)
    return "\n".join(out)


def main() -> int:
    from units import ALL_UNITS  # imported here so PYTHONHASHSEED is already fixed
    report = evaluate(ALL_UNITS)
    print(render(report))
    return 0 if report.integrity_ok else 1
