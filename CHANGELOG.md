# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- GitHub Actions CI (test matrix Python 3.8–3.13 on Linux + macOS, `ruff` lint).
- PyPI release pipeline via Trusted Publishing (OIDC), triggered by `vX.Y.Z` tags.
- Community docs: LICENSE, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, CHANGELOG,
  issue/PR templates, Dependabot, `.editorconfig`, pre-commit.

### Changed
- Distribution renamed `coverage-probe` → `selfsame`; added a `selfsame` console
  command alongside `probe`.

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

[Unreleased]: https://github.com/PraveenKPandu/Selfsame/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/PraveenKPandu/Selfsame/releases/tag/v0.1.0
