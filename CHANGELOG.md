# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **Repository restructured into a polyglot monorepo.** The Python implementation moved to
  `packages/python/` (importable package name unchanged; `pip install selfsame` ships the
  same package). CI and the PyPI release workflow now build from there. No behavior or API
  change for users.

### Added
- **Per-package release pipelines.** Each language publishes independently on its own tag
  prefix: Python `vX.Y.Z` → PyPI (existing), Node `node-vX.Y.Z` → npm via Trusted Publishing
  + provenance (`release-node.yml`), Java `java-vX.Y.Z` → a GitHub Release with the built jar
  (`release-java.yml`; Maven Central deferred until namespace + GPG setup). One-time setup and
  cut steps are in `RELEASING.md`.
- **JavaScript / TypeScript implementation** (`packages/node/`, alpha) — the second language.
  Implements the Selfsame Protocol for the JS runtime: a JS-aware canonical form, the
  comparator and soundness gate (passing the cross-language conformance suite), a determinism
  harness (freezes `Date`/`Math.random`/`crypto`/timers, refuses uncontrolled I/O & threads),
  and an end-to-end capture → replay → compare pipeline that catches real regressions.
  Commands: `selfsame verify --base <ref> -- <cmd>` (git-worktree, base-vs-working-tree, the
  recommended one-command flow), `selfsame snapshot` / `selfsame drift` (freeze an accepted
  build, then measure drift — no second branch; the AI-velocity loop), plus `selfsame capture`
  / `selfsame replay` (directory pair, no git needed). Every verdict-producing command writes
  an agent-consumable `.selfsame/report.json`. Capture covers CommonJS (named + bare default
  function exports) and **ES modules** (`capture --esm`, Node ≥ 20.6 — a `module.register`
  loader reads export names with es-module-lexer and re-exports them wrapped, no source
  mutation or double-execution); richer method support is in progress. Node ≥ 18; one small
  dependency (es-module-lexer) for the ESM path. **Published to npm** as `selfsame` (alpha, under the `next` tag):
  `npm install -g selfsame@next`.
- **Java (JVM) implementation** (`packages/java/`, alpha) — the third language, now
  **end-to-end**. The canonical form, comparator, and soundness gate are pure JDK (incl. a
  tiny dependency-free JSON parser) and **pass the cross-language conformance suite**; on top
  sits a `-javaagent` (ByteBuddy) capture → replay → compare pipeline (`selfsame capture` /
  `selfsame replay`) for public static methods, proven to catch real regressions. ByteBuddy is
  shaded into the agent jar, so a consumer's project adds **no dependency**. Captures public
  static **and instance** methods — the receiver is reconstructed across versions (via
  `ReflectionFactory`, like Java serialization) and its post-call mutation is compared.
  Determinism is the run-twice guard; a one-command `verify` and I/O quarantine are next.
  Java 17+.
- **The Selfsame Protocol** (`SPEC/protocol.md`) — the language-neutral contract (canonical
  form, soundness rules, verdict model, report schema) that every language implementation
  must share, with JSON Schemas in `SPEC/schemas/`.
- **Conformance suite** (`SPEC/conformance/`) — language-neutral comparator and soundness
  vectors, run against the Python implementation in CI; the template for future languages.
- **Language roadmap** (`docs/languages.md`) and design placeholders for JavaScript/TypeScript
  (`packages/node/`, next) and Java (`packages/java/`). Go and Rust are documented as **held**
  until they can match Python's automatic, sound guarantee.

## [0.3.0] - 2026-06-24

A new axis of verification — proving that a passing result actually *depends* on
a silent assumption — plus a wider determinism net and a robustness fix for
replaying live working trees.

### Added
- **Assumption adjudicator** (`selfsame adjudicate`, experimental) — holds the
  code fixed and *violates a nominated dependency boundary* (`none`/`raises`/
  `wrong-type`/`zero`/`negative`), re-runs on the captured inputs, and reports
  whether the behavior was **load-bearing** on that assumption (with a minimized
  witness), **not-load-bearing**, or **unverifiable**. A judge, not a detective:
  it adjudicates assumptions you nominate, it does not enumerate them. The
  `wrong-type` violation is shape-aware (a genuine type mismatch vs. the boundary's
  real return), and a nomination that never takes effect is flagged `boundary not
  invoked` so it can't masquerade as tolerant. Advisory by default (exit 0);
  `--fail-on-load-bearing` gates CI. Writes `.selfsame/assumptions.json` + `.md`.
- **Architecture & engineering spec** (`docs/architecture.md`) — the normative
  contract: data/wire formats, canonical-form schema, soundness rules, verdict
  model, and module map. Plus the adjudicator design (`docs/adjudicator.md`).

