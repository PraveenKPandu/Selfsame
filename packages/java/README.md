# selfsame-java — JVM (planned)

> **Status: planned (after JavaScript/TypeScript).** Not yet built. This directory holds the
> design so the work can start against a frozen [protocol](../../SPEC/protocol.md).

A JVM implementation targeting the [Selfsame Protocol](../../SPEC/protocol.md), which must
pass the [conformance suite](../../SPEC/conformance/). Feasible with substantial effort; the
sticky part is determinism (see below).

## Planned approach (per protocol section)

| protocol piece | JVM mechanism |
|---|---|
| **Capture** (§5) | a `-javaagent` using bytecode instrumentation (ByteBuddy/ASM) to wrap target methods and record bound arguments, keyed `fqcn::method` |
| **Serialize** (§5.1) | a reflective deep encoder (Java serialization needs `Serializable`; reflection is more general); round-trippable for replay |
| **Canonicalize** (§4) | reflection-based canonical form honoring observable semantics: `equals`/`hashCode`, boxing, `BigDecimal` scale, records, collection ordering; unrepresentables → `opaque` |
| **Determinism** (§7) | wrap `java.util.Random`/`SecureRandom`; **native** `System.currentTimeMillis`/`nanoTime` can't be monkeypatched, so the agent must rewrite clock call-sites at load time — this is the hard part |
| **Replay/build** (§2) | compile each git worktree (Maven/Gradle), classpath isolation, a subprocess per version |

## Risk

Native time sources mean the determinism guarantee (§7) requires call-site rewriting via the
agent. Until that is solid, the JVM implementation must **refuse** time-dependent code rather
than claim to control it — never silently allow it.

Track progress on the [language roadmap](../../docs/languages.md).
