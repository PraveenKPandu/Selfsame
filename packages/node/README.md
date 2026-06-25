# @selfsame/node — JavaScript / TypeScript (planned)

> **Status: planned — the next implementation.** Not yet built. This directory holds the
> design so the work can start against a frozen [protocol](../../SPEC/protocol.md).

The Node implementation will bring Selfsame's *zero-false-confidence* behavior checking to
JavaScript and TypeScript (TS compiles to JS, so one runtime serves both). It targets the
[Selfsame Protocol](../../SPEC/protocol.md) and must pass the
[conformance suite](../../SPEC/conformance/).

## Why this is the natural second language

Node is a dynamic runtime with the interception points the guarantee needs — the same
properties that make the Python reference possible. And the audience shipping JS/TS with AI
agents is large.

## Planned approach (per protocol section)

| protocol piece | Node mechanism |
|---|---|
| **Capture** (§5) | a `--require`/`module.register` loader hook that wraps target modules' exported functions and records bound arguments, keyed `module::qualname` |
| **Serialize** (§5.1) | a structured-clone-style encoder (JSON is insufficient — it loses `Map`/`Set`/`Date`/`BigInt`/`undefined`/`-0`); round-trippable for replay |
| **Canonicalize** (§4) | JS-aware canonical form: `NaN`/`-0`, `undefined` vs `null`, `Map`/`Set` order-normalization, `BigInt`, class instances by observable state; `Symbol` and unrepresentables → `opaque`. Extension tags for `bigint`, `map`, `set` |
| **Determinism** (§7) | freeze `Date`/`Date.now`, `Math.random`, `crypto.getRandomValues`, `performance.now`, `process.hrtime`; run twice and refuse on disagreement |
| **Replay/build** (§2) | git worktree per version + `npm ci` + a child process per version |

## Open questions to resolve before coding

- ESM vs CJS interception coverage (loader hooks vs `require` patching).
- TypeScript: run against compiled JS (source maps for `file:line`) vs `ts-node`.
- How to scope "target modules" the way Python scopes `--modules`.

Track progress on the [language roadmap](../../docs/languages.md).
