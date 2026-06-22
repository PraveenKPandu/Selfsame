# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
