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
run_probe.py                         entry point (fixes hash seed, runs)
probe/effects.py                     recorded, deterministic effect shims
probe/generators.py                  type-hint-driven input generation
probe/harness.py                     observe / self-check / diff / classify (the core)
probe/runner.py                      orchestration, metrics, thresholds, verdict
probe/model.py                       Unit dataclass
units/                               the stratified corpus + positive controls
```
# Selfsame
