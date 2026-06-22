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

## 11. Attaching to a running process: what actually works, and what doesn't

Goal: snapshot the captures of a long-running process (e.g. a server) on demand
*without killing it*, and — as far as feasible — attach to a process that is
already running.

**What we built (robust, in scope): on-demand flush for hook-enabled processes.**
A process started under `probe capture -- <command>` (any process that ran
`import probe._capture_hook` with the capture env set) installs a signal handler
— **SIGUSR1 by default, overridable via `PROBE_CAPTURE_FLUSH_SIGNAL`** (name,
number, or `0`/`none` to disable). `probe attach <pid>` sends that signal; the
hook flushes its current records to `cap-<pid>.pkl` in its `PROBE_CAPTURE_DIR`
and the process keeps running. So "capture from a running server, snapshot now,
keep it running" works soundly: send the signal repeatedly to take successive
snapshots; the snapshot is just the standard per-process capture file, mergeable
and replayable like any other.

Design choices that keep it safe (the signal handler must never crash or hang the
target):
- The handler does **no work** beyond `Event.set()`. The actual flush (which
  takes `_lock` and writes a file) runs on a dedicated daemon thread. Doing the
  flush inside the handler would risk a deadlock — if the signal fires in the
  main thread while it already holds `_lock` inside `_record`, re-acquiring the
  non-reentrant lock in the same thread would hang. Setting an Event is
  re-entrancy-safe and lock-free.
- The handler is installed only from `install()`, only in the **main thread**
  (Python requires `signal.signal` to be called there), and the whole thing is
  wrapped in try/except so it can never break the target.
- It **chains to any pre-existing handler** for that signal, so it won't silently
  swallow an app's own SIGUSR1 use. (Still: pick a signal the app doesn't use, or
  set `PROBE_CAPTURE_FLUSH_SIGNAL` accordingly. SIGUSR1's *default* disposition is
  to terminate, so there's a tiny window during interpreter startup, before the
  hook installs, where a signal would kill the process — send the signal only
  after the process is up.)

`probe capture` now prints its capture dir and the exact `probe attach` command
to use, and takes `--capture-dir` so long-running sessions can dump to a known
path instead of an ephemeral temp dir.

**What we did NOT build, and why (honest limitation): injecting into a fully
unmodified, already-running process.** Truly instrumenting an arbitrary process
that was *not* started under the hook requires debugger/code-injection
(ptrace/gdb, pyrasite/madbg style: attach, call into the live interpreter, exec
the hook). This is fragile and platform-restricted:
- **Linux:** needs ptrace permission (`CAP_SYS_PTRACE` or a permissive
  `yama/ptrace_scope`); often blocked in containers/hardened hosts.
