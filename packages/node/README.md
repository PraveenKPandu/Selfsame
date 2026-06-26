# selfsame (JavaScript / TypeScript)

> **Status: alpha.** The protocol-critical core (canonical form, comparator, soundness
> gate) passes the cross-language [conformance suite](../../SPEC/conformance/), and an
> end-to-end capture → replay → compare pipeline catches real regressions. Capture covers
> both **CommonJS** and **ES modules** (ESM needs Node ≥ 20.6); richer method/receiver
> support is in progress.

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

Requires Node ≥ 18 (≥ 20.6 for ESM capture). One small dependency
([es-module-lexer](https://www.npmjs.com/package/es-module-lexer), to read ESM export names
without executing modules).

## Use

For **ES modules**, add `--esm` to `capture` (uses a `module.register` loader; Node ≥ 20.6):

```bash
selfsame capture --esm --target ./src --out .selfsame -- node ./run-my-tests.mjs
selfsame replay --before ./old --after ./src --captures .selfsame
```

**One command (recommended, CommonJS)** — capture inputs from your test/app run, then verify
the working tree against a git ref:

```bash
selfsame verify --base main --root ./src -- node ./run-my-tests.js
```

```
X applyDiscount  n=3  divergent  @ input #2
      base : ["float",167.5]
      head : ["float",167.49]

selfsame: 0 equivalent · 1 divergent · 0 unverifiable · 0 skipped · 0 error
```

Each version is checked out as a `git worktree` and run in its own process (with the repo's
`node_modules` symlinked in). Exit code is non-zero on any divergence, so it drops into CI.
Add `--head <ref>` to compare two refs instead of working-tree-vs-base.

**No second branch? Freeze an accepted build, then measure drift** (the AI-velocity loop):

```bash
selfsame snapshot --root ./src -- node ./run-my-tests.js   # freeze behavior to .selfsame/snapshot.json
# ... let an AI ship changes ...
selfsame drift --root ./src                                # exit 1 if anything drifted
```

**Or two explicit steps** (no git needed) — capture, then replay two directories:

```bash
selfsame capture --root ./src --out .selfsame -- node ./run-my-tests.js
selfsame replay  --before ./old --after ./src --captures .selfsame
```

Every verdict-producing command writes an agent-consumable `.selfsame/report.json`
([schema](../../SPEC/schemas/report.schema.json)) — `--no-report` to skip, `--report <path>`
to relocate.

## How it maps to the protocol

| protocol piece | this implementation |
|---|---|
| **Capture** (§5) | `Module._load` interception wraps target modules' exported functions / class methods; args serialized with `node:v8` (the pickle analog) |
| **Canonicalize** (§4) | `src/canonical.js` — JS-aware: `NaN`/`-0`, `null` vs `undefined`, `BigInt`, `Map`/`Set` (order-normalized), `Date`, `RegExp`, class instances by observable state; `Symbol`/unrepresentables → `opaque` |
| **Soundness** (§6) + **compare** (§8) | `src/soundness.js` — passes the conformance vectors |
| **Determinism** (§7) | `src/harness.js` — freezes `Date`/`Date.now`/`performance.now`/`process.hrtime`, seeds `Math.random` and `crypto`; runs each input twice and refuses on disagreement; counts `fs`/`net` I/O and `worker_threads` |
| **Replay** (§2) | a worker subprocess per version (`src/replayWorker.js`) |

## Honest limitations (alpha)

- **CommonJS** captures named exports + bare default function exports (`module.exports = fn`);
  a default-exported *class* isn't yet. **ESM** (`--esm`, Node ≥ 20.6) captures top-level
  exported functions (via a `module.register` loader that reads export names with
  es-module-lexer and re-exports them wrapped — no source mutation); exported class methods
  are next. TypeScript works as compiled JS, a CJS TS runner, or ESM TS on Node ≥ 20.6.
- **Methods** are best-effort: the receiver is serialized with `node:v8`, which doesn't restore
  the class prototype across versions, so method support is reliable for plain-data receivers.
- I/O / thread counting is best-effort (`fs`, `net`, `worker_threads`); anything it can't see it
  may not refuse — the determinism guard (run-twice) is the backstop.
- `verify` symlinks the repo's existing `node_modules` into each worktree (no per-version
  reinstall); a version whose dependency set differs from the working tree's may need a manual
  install in the worktree.

See the [language roadmap](../../docs/languages.md). Contributions welcome against the
[conformance suite](../../SPEC/conformance/).

## Development

```bash
cd packages/node
node --test test/        # canonical golden, conformance, harness, end-to-end
```
