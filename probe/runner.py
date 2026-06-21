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
from .generators import UnsupportedSignature, generate
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
    detail: Optional[str] = None    # human-readable divergence summary
    # integrity flags
    false_positive: bool = False    # said divergent, author expected equivalent
    missed_catch: bool = False      # said equivalent, author expected divergent
    cause_mismatch: bool = False    # unverifiable but wrong/unexpected cause
    unexpected_unverifiable: bool = False


def _dedup(rows: List[tuple]) -> List[tuple]:
    seen = set()
    out = []
    for args in rows:
        marker = repr(args)  # args may contain unhashable values (lists, dicts)
        if marker not in seen:
            seen.add(marker)
            out.append(args)
    return out


def run_unit(unit: Unit) -> UnitResult:
    seeds = list(unit.seeds)
    try:
        generated = generate(unit.original)
    except UnsupportedSignature as e:
        # No strategy for these inputs. If the author supplied seeds we still
        # check those; otherwise we honestly report "unsupported" rather than
        # invent inputs and emit a meaningless verdict.
        if not seeds:
            return UnitResult(unit, "unsupported", cause=str(e))
        generated = []

    inputs = _dedup(seeds + generated)

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
    if d.original is not None and d.refactored is not None:
        res.detail = "%s  ->  %s" % (d.original.summary, d.refactored.summary)
    return res


@dataclass
class Report:
    results: List[UnitResult]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def verifiable(self) -> int:
        # A trustworthy verdict was reached (equivalent or divergent). Both
        # "unverifiable" (nondeterministic) and "unsupported" (no inputs) count
        # against coverage — they are changes we could not vouch for.
        return sum(1 for r in self.results
                   if r.verdict in ("equivalent", "divergent"))

    @property
    def unsupported(self) -> int:
        return sum(1 for r in self.results if r.verdict == "unsupported")

    @property
    def unverifiable(self) -> int:
        return sum(1 for r in self.results if r.verdict == "unverifiable")

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

_GLYPH = {"equivalent": "=", "divergent": "x",
          "unverifiable": "?", "unsupported": "-"}


def _line(r: UnitResult) -> str:
    g = _GLYPH[r.verdict]
    detail = ""
    if r.verdict == "unverifiable":
        detail = "cause=%s" % r.cause
    elif r.verdict == "unsupported":
        detail = "(no inputs) %s" % (r.cause or "")
    elif r.verdict == "divergent":
        detail = "caught @ %r" % (r.witness,)
        if r.detail:
            detail += "  [%s]" % r.detail
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
    out.append("Units                  : %d" % report.total)
    out.append("Verifiable coverage    : %.0f%%  (%d/%d got a trustworthy verdict)"
               % (report.coverage * 100, report.verifiable, report.total))
    out.append("  unverifiable (flicker): %d" % report.unverifiable)
    out.append("  unsupported (no input): %d" % report.unsupported)
    out.append("Divergences caught     : %d" % report.caught)
    out.append("False positives        : %d" % report.false_positives)
    out.append("Missed catches         : %d" % report.missed_catches)
    out.append("Misclassified          : %d" % report.misclassified)

    out.append("Coverage caveat        : corpus-relative on a hand-built "
               "stand-in; NOT a real-world estimate (see README)")

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
