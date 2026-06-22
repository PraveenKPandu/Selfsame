# Coverage Probe — go/no-go findings

The question: is deterministic behavior-equivalence checking worth building as a
real tool? We made the engine sound, then measured it on constructed and real
corpora.

## 1. Soundness is achievable, but trades hard against coverage

On a stratified constructed corpus (`measure.py`):

| | naive "verifiable" | trustworthy | confidently wrong |
|---|---|---|---|
| naive engine | 75% | 42% | **33%** |
| after soundness work | 50% | **50%** | **0%** |

A black-box checker cannot prove equivalence, so the bar is "never confidently
wrong." We reached 0% false confidence by refusing uncontrolled I/O, refusing any
thread use, and mining code literals for inputs. The price: it refuses ~half of
even a favorable corpus.

## 2. On REAL repos and REAL commits, current coverage is ~0%

`real_repo.py` walks a file's git history and checks every top-level function
whose body actually changed.

| repo | typed? | changed funcs | sound auto-verify | blocker |
|---|---|---|---|---|
| inflection (`inflection.py`) | now, not historically | 49 | **0%** | 100% unsupported — untyped at refactor time |
| httpx (`httpx/_utils.py`) | yes | 43 | **0%** | 100% extraction error — relative imports |

Two different real-world walls, same result:

- **Generation wall.** The refactors happened before the code was typed.
  Hint-driven generation produces no inputs → everything `unsupported`. (Even
  httpx's *current* typed signatures use `str | bytes` unions our generator
  doesn't handle on 3.9.)
- **Extraction wall.** Real code lives in packages with relative imports; the
  naive "exec the source text" loader can't resolve `from . import x` → every
  function errors at load.

Neither wall is the *concept* failing — both are engineering gaps. But they are
the gaps that decide real-world usefulness, and they are large.

## 3. What this implies

- The sound core works. The bottleneck is **getting real code in (extraction)**
  and **getting inputs (generation)** — not the equivalence check itself.
- In Python specifically, typing reality caps coverage: most code is untyped at
  the moment it's refactored.
- Fixing both walls is multi-week work: a package-aware extractor (check out each
  ref and import properly, isolate versions per subprocess) and a real input
  engine (Hypothesis + type inference, or runtime argument capture from an
  existing test run).

## 4. Recommendation

Conditional / narrow. The general "equivalence verifier for Python refactors" is
not viable today — real coverage is ~0% without large extraction + generation
investment, and even then Python's untyped reality caps it. The credible paths:

1. **Pivot the input problem:** don't generate inputs — *capture* them. Record
   real arguments from an existing test run or production trace, then replay both
   versions. This sidesteps the typing wall entirely and is where the leverage is.
2. **Pivot the language:** a typed-from-birth ecosystem (Go/Rust/TS) removes both
   walls (clean module imports, universal types). Test the hypothesis there.
3. **Stop** if the target is general untyped Python with existing test suites —
   "run the tests on both versions" beats this.

The decisive next experiment if continuing: wire runtime argument capture (option
1) and re-measure on a real repo's own test suite.

## 5. The pivot works: capture real inputs instead of generating them

We built it (`probe/capture.py`, `probe/replay.py`, `probe/_replay_worker.py`,
`probe/canonical.py`) and ran it on the same repo that scored 0%.

- **Capture:** a `sys.setprofile` hook recorded arguments to inflection's
  functions while its real test suite ran — **704 distinct arg-sets across 13
  functions from 455 passing tests, with zero type hints needed.**
- **Replay:** each version checked out as a `git worktree` (relative imports just
  work) and run in its own subprocess; observations compared structurally with
  the soundness rules intact.

Result on inflection, HEAD~20..HEAD, real captured inputs:

| metric | hint-generation (§2) | **capture-replay** |
|---|---|---|
| sound auto-verify | **0%** | **100%** (12/12 comparable functions) |
| equivalent | 0 | 9 |
| divergent (real changes caught) | 0 | 3 |

The 3 divergences are genuine historical behavior changes, caught at real inputs:
`pluralize("passerby")` (passerbies → passersby), `singularize("passersby")`,
`titleize("ana índia")` (Unicode capitalization fix). Verified by hand.

**Conclusion: capturing inputs from an existing test suite removes both walls at
once** — no type hints required (capture sidesteps generation), and worktree-based
loading handles package/relative imports. The sound core drops straight in. This
is the viable shape of the tool: *point it at a repo that has tests, and it tells
you which functions a refactor provably left unchanged — soundly.*

Remaining limits: only functions exercised by tests get inputs (coverage tracks
test coverage); cross-version comparison is state-structural (custom `__eq__`
honored only in-process).

## 6. Multi-repo validation (probe.verify on real repos)

Ran the one-command `probe.verify` against six real OSS repos, comparing ~30
commits of history per repo, inputs from each repo's own test suite.

| repo | profile | sound auto-verify |
|---|---|---|
| inflection | pure functions | 100% |
| slugify | string processing | 100% |
| boltons | utilities + OrderedMultiDict | 95% |
| toolz | functional + classes | 90% |
| sortedcontainers | heavy OO (SortedList) | 86% |
| cachetools | caching classes | n/a — HEAD needs Python 3.10+ |

**Zero false confidence on every repo.** Refusals all had honest causes (lazy
iterators over the safety cap, pickle-internal dunders, added/removed members).

Each repo surfaced real defects, all fixed:

- `src/` layout couldn't be imported in replay -> src-aware path insertion.
- Mutating methods were falsely "nondeterministic" (the determinism guard re-ran
  on the same `self`) -> deep-copy args per run, and compare the post-call `self`
  state so a method's mutation is part of the behavior checked.
- Test code was captured as noise (`--modules toolz` matched `toolz.tests.*`,
  flooding results with `TestCase` methods) -> exclude test modules; drop
  `<lambda>`/`<genexpr>`/`<locals>`.
- `argparse`/`sys.exit` crashed the worker (`SystemExit` not an `Exception`) ->
  treated as observable behavior.
- Iterator/generator returns were refused as opaque -> bounded materialization
  (`__iter__`, `irange`, `iterkeys`, ... now verify; unbounded -> still refused).
- A pathological (stress) suite made capture hang under the profile hook -> an
  event-budget safety valve uninstalls profiling after enough samples (a 5M-call
  loop drops from a long profiled run to ~1.6s).

A sixth repo (boltons) found no new bugs — the engine had stabilized.

## 7. Python-version matching is critical; replay performance

Running the probe means running the *target's* code and tests, so the probe must
use a Python the target supports. cachetools' HEAD requires `>= 3.10`; under the
machine's 3.9 its tests couldn't import and capture got nothing (0%). Under a
3.10 venv it produced a real verdict: **41% sound, 0 false confidence** (cache
classes carry opaque internal state in many captured instances -> soundly
refused; LFUCache operations on large captured caches hit the worker timeout ->
not-comparable, also honest).

Fixes:

- **`--python /path/to/pythonX.Y`** on `probe.verify` runs the test command and
  the replay workers under that interpreter (the orchestrator can stay on any
  Python). The target's `requires-python` is read from pyproject/setup.cfg and a
  mismatch is reported loudly ("declares requires-python >= 3.10 ... Pass
  --python ...") instead of silently capturing nothing.
- **Replay parallelism**: per-function checks run concurrently (each spawns two
  short-lived worker subprocesses). cachetools dropped from ~25 min to ~3 min.
- **Worker timeout** (`PROBE_WORKER_TIMEOUT`): a function whose replay can't
  finish in budget is reported `timeout` (not-comparable) — never a false pass.
- **Lower default capture budget** (600k events): a test runner's own startup
  generates millions of calls; the old 3M default let the profiler crawl.

Correctness note: an earlier attempt to cap replayed args per function (for
speed) silently dropped the inputs that trigger a divergence (e.g. inflection's
`pluralize("passerby")` at input #108) — a missed catch. So arg-capping is OFF
by default; speed comes from parallelism + timeout. Heavy repos can opt into
`PROBE_REPLAY_MAX_ARGS` for speed, explicitly trading divergence coverage.
