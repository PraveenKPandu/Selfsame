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
test coverage); capture is in-process via pytest today; cross-version comparison
is state-structural (custom `__eq__` honored only in-process).
