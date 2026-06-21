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
