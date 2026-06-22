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

## 8. Targeted-wrapping capture (removes the profiler tax)

The original capture used a global `sys.setprofile`, which fires on EVERY call in
the process — pytest's own machinery generates millions — so it was slow and
needed an event-budget safety valve that, tuned low, *under-captured* normal
suites. Replaced with an import hook (a `sys.meta_path` finder) that wraps ONLY
the target modules' functions and methods as they import. Overhead now lands
solely on calls into the code under test; the event budget is gone.

- Keys come from `__qualname__` at wrap time (accurate for methods, classmethods,
  staticmethods; closures/`<locals>` are skipped — no more `caseinsensitive`-style
  not-comparable noise).
- The wrapper binds args+kwargs to a positional values list (defaults applied),
  so the capture format and replay are unchanged.
- A per-key "full" set short-circuits recording once a function hits its sample
  cap, so a stress suite calling one method millions of times stays cheap.

Effects: the sortedcontainers stress capture that *hung* under the profiler now
finishes in seconds; sortedcontainers coverage rose 86% -> 94% (cleaner method
wrapping, 0 not-comparable); inflection stays 100% with all divergences caught.
## 9. Public-interface snapshots for stateful classes

Previously `canonical(obj)` for a general object compared its private
`__dict__`/`__slots__`, or refused (`opaque`). Two problems: (a) comparing
private internals is **representation-sensitive** — a refactor that swaps the
internal layout (e.g. linked-list -> OrderedDict) while preserving observable
behavior would FALSE-POSITIVE as `divergent`; (b) objects with opaque internals
gave low coverage.

Change (`probe/canonical.py`, mirrored in `probe/equality.py`): before the
private-state fallback, snapshot an object by its OBSERVABLE public interface
when a **side-effect-free** one exists:

- `collections.abc.Sequence` (not str/bytes — handled earlier): snapshot ordered
  contents via iteration. For these, `__iter__` is the contract for "the
  contents," and the contents ARE the behavior — representation-independent.
- `collections.abc.Set`: snapshot order-normalized contents.
- Public (non-`_`-prefixed) attributes are read from the object's own
  `__dict__`/`__slots__` storage (never descriptors/properties, which could
  compute or mutate) and included in the snapshot.

Soundness — why no false positives and no missed catches:

- **No false positives across a refactor.** Same public class + same observable
  contents + same public attrs -> identical snapshot, even if `__dict__` differs.
  This is exactly the representation-change case that the private path got wrong.
  (Test: `test_internal_repr_change_canonicalizes_equal`.)
- **No missed catches.** The snapshot keys on the class qualname AND the full
  contents AND public attrs, so different contents, a different container kind,
  or a changed public attribute all canonicalize NOT-equal. (Tests:
  `test_different_observable_contents_not_equal`,
  `test_public_attributes_included_in_snapshot`.) In replay, base/head are the
  same class, so the qualname key never masks a real change.
- **Mappings are excluded.** Materializing a mapping's items calls
  `__getitem__`, which MUTATES LRU-style caches — a side effect that would
  corrupt the snapshot and break determinism. Mappings fall back to private-state
  comparison (or refuse). Verified the read path never touches `__getitem__`
  (`test_mapping_not_read_via_getitem`).
- **No regression.** When no safe public interface exists, the existing private
  `__dict__`/`__slots__` path runs unchanged (so SortedList-style private
  comparisons still work), and a truly opaque object (no public view, no state)
  still refuses (`test_opaque_with_no_observable_still_refuses`,
  `test_private_only_object_still_uses_private_state`). A broken
  `__iter__`/`__getitem__` is caught and falls back rather than guessing.

Limitations: the Set path in `equality.py` compares contents as a `frozenset`,
so set members without a real `__eq__` degrade to identity comparison — this can
only produce a conservative NOT-equal, never a false positive. The benefit is
scoped to Sequence/Set; arbitrary domain objects whose observable interface is
methods (not iteration) still fall back to private state or refuse.
## 10. Capturing the entry-point script (`__main__`)

The import hook can only wrap modules that are *imported*. The script you run
directly (`python myscript.py`) executes as module `__main__` — its top-level
functions are never imported, so `probe capture --modules __main__ -- python
myscript.py` captured nothing from the script's own code. Fixed by adding a
*scoped* `sys.setprofile` that records ONLY calls whose defining module
(`frame.f_globals['__name__']`) matches a target. It is installed **only when the
entry module is itself a target** (detected via `sys.modules['__main__'].__name__`
at hook-install time), so:

- A normal test-runner invocation (targets = imported library modules) never
  installs the profile — the import-hook path is untouched and pays zero
  profiler tax. A regression test asserts `sys.getprofile() is None` in that case.
- When the profile *is* on (a single app run, not millions of pytest-internal
  calls), the callback filters on `__name__` before any work, so non-target calls
  cost one dict lookup + a membership test and are dropped.

Records use the identical format and keys as the import-hook path
(`__main__::qualname`, a pickled positional values list with defaults applied;
varargs fall back to positional-only; `<locals>`/lambdas and class/module bodies
are skipped via `CO_OPTIMIZED`). The args-binding/dedup/cap logic is shared
(`_store`), so captures merge and replay identically. Exact method qualnames work
even pre-3.11 (no `code.co_qualname`) via a lazily-built code→qualname index over
the entry module's namespace. The hook is fully defensive: any failure to record
is swallowed and never disturbs the script under capture.
