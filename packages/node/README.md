# selfsame (JavaScript / TypeScript)

> **Status: alpha.** The protocol-critical core (canonical form, comparator, soundness
> gate) passes the cross-language [conformance suite](../../SPEC/conformance/), and an
> end-to-end capture → replay → compare pipeline catches real regressions. Capture currently
> covers **CommonJS** modules; ESM and richer method/receiver support are in progress.

The JavaScript/TypeScript implementation of the [Selfsame Protocol](../../SPEC/protocol.md) —
sound, zero-false-confidence behavior checking. It captures the *real* arguments your tests or
app feed your code, replays two versions in isolated subprocesses, and compares the results
structurally. TypeScript is supported by running against compiled JS (or a CJS TS runner).

> **The one promise: zero false confidence.** It never reports `equivalent` when behavior
> differs, nor `divergent` when it doesn't. When it can't be sure (uncontrolled I/O, threads,
> nondeterminism, opaque values), it **refuses** (`unverifiable`) instead of guessing.

## Install

```bash
npm install -g selfsame      # or run via npx
```

Requires Node ≥ 18. Zero runtime dependencies.

## Use

Two steps: record real inputs, then verify two versions against them.

```bash
# 1. Capture real inputs by running your tests/app (modules under --root get wrapped)
selfsame capture --root ./src --out .selfsame -- node ./run-my-tests.js

# 2. Replay those inputs across two versions and get a per-function verdict
selfsame replay --before ./old --after ./src --captures .selfsame
```

```
X applyDiscount  n=3  divergent  @ input #2
      base : ["float",167.5]
      head : ["float",167.49]

selfsame: 0 equivalent · 1 divergent · 0 unverifiable · 0 skipped · 0 error
```

Exit code is non-zero on any divergence, so it drops into CI.

## How it maps to the protocol

| protocol piece | this implementation |
|---|---|
| **Capture** (§5) | `Module._load` interception wraps target modules' exported functions / class methods; args serialized with `node:v8` (the pickle analog) |
| **Canonicalize** (§4) | `src/canonical.js` — JS-aware: `NaN`/`-0`, `null` vs `undefined`, `BigInt`, `Map`/`Set` (order-normalized), `Date`, `RegExp`, class instances by observable state; `Symbol`/unrepresentables → `opaque` |
| **Soundness** (§6) + **compare** (§8) | `src/soundness.js` — passes the conformance vectors |
| **Determinism** (§7) | `src/harness.js` — freezes `Date`/`Date.now`/`performance.now`/`process.hrtime`, seeds `Math.random` and `crypto`; runs each input twice and refuses on disagreement; counts `fs`/`net` I/O and `worker_threads` |
| **Replay** (§2) | a worker subprocess per version (`src/replayWorker.js`) |

## Honest limitations (alpha)

- **CommonJS only** for capture. ESM capture needs loader hooks (`module.register`, Node ≥ 20)
  — not yet wired. TypeScript works via compiled JS or a CJS TS runner.
- **Named exports** are wrapped; a bare `module.exports = function` default export isn't yet.
- **Methods** are best-effort: the receiver is serialized with `node:v8`, which doesn't restore
  the class prototype across versions, so method support is reliable for plain-data receivers.
- I/O / thread counting is best-effort (`fs`, `net`, `worker_threads`); anything it can't see it
  may not refuse — the determinism guard (run-twice) is the backstop.
- Version materialization is by **directory pair** (`--before`/`--after`); git-worktree and
  npm-install-per-version (like the Python `verify`) are not yet built.

See the [language roadmap](../../docs/languages.md). Contributions welcome against the
[conformance suite](../../SPEC/conformance/).

## Development

```bash
cd packages/node
node --test test/        # canonical golden, conformance, harness, end-to-end
```
