# Coverage Probe — Implementation

A runnable implementation of the go/no-go experiment for the behavior-equivalence
verifier. It measures **verifiable coverage**: the fraction of code changes where a
deterministic harness can make a trustworthy equivalence verdict.

## Run

```bash
python3 run_probe.py
```

No third-party dependencies (pure stdlib). It re-execs once to fix `PYTHONHASHSEED=0`
so hash/set ordering is controlled for the whole run.

## Check a real refactor

The demo above runs the engine against a hand-built corpus. To point it at
*actual* code — two versions of a module — use `probe.check`. It extracts the
top-level functions present in both versions, pairs the ones whose signatures
are unchanged, and checks each in an **isolated subprocess**:

```bash
# two files on disk
python3 -m probe.check before.py after.py

# two git refs + a path in the repo
python3 -m probe.check --git main HEAD app/calc.py
```

Try it on the bundled example (an equivalent refactor, one real bug, an
entropy-using function, an unannotated function, and a signature change):

```bash
python3 -m probe.check examples/calc_before.py examples/calc_after.py
```

Each matched function gets one verdict: `equivalent` (trustworthy pass),
`divergent` (shows the input + before→after), `unverifiable` (nondeterministic,
with cause), or `unsupported` (no input-generation strategy for its types). The
command exits non-zero when any divergence is caught, so it can gate CI. This is
the narrow-but-real slice: it works today on **deterministic functions with
type-hinted, generatable parameters** — not yet on stateful classes, I/O against
live systems, or cross-file refactors.

## What it does

For every unit (an `original` + a `refactored` function):

1. **Generates inputs** from type hints (`probe/generators.py`) plus any unit-supplied
   seed inputs. (Hypothesis is the production upgrade.)
2. **Self-checks determinism** (`probe/harness.py`): runs the *original* 3× per input
   under a controlled environment (frozen clock, seeded RNG, fixed hash seed, recorded
   I/O). If the three runs disagree, the unit is **unverifiable**, and the cause is
   classified (concurrency / uncontrolled-time / uncontrolled-entropy / unknown) by
   counting threads started and direct time/entropy calls. This is the negative control:
   stable code must never be flagged.
3. **Diffs the versions** (only on deterministic units): runs original vs refactored on
   the same inputs and compares observed behavior — return value **plus the ordered trace
   of external effects** plus exceptions. Any mismatch is a caught behavioral divergence.

Effects (`probe/effects.py`) are injected and recorded: the trace of external calls is
treated as part of behavior, so a refactor that changes *which* calls fire (or their
order) is detected, not hidden.

## What the result means

The included corpus (`units/`) is a **stratified stand-in** for real LLM-refactored OSS
code: pure, time/RNG, I/O, stateful, concurrent, plus three **positive controls** (refactors
that deliberately change behavior and must be caught). Running it demonstrates the engine
end-to-end and shows the controls firing:

- concurrency units → flagged unverifiable (cause: concurrency)
- positive controls → 3/3 caught (off-by-one, dropped zero-guard, changed default)
- everything else → verified equivalent, zero false positives

The 89% coverage on this corpus is **not** a real-world estimate — the mix is deliberately
tractable. The real number comes from swapping in real refactors (below).

## To run the real probe

Replace the corpus with real material:

1. Sample ~16 units from real OSS Python repos, stratified per the protocol (don't
   cherry-pick pure functions).
2. Generate each `refactored` version with an actual LLM ("refactor, preserve behavior").
3. Keep the three positive controls and the A-vs-A negative control.
4. For real I/O, swap the deterministic `Effects` stubs for `vcrpy`-style record-replay
   against real recorded responses.
5. Read the verdict; if it lands 40–65%, re-run a confirmation in a typed language (Go).

## Files

```
run_probe.py                         entry point for the corpus demo (fixes hash seed)
probe/check.py                       CLI: check a real refactor (two files or git refs)
probe/extract.py                     pull + pair functions from two module versions
probe/_worker.py                     isolated per-unit subprocess worker
probe/effects.py                     recorded, deterministic effect shims
probe/generators.py                  type-hint-driven input generation
probe/harness.py                     observe / self-check / diff / classify (the core)
probe/equality.py                    structural value equality (not repr)
probe/runner.py                      orchestration, metrics, thresholds, verdict
probe/model.py                       Unit dataclass
units/                               the stratified corpus + positive controls
examples/                            calc_before.py / calc_after.py for probe.check
tests/                               unit + end-to-end tests (python3 -m unittest discover -s tests)
```

## Honesty notes (what this engine does and does not guarantee)

- **Equivalence is structural, not `repr`-based.** Objects with only identity
  equality are compared by their `__dict__`/`__slots__` state; floats handle
  `nan`/`-0.0`; an object we cannot introspect is reported *not provably equal*
  rather than guessed.
- **Determinism control is broad but bounded.** The harness freezes the clock
  (`time.*`, `time.*_ns`, `datetime.now/utcnow/today`) and seeds entropy
  (`random`, `os.urandom`, `random._urandom`, `uuid4/1`, `secrets`). It cannot
  intercept `from datetime import datetime` (reference captured at import) or
  per-instance `random.Random(...)`; those surface as an *unverifiable* verdict,
  never as silent false confidence.
- **Unsupported inputs are refused, not faked.** If the generator has no strategy
  for a parameter's type, the unit is reported `unsupported` (counts against
  coverage) instead of fed a placeholder value.
- **Input generation is bounded, not exhaustive.** The stdlib generator caps the
  number of input combinations per function, so an "equivalent" verdict means
  "equivalent on the inputs tried", not a proof. Hypothesis is the intended
  upgrade for real coverage.
- **Isolation is per-unit, not per-call.** Each function is checked in its own
  subprocess (crashes and runaway loops are contained, side effects are kept out
  of the parent), but the function still runs several times *within* that
  process. True per-call sandboxing (containers) is future work.
- **The coverage % is corpus-relative.** It is a property of this hand-built
  stand-in corpus, not a real-world estimate. See "To run the real probe".
# Selfsame
# Selfsame
