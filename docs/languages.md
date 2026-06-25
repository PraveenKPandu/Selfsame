# Language roadmap

Selfsame is a *protocol* with one reference implementation today. The
[Selfsame Protocol](../SPEC/protocol.md) defines what every language must share so a verdict
means the same thing everywhere; the [conformance suite](../SPEC/conformance/) keeps the
implementations honest.

The thing that makes Selfsame valuable — the **zero-false-confidence guarantee** — is also
what gates which languages can join. A language qualifies only if it can, for arbitrary code:
**capture** real call arguments, **canonicalize** values by observable form, and **control**
the clock/entropy (or soundly refuse what it can't). Dynamic runtimes can; statically
compiled ones with no interception point largely cannot without rewriting the code under test
— which would itself break soundness.

## Status

| language | status | why |
|---|---|---|
| **Python** | ✅ shipped (reference) | dynamic runtime; full guarantee. Lives in [`packages/python/`](../packages/python/) |
| **JavaScript / TypeScript** | 🟢 alpha | core passes conformance; end-to-end capture→replay works (CommonJS; ESM + richer methods in progress). Lives in [`packages/node/`](../packages/node/) |
| **Java (JVM)** | 🟡 core landed | comparator core (canonical/compare/soundness) passes conformance; capture (`-javaagent`) + determinism + replay pending. In [`packages/java/`](../packages/java/) |
| **Go** | ⏸️ held | no runtime interception or reflection-on-functions; can't freeze `time.Now()`/`rand` for arbitrary code without rewriting it (which breaks soundness) |
| **Rust** | ⏸️ held | no reflection; generic capture/determinism are impossible without source annotation (`#[…]` macros + `serde` bounds) — a different, manual UX |

**Decision (current):** Go and Rust are **held until they can match Python's automatic, sound
guarantee.** We will not ship them with a reduced or silently-weaker guarantee — that would
contradict the one promise the project rests on. They remain open research; if a sound,
non-invasive interception approach emerges, they graduate.

## How a new language joins

1. Read the [protocol](../SPEC/protocol.md) and implement the five pieces (capture,
   serialize, canonicalize, determinism, replay/build) for that runtime.
2. Pass the [conformance suite](../SPEC/conformance/) — wire its vectors into the package's
   CI, mirroring [`packages/python/tests/test_conformance.py`](../packages/python/tests/test_conformance.py).
3. Add per-language `value → canonical` golden tests inside the package (constructing native
   values, which the language-neutral vectors can't do).
4. Add the package's job to the CI matrix and a per-registry release workflow.
5. Update this table and the package's status.

A language must never claim the guarantee it cannot uphold. If it cannot control an effect, it
**refuses** (`unverifiable`) — it does not approximate.
