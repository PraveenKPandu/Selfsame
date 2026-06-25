# Contributing

Thanks for your interest in Selfsame!

## Repository layout

Selfsame is a polyglot monorepo: a language-neutral protocol with per-language
implementations.

```
SPEC/               # the Selfsame Protocol (source of truth) + conformance vectors
packages/python/    # the reference implementation (this is what `pip install selfsame` ships)
packages/node/      # JavaScript/TypeScript implementation (planned)
packages/java/      # JVM implementation (planned)
docs/               # shared docs + the language roadmap
```

See [SPEC/protocol.md](SPEC/protocol.md) and [docs/languages.md](docs/languages.md).

## Dev setup (Python)

No third-party runtime dependencies — the Python implementation is pure standard library.

```bash
git clone git@github.com:PraveenKPandu/Selfsame.git
cd Selfsame/packages/python
python -m pip install -e .        # provides the `selfsame` / `probe` commands
```

## Running the checks

```bash
cd packages/python
PYTHONHASHSEED=0 python -m unittest discover -s tests   # test suite (incl. conformance)
python run_probe.py                                     # corpus demo (or: probe demo)
ruff check probe tests units                            # lint (pip install ruff)
```

CI runs the test suite on Python 3.8–3.13 (Linux) plus macOS, `ruff`, and the cross-language
**conformance** suite. Please make sure they're green before opening a PR.

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
