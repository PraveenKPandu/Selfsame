# Contributing

Thanks for your interest in Selfsame!

## Dev setup

No third-party runtime dependencies — Selfsame is pure standard library.

```bash
git clone git@github.com:PraveenKPandu/Selfsame.git
cd Selfsame
python -m pip install -e .        # provides the `selfsame` / `probe` commands
```

## Running the checks

```bash
PYTHONHASHSEED=0 python -m unittest discover -s tests   # test suite
python run_probe.py                                     # corpus demo (or: probe demo)
ruff check probe tests units                            # lint (pip install ruff)
```

CI runs the test suite on Python 3.8–3.13 (Linux) plus macOS, and `ruff`.
Please make sure both are green before opening a PR.

## The one rule that matters: soundness

Selfsame's guarantee is **zero false confidence** — it must never report
`equivalent` when behavior differs, or `divergent` when it doesn't. When in
doubt, the engine *refuses* (`unverifiable` / `not-comparable`) rather than
guess. Any change must preserve this. New behaviors should come with tests that
demonstrate they don't introduce a false positive or a missed catch. See
`experiments/FINDINGS.md` for the reasoning behind the current design.

## Branching (gitflow)

- Branch from `develop` using a descriptive name: `feature/<topic>`.
- Open PRs into `develop`. `main` is release-only.
- Merges into `develop` use `--no-ff`.

## Releasing

See [RELEASING.md](RELEASING.md). Releases publish to PyPI automatically on a
`vX.Y.Z` tag via GitHub Actions Trusted Publishing.
