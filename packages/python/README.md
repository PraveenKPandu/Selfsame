# selfsame (Python)

[![CI](https://github.com/PraveenKPandu/Selfsame/actions/workflows/ci.yml/badge.svg)](https://github.com/PraveenKPandu/Selfsame/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/selfsame.svg)](https://pypi.org/project/selfsame/)
[![Python](https://img.shields.io/pypi/pyversions/selfsame.svg)](https://pypi.org/project/selfsame/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](../../LICENSE)

The **Python implementation** of Selfsame — a sound behavior checker. It captures the
*real* arguments your tests (or app) feed your code, replays two versions in isolated
subprocesses, and compares the results structurally. Use it to prove a refactor didn't
change behavior — or to catch the silent regressions that creep in when an AI agent ships
features all day and "a new feature works, but the old ones quietly broke."

> **The one promise: zero false confidence.** Selfsame never says `equivalent` when behavior
> actually differs, and never says `divergent` when it doesn't. When it can't be sure, it
> **refuses** (`unverifiable`) instead of guessing.

![Selfsame catching a silent regression that passing tests missed](https://raw.githubusercontent.com/PraveenKPandu/Selfsame/main/assets/selfsame-demo.gif)

This package is the reference implementation and the source of truth for the cross-language
[Selfsame Protocol](../../SPEC/protocol.md). Other language runtimes (JavaScript/TypeScript,
Java, …) implement the same protocol and are tracked on the
[language roadmap](../../docs/languages.md).

## Install

```bash
pip install selfsame        # or: pipx install selfsame · uv tool install selfsame
```

Installs the `selfsame` command (`probe` is a kept alias). Pure standard library, no runtime
dependencies. Python 3.8+.

## 60-second start

**Did my refactor change behavior?** (inputs come from your existing tests)

```bash
selfsame verify --base main --modules mypkg -- pytest -q
```

**No second branch? Freeze the accepted build, then measure drift:**

```bash
selfsame snapshot --modules myapp -- pytest -q   # freeze behavior
# ... let an AI ship changes ...
selfsame drift                                   # exit 1 if anything diverged
```

## Commands

| command | what it does |
|---|---|
| `selfsame verify`   | replay base vs head on your test inputs; per-function verdict + CI exit code |
| `selfsame snapshot` | freeze the current (accepted) build's behavior to a baseline file |
| `selfsame drift`    | measure how much current code deviated from the baseline (no second branch) |
| `selfsame capture`  | record real call arguments from any test or app command |
| `selfsame replay`   | replay captured arguments across two git refs |
| `selfsame attach`   | dump captures from a running, hook-enabled process without stopping it |
| `selfsame check`    | generate inputs and check two files / git refs (for typed, pure functions) |
| `selfsame fuzz`     | *(experimental)* mutate real inputs to find divergences your tests miss |
| `selfsame adjudicate` | *(experimental)* prove whether a nominated assumption is load-bearing |

## Documentation

Full docs live at the repo root: [getting started](../../docs/getting-started.md) ·
[how it works](../../docs/how-it-works.md) · [commands](../../docs/commands.md) ·
[configuration](../../docs/configuration.md) · [limitations](../../docs/limitations.md) ·
[architecture & spec](../../docs/architecture.md).

## Development

```bash
cd packages/python
pip install -e .
PYTHONHASHSEED=0 python -m unittest discover -s tests
ruff check probe tests units
```

License: [MIT](../../LICENSE).
