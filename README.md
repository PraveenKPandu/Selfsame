# Selfsame

[![CI](https://github.com/PraveenKPandu/Selfsame/actions/workflows/ci.yml/badge.svg)](https://github.com/PraveenKPandu/Selfsame/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/selfsame.svg)](https://pypi.org/project/selfsame/)
[![Python](https://img.shields.io/pypi/pyversions/selfsame.svg)](https://pypi.org/project/selfsame/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Sound behavior-equivalence verification for refactors.** Selfsame checks that a
refactor didn't change behavior, using your project's *own tests* for inputs: it
captures real call arguments while your tests (or app) run, replays both versions
of the code in isolated subprocesses, and compares the results structurally.

> **Guarantee: zero false confidence.** Selfsame never reports `equivalent` when
> behavior actually differs, or `divergent` when it doesn't. When it can't be
> sure, it *refuses* (`unverifiable` / `unsupported`) rather than guess.

## Install

```bash
pip install selfsame        # or: pipx install selfsame  ·  uv tool install selfsame
```

Pure standard library — no runtime dependencies. Installs the `selfsame` command
(`probe` is a kept alias).

## Quickstart

```bash
# Did my working-tree refactor change behavior vs main? (inputs come from your tests)
selfsame verify --base main --modules mypkg -- pytest -q

# CI mode: only the functions changed in this PR; non-zero exit if any diverged
selfsame verify --base main --modules mypkg --changed-only -- pytest -q
```

## Catching regressions without two branches (AI-driven dev)

When code is generated/changed continuously, you often don't have a clean "before"
branch — you have an **accepted build** and **whatever the next feature did to it**.
The danger is silent behavioral regression: a new feature ships, but existing
functionality quietly broke. Freeze the accepted behavior, then measure deviation:

```bash
selfsame snapshot --modules mypkg -- pytest -q   # freeze the accepted build
# ... develop / generate the next feature ...
selfsame drift                                   # exit 1 if behavior deviated
```

`drift` replays the *same* inputs the accepted build was characterized on against
the current code and reports each deviation (with base-vs-head witness and
`file:line`), writing the same agent-consumable `.selfsame/report.json`. It
measures *deviation*, not correctness — and only over the inputs your tests
exercised (the report names changed functions that have no test coverage).

## Commands

| command | what it does |
|---|---|
| `selfsame verify` | capture inputs from your tests, replay base vs head, per-function/method verdict (+ CI exit code) |
| `selfsame snapshot` | freeze the current (accepted) build's behavior to a baseline file |
| `selfsame drift`  | measure how much current code deviated from the snapshot baseline (no second branch) |
| `selfsame check`  | generate inputs and check two files or two git refs |
| `selfsame capture`| record real call arguments from any test or app command |
| `selfsame replay` | replay captured arguments across two git refs |
| `selfsame attach` | on-demand capture flush from a running, hook-enabled process |
| `selfsame fuzz`   | *(experimental)* capture-seeded differential fuzzing — mutate real inputs to find divergences your tests don't cover |
| `selfsame demo`   | run the built-in corpus end-to-end |

Each verdict is one of: `equivalent` (trustworthy pass), `divergent` (shows the
input + before→after), `unverifiable` (nondeterministic / uncontrolled I/O — with
cause), or `unsupported` (no input strategy). Everything also works as
`python -m probe.<cmd>`.

## Project

- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md) · Releasing: [RELEASING.md](RELEASING.md)
- Changelog: [CHANGELOG.md](CHANGELOG.md) · Security: [SECURITY.md](SECURITY.md)
- Design rationale & validation: [experiments/FINDINGS.md](experiments/FINDINGS.md)
- License: [MIT](LICENSE)

---

## How it works (the demo)

```bash
selfsame demo        # or: python3 run_probe.py
```

The demo runs the engine against a hand-built corpus (`units/`). It's pure stdlib
and re-execs once to fix `PYTHONHASHSEED=0` so hash/set ordering is controlled for
the whole run.

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

## Verify a refactor with the repo's own tests (the main path)

`probe.check` generates inputs, which fails on real code that is untyped or in a
package (see `experiments/FINDINGS.md`). The capture-replay path instead records
**real arguments from an existing test run** and replays both versions, loaded
package-aware from git worktrees. No type hints required; relative imports work;
**methods on classes are supported** (the receiver `self` is captured and rebuilt
against each version).

One command — run it from the repo root:

```bash
# "did my working-tree refactor change behavior vs main?"
python3 -m probe.verify --base main --modules mypkg -- pytest -q

# any test runner works (capture is injected into every spawned process)
python3 -m probe.verify --base v1.2 --head HEAD --modules mypkg -- python -m unittest
```

It captures inputs while the tests run, replays both versions, prints a
per-function/method verdict, and exits non-zero if any divergence is caught
(drop it in CI). `--head` defaults to your current working tree.

Because the probe **runs the target's code and tests**, it must use a Python the
target supports. Pass `--python /path/to/pythonX.Y` to run the tests and replay
workers under that interpreter; the repo's `requires-python` is checked and a
mismatch is reported loudly instead of silently capturing nothing:

```bash
python3 -m probe.verify --base main --modules cachetools \
        --python /path/to/py310/bin/python -- python -m pytest -q
```

Per-function replay runs in parallel; a function whose replay exceeds
`PROBE_WORKER_TIMEOUT` is reported `timeout` (not-comparable), never a false pass.
The summary separates `verified` (equivalent/divergent/unverifiable) from
`not verified` (skipped/error/timeout), so a busy machine's timeouts never look
like divergences. Exit codes: **0** none diverged · **1** a divergence ·
**2** usage · **3** with `--strict`, some function couldn't be verified.

For CI on a PR, add `--changed-only` to check just the functions whose body
changed between base and head (the rest are unchanged and uninteresting):

```bash
python3 -m probe.verify --base main --modules mypkg --changed-only -- pytest -q
```

### Output, CI & config

- On a divergence, the report shows **what differed** — `base: …` vs `head: …` —
  and a **minimized** witness (`--no-minimize` to skip), so you don't reproduce
  by hand.
- It also lists **changed-but-untested functions** (no captured inputs), so
  "all equivalent" stays honest about what wasn't checked.
- `--json-out report.json` and `--junit-xml report.xml` emit machine-readable
  results for pipelines and PR annotations.
- Put defaults in `[tool.selfsame]` (pyproject.toml) or `selfsame.toml` so
  `selfsame verify -- pytest -q` runs with no flags:
  ```toml
  [tool.selfsame]
  base = "main"
  modules = ["mypkg"]
  changed_only = true
  ```
- A function that **gained/lost a parameter** is reported as `interface-change`
  (not a behavior divergence), and an added/removed function as `skipped` — so
  runs across real feature history read cleanly.

### Real-world notes

- **Dynamically-versioned packages** (setuptools-scm / hatch-vcs, where
  `_version.py` is generated and git-ignored): the base version is checked out as
  a clean `git worktree`, which lacks generated files. Selfsame auto-copies
  git-ignored source files under your package dir into the worktree so it still
  imports; if a `ModuleNotFoundError` persists, build/generate the file first.
- **Heavy suites:** capture is bounded by `PROBE_CAPTURE_TIMEOUT` (default 300s)
  and `pytest-benchmark` is auto-disabled during capture (its timing loops blow
  up under the hook; keep it with `PROBE_KEEP_BENCHMARK=1`). Property-based
  (hypothesis) suites generate large call volumes — prefer `--changed-only`.
- **Coverage = test coverage:** Selfsame only checks the inputs your tests
  actually exercise. A change on a branch no test reaches is reported
  `equivalent` (true for those inputs) — it verifies, it doesn't prove.

### Inputs from a real app, not just tests

The capture command after `--` can be *anything* that runs your code — a script,
an integration harness, or a server — so inputs aren't limited to your test
suite:

```bash
# capture real call arguments from an actual app run
probe capture --modules mypkg --out caps.pkl -- python -m myapp run-some-workload
probe replay /path/to/repo main HEAD caps.pkl
```

For a long-running process (a server you exercise by hand), the hook flushes
captures every few seconds (`PROBE_CAPTURE_FLUSH_SECS`), so an abrupt SIGTERM/
SIGKILL still leaves a usable capture file.

You can also snapshot a running, hook-enabled process **on demand without
stopping it**:

```bash
# start the process under capture with a known dump directory
probe capture --modules mypkg --capture-dir ./caps --out caps.pkl -- python -m myapp serve
# ...later, in another shell, dump its current captures (process keeps running):
probe attach <pid> --capture-dir ./caps      # writes caps/cap-<pid>.pkl
```

`probe attach` sends the hook's flush signal (default SIGUSR1, override with
`PROBE_CAPTURE_FLUSH_SIGNAL`). This works only for processes started under the
hook — it does **not** inject into an arbitrary unmodified process (that needs
ptrace/gdb and is heavily restricted, especially on macOS under SIP; see
`experiments/FINDINGS.md` §9).

Capture and replay are also available separately (`probe.capture --modules M
--out caps.pkl -- <test cmd>` then `probe.replay <repo> <base> <head> caps.pkl`).

Measured: on `inflection` (untyped history) this turns `probe.check`'s 0% into
**100% sound auto-verify** (10 equivalent, 3 real behavior changes caught) across
20 real commits — because the inputs come from tests, not from guessing. Coverage
then tracks test coverage; the soundness rules (refuse uncontrolled I/O / threads
/ nondeterminism / opaque returns) are unchanged.

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
probe/verify.py                      CLI: one-command verify via the repo's tests
probe/check.py                       CLI: check a real refactor (two files or git refs)
probe/capture.py                     CLI: capture real call args from any test command
probe/attach.py                      CLI: on-demand flush of a running hook-enabled process
probe/_capture_hook.py               capture hook injected into spawned processes
probe/replay.py                      CLI: replay captured args across two refs (worktrees)
probe/canonical.py                   JSON canonical value form (cross-process compare)
probe/extract.py                     pull + pair functions from two module versions
probe/_worker.py                     isolated per-unit subprocess worker
probe/_replay_worker.py              per-version replay subprocess (functions + methods)
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

## Soundness (the verifier must never be confidently wrong)

A black-box checker can't *prove* equivalence (the input space is infinite), so
the one thing it must never do is say "equivalent" when behavior actually
differs. We measured this honestly: a stratified, not-cherry-picked corpus
(`experiments/`, run `python3 experiments/measure.py`) scores each verdict
against author ground truth.

| | naive tally | reality |
|---|---|---|
| before soundness work | 75% "verifiable" | 42% trustworthy, **33% confidently wrong** |
| after soundness work  | 50% "verifiable" | **50% trustworthy, 0% confidently wrong** |

The three fixes that closed the gap:

- **Uncontrolled I/O is refused, not certified.** The harness counts real file
  and socket access at runtime, and a static scan flags functions that *can*
  reach the network/subprocess even when the sampled inputs don't. Either way →
  `unverifiable (uncontrolled-io)`. (Code that routes I/O through the recorded
  Effects shim stays verifiable.)
- **Any thread use is unverifiable** — even if the sampled runs happened to
  agree. A race that didn't manifest is not a guarantee.
- **Literals are mined from the code** and fed back as inputs, so a bug hinging
  on a magic value (e.g. a parser that special-cases `"on"`) is caught instead
  of missed by a fixed value pool.

Residual honest gap: a function whose risky path is only reached by an input the
generator never produces (e.g. a valid URL string) can still read "equivalent".
This is the fundamental limit of example-based generation — Hypothesis / coverage
-guided generation is the real fix, and the I/O static scan already covers the
common cases.

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