### Changed
- **Broader determinism control** — the harness now also freezes
  `from datetime import datetime/date` references captured at import across all
  loaded modules, and makes unseeded `random.Random()` instances deterministic.
  Remaining gaps (aliased `... as dt` imports, C-level extension entropy) surface
  as `unverifiable`, never as false confidence.

### Fixed
- **Stateless objects are comparable** — an object with a present-but-empty
  `__dict__`/`__slots__` is now treated as empty state (so methods on stateless
  receivers are verifiable) instead of being refused as opaque; only objects with
  no introspectable state at all stay opaque.
- **Stale-bytecode replay bug** — replay/adjudicate workers compile the target
  from current source (`sys.dont_write_bytecode` + a fresh `pycache_prefix`), so
  replaying a live working tree right after a same-size, same-mtime-second edit no
  longer risks importing a stale `.pyc` and reporting a real change as equivalent.

## [0.2.0] - 2026-06-22

The release that makes Selfsame fit AI-driven development: detect behavioral
regressions against a confirmed baseline, with agent-consumable reports — and a
large jump in how much code can be soundly compared.

### Added
- **Snapshot / drift** — freeze a confirmed build's behavior (`selfsame snapshot`)
  and measure how much later code deviates from it (`selfsame drift`), with no
  second git branch. `drift --changed-only` scopes replay to changed functions.
- **pytest plugin** — a compare-only drift check at the end of a normal `pytest`
  run (`--selfsame` / `selfsame = true`). Never re-baselines; fails the session on
  drift unless `--selfsame-no-fail`.
- **Agent-consumable reports** — every `verify`/`drift` writes `.selfsame/report.json`
  + `report.md` with `file:line` references, base→head witnesses, soundness
  reasons, and changed-but-untested functions, plus a one-line machine summary.
  Also `--json-out` and `--junit-xml`.
- **Divergence detail + witness minimization** — divergences show base vs head
  outputs and a minimized failing input (`--no-minimize` to skip).
- **Coverage blind-spot report** — lists changed functions with no test inputs.
- **`[tool.selfsame]` config** (pyproject.toml / selfsame.toml) and `--strict`.
- **Leaf value-type canonicalization** — `datetime`/`date`/`time`/`timedelta`,
  `Decimal`, `complex`, `Fraction`, `Path`, `re.Match`/`Pattern`, and singletons
  are compared by their observable form (and any object/container holding them),
  greatly increasing sound coverage (e.g. arrow 45% → 90%).
- Experimental capture-seeded **coverage-guided differential fuzzing**
  (`selfsame fuzz`).
- GitHub Actions CI (Python 3.8–3.13, Linux + macOS, `ruff`); PyPI release via
  Trusted Publishing (OIDC); community docs and rewritten README + `docs/` tree.

### Changed
- Distribution renamed `coverage-probe` → `selfsame`; `selfsame` console command
  alongside `probe`.
- Cross-version drift handling: a signature change is reported `interface-change`
  (not a false `divergent`); an added/removed function is `skipped`.
- Verdict output separates `verified` from `not verified`; exit codes
  0/1/2/3 (`3` = `--strict` with unverifiable functions).

### Fixed
- Capture is bounded by `PROBE_CAPTURE_TIMEOUT` and auto-disables
  `pytest-benchmark`, so heavy/property-based suites can't run away.
- Worktrees are prepared with build-generated, git-ignored sources
  (setuptools-scm/hatch-vcs `_version.py`) so dynamically-versioned packages
  import during replay.
- Re-entrancy guard in the capture hook fixes an infinite hang on cyclic /
  Mapping classes (e.g. bidict).

## [0.1.0] - 2026-06-22

First tagged release of the Coverage Probe / Selfsame engine.

### Added
- Sound behavior-equivalence verifier: capture real call arguments from a repo's
  tests or app, replay both versions in isolated subprocesses, compare
  structurally. Guarantee: zero false confidence.
- `probe` CLI: `verify`, `check`, `capture`, `replay`, `attach`, `demo`.
- Targeted import-wrapping capture; entry-script (`__main__`) capture;
  on-demand `probe attach` flush for running processes.
- Package-aware replay from git worktrees; parallel workers with per-worker
  timeout; CI mode (`--changed-only`); `--python` for version-matched runs.
- Structural equality: callable-aware, public-interface snapshots for stateful
  containers, bounded iterator materialization.
- Child-process reaper so the tool never leaves orphaned subprocesses.

[Unreleased]: https://github.com/PraveenKPandu/Selfsame/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/PraveenKPandu/Selfsame/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/PraveenKPandu/Selfsame/releases/tag/v0.1.0
