# Limitations

Selfsame is deliberately honest about what it does and doesn't promise. Read this before you
rely on a green result.

## It verifies deviation, not correctness

Selfsame tells you whether behavior **changed** (or whether two implementations **agree**) —
not whether the behavior is **right**. Proving correctness needs an independent spec or
oracle, and a deterministic tool can't supply one (especially if an AI wrote the spec too).
A `divergent` verdict means "this changed," and `equivalent` means "this didn't change on the
inputs tried" — neither means "this is correct."

## Coverage equals test coverage

The inputs come from a real run of your code, so Selfsame only checks **what your tests (or
app run) actually exercise**. A behavior change on a branch no input reaches is reported
`equivalent` — true for the inputs tried, but it didn't probe that path.

This is surfaced, not hidden: the report lists **changed functions with no captured inputs**
(`unverified_changed`) so the blind spot is explicit. The fix is more test coverage (or the
experimental `fuzz` command, which mutates real inputs to reach untested edges). Value
compounds as your test suite grows.

## A green result is "equivalent on the inputs tried," not a proof

The input space is infinite; Selfsame compares the inputs it captured. It is sound (it never
*falsely* claims equivalence on an input it did check), but "equivalent" is scoped to those
inputs — not a universal proof.

## Soundness lowers coverage on purpose

To guarantee zero false confidence, Selfsame **refuses** anything it can't compare
deterministically — uncontrolled I/O, threads, nondeterminism, opaque return/state values.
On such functions you get `unverifiable` (with the cause), not a verdict. That's the
intended trade: fewer answers, but every answer is trustworthy. Route I/O through a recorded
shim, or make the function deterministic, to bring it back into scope.

## Stateful objects and cross-version drift

- Objects are compared by an observable public snapshot when one exists, otherwise by private
  `__dict__`/`__slots__` state. An object with an empty-but-present `__dict__`/`__slots__` is
  *empty state* (comparable); only an object with **no** introspectable state at all (e.g.
  `object()`, some C types) is refused — never guessed.
- Common value types — `datetime`/`date`/`time`/`timedelta`, `Decimal`, `complex`, `Fraction`,
  `Path`, `re.Match`/`Pattern` — are compared by their **observable form** (and so is any
  object/dict/list that contains them).
- Comparing a **captured object across versions** relies on it pickling in one version and
  reconstructing in the other. If a class's internal layout changes a lot between versions
  (e.g. across many commits), the captured `self` may not reconstruct — reported as `error`,
  never as a false verdict. (Same-version `drift` is unaffected.)
- Mappings are not read via the public-snapshot path (their `__getitem__` can mutate LRU
  caches), so cache-like classes fall back to private state or are refused.

## Determinism control is broad but bounded

The harness freezes the clock and seeds entropy (`time.*`, `datetime.now/utcnow/today`,
`random`, `os.urandom`, `uuid`, `secrets`). It also freezes `from datetime import
datetime/date` references captured at import across loaded modules, and makes unseeded
`random.Random()` instances deterministic. It still **cannot** intercept an aliased import
(`from datetime import datetime as dt`) or C-level time/entropy inside an extension; those
surface as `unverifiable`, never as silent false confidence.

## Operational notes

- **It runs your code and tests.** Use a Python your project supports (`--python`); a
  `requires-python` mismatch is reported loudly.
- **Heavy suites.** Capture is bounded by `PROBE_CAPTURE_TIMEOUT`; `pytest-benchmark` is
  auto-disabled during capture (its timing loops explode under the hook). Property-based
  (Hypothesis) suites generate huge call volumes — prefer `--changed-only`.
- **Build-generated, git-ignored files** (e.g. setuptools-scm/hatch-vcs `_version.py`):
  Selfsame copies git-ignored source under your package dir into the base worktree so it
  imports; if a `ModuleNotFoundError` persists, generate/build the file first.
- **`drift --changed-only`** replays only *directly* changed functions, so a divergence in an
  unchanged caller of a changed callee can be missed — run full `drift` periodically to be
  exhaustive.

## Assumption adjudicator (experimental)

`selfsame adjudicate` ([docs](adjudicator.md)) is **experimental** and has its own boundaries:

- It is a **judge, not a detective** — it adjudicates assumptions *you nominate*, it does not
  discover them. Enumeration (symbol resolution, linters) is deliberately out of the core.
- A `not-load-bearing` result is scoped to the captured inputs and the tried violations, and
  only meaningful if the boundary was actually invoked — the report flags `boundary not
  invoked` when a nomination never took effect (so it can't masquerade as "tolerant").
- It proves *load-bearingness*, not *correctness* — same as the rest of the tool.

## Not yet / out of scope

- Correctness checking, spec verification, or "is this the right output" — by design.
- Per-call sandboxing (containers). Isolation is per-version-subprocess, not per-call.
- N-way comparison of many fresh AI generations (a heuristic, non-sound idea — deliberately
  not built; see [experiments/FINDINGS.md](../experiments/FINDINGS.md) §22).

For why the verdicts you *do* get are trustworthy, see [How it works](how-it-works.md).
