# Conformance suite

Language-neutral vectors that keep every Selfsame implementation honest. They pin the two
pieces of shared semantics that the [protocol](../protocol.md) guarantees are identical
everywhere: the **comparator** (do two observations compare equal?) and the **soundness
gate** (is an observation refused, and with which `reason`?).

Each implementation MUST run these vectors against its own comparator and soundness gate in
CI. If a vector fails, the implementation is non-conformant — its `equivalent` /
`divergent` / `unverifiable` verdicts no longer mean what they mean elsewhere.

## Vectors

| file | feeds | asserts |
|---|---|---|
| [`cases/canonical-comparison.json`](cases/canonical-comparison.json) | pairs of observations | the boolean equality result (protocol §8) |
| [`cases/soundness-verdicts.json`](cases/soundness-verdicts.json) | one or more observations | the `reason` string, or `null` if verifiable (protocol §6) |

Observations and canonical forms follow
[`../schemas/canonical.schema.json`](../schemas/canonical.schema.json). Canonical forms in
the comparison vectors are assumed **already order-normalized** (protocol §4.3) — order
normalization itself is a *value → canonical* property and is tested per-language, where the
runtime's native values can actually be constructed.

## What is NOT covered here (and why)

- **`value → canonical` mapping** (e.g. "a `datetime` becomes `["datetime", …]`", "a set is
  sorted"): constructing native runtime values is language-specific, so these golden tests
  live inside each package. The vectors here assume canonicalization already happened.
- **Capture/replay mechanics, determinism harness, build isolation**: language-specific
  machinery, validated by each package's own tests.

## How an implementation consumes the vectors

1. Read each JSON file from this directory.
2. For `canonical-comparison`: for every case, compute `compare(a, b)` and assert it equals
   `same`.
3. For `soundness-verdicts`: for every case, compute the refusal `reason` for `observations`
   and assert it equals `reason` (`null` ⇒ verifiable).

The Python reference test is
[`packages/python/tests/test_conformance.py`](../../packages/python/tests/test_conformance.py)
— use it as the template when adding a new language.
