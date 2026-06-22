# How it works

Selfsame answers one question soundly: **do two versions of this code behave the same on the
inputs I actually use?** It does that in three stages — capture, replay, compare — and refuses
to answer whenever a sound answer isn't possible.

## The pipeline

```
capture                         replay                          compare
────────                        ──────                          ───────
run your tests/app with a       check out each version as a     turn each result into a
hook that records the real      git worktree (or read it from   cross-process canonical form
arguments to target functions   a snapshot) and re-run the      and compare structurally;
  → inputs (pickled)            SAME inputs in an isolated       refuse if it can't be
                                subprocess per version          compared deterministically
```

1. **Capture** (`probe/_capture_hook.py`, `probe/capture.py`). A capture hook is injected via
   a generated `sitecustomize` on `PYTHONPATH`, so it loads into every process your command
   spawns. It wraps only your *target* modules' functions/methods and records their bound
   arguments (the receiver `self` included) — keyed by `module::qualname`. Because the inputs
   come from a real run, **no type hints or input generation are needed**, and methods,
   packages, and relative imports all work.

2. **Replay** (`probe/replay.py`, `probe/_replay_worker.py`). Each version is materialized —
   a base/head pair as `git worktree`s for `verify`, or the frozen baseline from the snapshot
   file for `drift` — and every captured input is re-run in a **fresh subprocess per
   version**, so two versions of the same package never share an interpreter. Checks run in
   parallel; a function that exceeds `PROBE_WORKER_TIMEOUT` is reported `timeout`, never a
   false pass.

3. **Compare** (`probe/canonical.py`). Each observation — return value, exception, **and the
   receiver's post-call state** for methods — is converted to a JSON canonical form and
   compared. Two results are equal iff their canonical forms are equal.

## What "behavior" means here

Behavior is compared **structurally**, not by `repr()`:

- Atomics handle the awkward cases (`nan`, `-0.0`); containers are order-normalized for
  sets/dicts.
- Callables and classes are identified by `module`+`qualname`, so caches that store functions
  compare correctly.
- Lazy iterators/generators are materialized up to `PROBE_ITER_CAP` and compared as the
  sequence they yield; beyond the cap they're refused as opaque.
- Stateful objects are compared by an **observable, side-effect-free** public snapshot when
  one exists (e.g. a Sequence's contents), otherwise by their private `__dict__`/`__slots__`
  state — and if neither can be read safely, they're refused rather than guessed.
- For methods, the **post-call `self`** is part of the verdict, so a refactor that changes how
  a method mutates its receiver is caught.

Determinism is enforced before comparison: each input is run twice and, under a controlled
harness (frozen clock, seeded entropy), checked for agreement. If the two runs disagree, the
input is nondeterministic and the function is refused.

## The soundness model

A black-box checker can't *prove* equivalence — the input space is infinite. So the one thing
Selfsame must never do is claim equivalence when behavior actually differs. It earns that by
**refusing** anything it can't compare deterministically:

| refused as `unverifiable` when… | why |
|---|---|
| the function does **uncontrolled I/O** (file/socket) | not reproducible across runs |
| it **starts a thread** | a race that didn't manifest is not a guarantee |
| two runs of the same input **disagree** (nondeterminism) | uncontrollable |
| it returns an **opaque** value (no safe structural view) | can't be compared, won't be guessed |

We measured this honestly on a stratified, not-cherry-picked corpus
(`experiments/measure.py`):

| | naive tally | reality |
|---|---|---|
| before soundness work | 75% "verifiable" | 42% trustworthy, **33% confidently wrong** |
| after soundness work | 50% "verifiable" | **50% trustworthy, 0% confidently wrong** |

The trade is explicit: soundness *lowers* coverage (it refuses more) but drives "confidently
wrong" to zero. A green result is one you can rely on. See
[experiments/FINDINGS.md](../experiments/FINDINGS.md) for the full validation across real OSS
repos.

## Two ways to get inputs

| | `capture` / `verify` / `snapshot` (recommended) | `check` (legacy) |
|---|---|---|
| inputs | recorded from a real run | generated from type hints |
| needs type hints? | no | yes |
| packages / relative imports | yes | limited |
| methods / stateful classes | yes | no |
| when to use | real code with a test suite or app run | small, typed, pure functions |

On real-world untyped code, generation scores near 0% coverage (functions have no usable
hints) — which is why capture-replay is the main path. Capturing real inputs from an existing
test suite turns that into 100% sound auto-verify on the same code, because the inputs come
from your tests, not from guessing.

## Determinism guarantees, in short

- `PYTHONHASHSEED=0` in replay workers → stable hash/set ordering across processes.
- Arguments are deep-copied per run, so a mutating call can't taint the next run, and the
  post-call receiver state can be read.
- Each version runs in its own subprocess from its own worktree/snapshot — true version
  isolation, contained crashes.

Next: [Limitations](limitations.md) — the boundaries of all this.