- **macOS:** SIP and code-signing typically block ptrace of the system/signed
  Python outright. On the dev machine here (`arm64`, **SIP enabled**, no `gdb`,
  `pyrasite` not installed; only Apple's signed `lldb`), attaching to a signed
  Python to inject code is not viable without disabling SIP and/or special
  entitlements. We did not ship a half-working injection path, because a probe
  whose cardinal rule is *zero false confidence* must not pretend to instrument a
  process it cannot.

**Recommended alternative for the unmodified-process case:** start the process
under `probe capture -- <command>` (or have it `import probe._capture_hook` with
the capture env set) from the beginning, then use `probe attach` to snapshot it
on demand. That is the sound, portable path.

## 12. No orphaned child processes on interruption

`probe verify` spawns a test command (pytest) and many replay-worker
subprocesses. If the orchestrator was killed with SIGTERM (e.g.
`pkill -f probe.verify`) or otherwise interrupted, those children reparented to
init and kept running — during development this saturated the machine (load 7+)
and silently starved later runs.

Fix (`probe/_procs.py`): every child is launched in its own session and tracked;
a SIGTERM/SIGINT/atexit reaper kills the whole child subtree (`killpg`) before the
orchestrator exits, then re-raises the signal with its default disposition.
Signal handlers are installed from the main thread (worker threads only register
their children). Verified end-to-end: SIGTERM to the orchestrator reaps its
sleeper child (0 survivors); unit tests cover run/timeout/terminate.

## 13. Capture-seeded differential fuzzing (prototype)

Capture-replay is sound but **bounded to inputs the tests already exercise**, so
its edge over "rerun the test suite on both versions" is thin. The original
vision was differential *fuzzing* (find divergences at inputs nobody tested), but
pure generation scored ~0% on real Python (§2). This prototype reconnects the
two: use the **real captured inputs as seeds**, mutate around them
(`probe/_mutate.py`) to reach inputs the tests never used, replay both versions,
and report divergences — partitioned into "seed" (test-reachable) vs "FUZZ-ONLY"
(beyond test coverage). Soundness is preserved: any input where either version is
nondeterministic / does uncontrolled I/O / spawns threads / returns opaque is
skipped, never reported.

Synthetic proof (a refactor with bugs only at `scale(0)` and `shout("")`, which
the tests don't cover):

| | capture-replay (test inputs) | capture-seeded fuzz |
|---|---|---|
| scale | equivalent (MISS) | **divergence @ (0,)** |
| shout | equivalent (MISS) | **divergence @ ('',)** |
| inc (truly equivalent) | equivalent | no divergence (no false positive) |

So fuzzing the seeds caught two behavior changes the test suite — and therefore
plain capture-replay — could never see, with no false positive on the equivalent
function.

Real-world (inflection HEAD~20..WORKTREE): 8 divergences at seed inputs, plus
**13 found only by fuzzing** (all in `titleize`, e.g. a doubled-unicode string).
No *new* broken function beyond the seeds here — inflection's refactor changed
behavior on test-reachable inputs, so the seeds already caught the affected
functions; fuzzing added breadth (more witnesses), not a new catch.

Takeaway: this is the piece that makes Selfsame meaningfully better than
re-running the test suite — but only when a behavior change **hides at an
untested edge**. It's a prototype (`probe fuzz`): mutation is a fixed
type-aware set, not coverage-guided; that's the next step if pursued.

## 14. Coverage-guided fuzzing + havoc mutation (next step)

The §13 prototype used a fixed one-shot mutation set — it can't introduce novel
bytes or drill nested branches. This adds AFL-style feedback:

- **Havoc mutation** (`probe/_mutate.py`): byte/char-level insert/delete/replace
  (alphabet drawn from seeds + printable), so the fuzzer can produce characters
  no seed contains. Seeded `random.Random` -> reproducible.
- **Coverage-guided loop** (`probe/_cgfuzz_worker.py`): trace line coverage of the
  target module via `sys.settrace`; keep a mutated input in the corpus if it hits
  a NEW line, then mutate *those* further. Drills through nested branches.
- `probe fuzz` is coverage-guided by default (`--oneshot` for the old mode).

Branchy proof — a bug at the *deep* path `s.startswith("k") and len(s) > 5`, with
seeds that never start with "k":

| | one-shot | coverage-guided |
|---|---|---|
| classify | **0 found** (can't introduce "k") | **divergence @ `('kbckbc',)`** (coverage 3 -> 6 lines) |

But on **data-driven** code (inflection's regex/word-table rules), pure line
coverage is the wrong signal: different inputs produce different *outputs* while
the same *lines* run, so coverage-guidance discarded them and found 0 (one-shot,
which keeps all mutations, found 13). Fix: **guide on output diversity too** —
keep an input if it hits a new line OR yields a new head output. With that:

| code style | guided result |
|---|---|
| cgdemo (branchy) | still finds the nested bug (FUZZ-ONLY) |
| inflection (data-driven) | 80 interesting inputs kept; 3 beyond-test divergences (was 0) |

Takeaway: coverage *and* output-diversity together make the guided fuzzer robust
across branchy and data-driven code, still sound (FUZZ-ONLY = real, io/threads/
nondeterministic/opaque inputs skipped). Next refinements if pursued: branch-edge
(not line) coverage, energy assignment / corpus scheduling, and dictionary tokens.

## 15. Fuzzer refinements: edge coverage, energy scheduling, dictionary tokens

The three follow-ups from §14, each proven on a minimal fixture that isolates
the capability:

1. **Branch-edge coverage** (`_cgfuzz_worker.py`): trace `(prev_line -> cur_line)`
   transitions instead of bare line hits. Strictly finer than line coverage —
   distinguishes different control-flow paths through the same lines (what AFL
   uses). Coverage keys renamed `seed_lines/total_lines -> seed/total`.

2. **Energy-weighted corpus scheduling** (`_cgfuzz_worker.py`): replace uniform
   `rng.choice(corpus)` with a weighted pick — `1/(1+times_chosen)` (drill fresh
   finds before over-explored seeds) times `1/(1+size)` (prefer smaller inputs).

3. **Dictionary tokens** (`_mutate.py`): `tokens_from_source()` mines str/int/
   float literals from the target module via `ast`; `mutate_one(..., tokens)`
   injects them (prob 0.3, type-matched, replace-or-splice for strings). Reaches
   exact-match branches havoc can't (`if cmd == "deploy"`).

Proof — each refinement isolated against one-shot:

| fixture (bug location)                       | one-shot | guided (refined) |
|----------------------------------------------|----------|------------------|
| nested `startswith("k") and len>5`           | 0        | found `('kbckbc',)`, edges 2->5 |
| exact-match `cmd == "deploy"` (mined literal)| 0        | found `('deploy',)` via dictionary |

Suite 75 -> 78 tests (token mining, bad-syntax fallback, token injection). Still
sound. Possible further work: branch-edge *hashing* (AFL's bucketed hit counts),
splice/crossover between corpus entries, and structural mutation of containers.

## 16. Fuzzer refinements II: bucketing, crossover, structural mutation

The three §15 follow-ups. Each is isolated with an A/B: the same guided fuzzer
with the one capability turned off, so the win is attributable, not incidental.

1. **AFL hit-count bucketing** (`_cgfuzz_worker.py`): count how many times each
   edge fires per run, bucket it (1,2,3,4-7,8-15,16-31,32-127,128+), and key
   coverage on `(edge, bucket)`. "Took this loop 8 times" is now distinct from
   "twice", so loop-depth-diverse inputs are retained.

2. **Splice/crossover** (`_mutate.py` `_crossover`): combine two energy-weighted
   parents — per position take one's value or the other's, splicing prefix+suffix
   for str/bytes. Merges a feature from one input with a feature from another.

3. **Structural container mutation** (`_mutate.py`): lists gain insert-at-position,
   subrange duplication, swap, reverse; dicts gain key add/del and value swap
   (was single-element mutate/del/append only).

Proof — each capability vs the same fuzzer with it disabled:

| fixture (bug location)                         | capability OFF | capability ON |
|------------------------------------------------|----------------|---------------|
| bug at exactly 7 loop iterations               | 0 (cov 8->8)   | found (cov 11->35) |
| `a.count("A")>=8 AND b.count("B")>=8`, split seeds | 0          | found `('AAAAAAAA','xBBBBBBBB')` |
| "mirror" list (first half == second half)      | 0              | found `([3,4,5,3,4,5],)` |

All three "OFF" columns are the full guided fuzzer (edge coverage + output
diversity + energy + dictionary) minus only the named capability — so each row
isolates exactly one refinement. One-shot finds 0 on all three. Suite 78 -> 84.
Still sound. Diminishing returns from here; the engine now covers the standard
greybox-fuzzer toolkit (coverage feedback, hit-count buckets, dictionary,
crossover, structural mutation, energy scheduling).

## 17. Usability hardening (from the real-repo evaluation)

The §16 fuzzer work was internal quality; this round fixes the three frictions
that actually stopped real users in the multi-repo evaluation (slugify / humanize
/ more-itertools / bidict). Each was a wall a casual user hit before getting a
verdict.

1. **Build-generated, git-ignored modules broke the base worktree.** A plain
   `git worktree add` materializes only tracked files, so a package whose
   `_version.py` is generated by setuptools-scm/hatch-vcs (git-ignored) failed to
   import on the base side — humanize was **35/35 error** with a cryptic
   `ModuleNotFoundError`. Fix: `_add_worktree` now copies git-ignored *source*
   files (scoped to the target package dirs, safe extensions, never build/cache)
   from the live working tree into the fresh worktree, plus a clear diagnostic if
   a missing-module error still occurs. (`probe/replay.py`)

2. **Capture had no timeout** → hypothesis/pytest-benchmark suites ran away
   (bidict pegged 8 cores ~40min). Fix: `PROBE_CAPTURE_TIMEOUT` (default 300s)
   bounds the capture command with a graceful SIGTERM-then-SIGKILL (the hook's
   periodic flush leaves partial inputs); pytest runs get `-p no:benchmark`
   appended (opt out `PROBE_KEEP_BENCHMARK=1`); a heavy-capture warning names
   hypothesis/benchmark and suggests `--changed-only`. (`probe/capture.py`,
   `probe/_procs.py`)

3. **timeout/error were indistinguishable from divergence.** Under load every
   function timed out and the wall of `timeout` rows looked like failures, while
   the exit code only flagged divergence (so "couldn't verify" == "verified
   clean"). Fix: rows are marked (`X` divergent, `!` error), the summary splits
   `verified -> equivalent/divergent/unverifiable` from `not verified ->
   skipped/error/timeout`, an explicit note names `PROBE_WORKER_TIMEOUT`, and
   `--strict` exits 3 when any function couldn't be verified (default stays
   0 clean / 1 divergent / 2 usage). (`probe/replay.py`, `probe/verify.py`)

Net: the soundness guarantee was already intact (the evaluation found zero false
confidence); these changes are about not failing silently or running away on the
packaging/test-suite realities of modern Python. Suite 86 -> 94 tests.
