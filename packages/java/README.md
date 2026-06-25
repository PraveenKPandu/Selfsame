# selfsame (JVM / Java)

> **Status: core landed; not yet an end-to-end tool.** The protocol-critical core — the
> canonical form, comparator, and soundness gate — is implemented in pure JDK and **passes the
> cross-language [conformance suite](../../SPEC/conformance/)**, so a Java `equivalent` /
> `divergent` / `unverifiable` already means what it means in Python and JS. The capture
> (JVM agent), determinism harness, and replay are **not built yet** — see the roadmap below.

A JVM implementation of the [Selfsame Protocol](../../SPEC/protocol.md). Pure JDK, no runtime
dependencies; Java 17+.

## What works today

| piece | status |
|---|---|
| Canonical form (`Canonical.java`) | ✅ JVM-aware: integers/`BigInteger`, `double` (NaN/±inf/-0), `BigDecimal` (keeps scale), `String`/`char`, `byte[]`, arrays, `List`/`Set`/`Map` (order-normalized), `java.time` (`Instant`/`LocalDate`/…), `enum`, `Class`, POJO/record by observable field state; no introspectable state → `opaque` |
| Comparator + soundness gate (`Soundness.java`) | ✅ `same` / `unsound` / `hasOpaque` — passes the conformance vectors |
| Minimal JSON (`Json.java`) | ✅ pure-JDK parser/serializer (no Jackson/Gson) |
| Capture (`-javaagent` bytecode instrumentation) | ⬜ not built |
| Determinism harness (clock/entropy control) | ⬜ not built (native `System.nanoTime` needs call-site rewriting via the agent) |
| Replay (subprocess per version + Maven/Gradle build) | ⬜ not built |

So today this is a **conformant comparator core**, not yet a runnable `verify`. The remaining
pieces are the heavy, JVM-specific machinery (an agent + clock rewriting); they are the next
milestone.

## Build & test

No test framework to download — tests run via a dependency-free runner:

```bash
cd packages/java
javac -d out src/main/java/dev/selfsame/*.java src/test/java/dev/selfsame/*.java
java -cp out dev.selfsame.TestMain      # runs conformance vectors + canonical golden tests
```

`mvn package` builds the jar (the core has no dependencies).

## Roadmap (per [docs/languages.md](../../docs/languages.md))

1. **Capture** — a `-javaagent` using ByteBuddy/ASM to wrap target methods and record args
   (serialized for replay), keyed `fqcn::method`. This is the one place a dependency enters,
   isolated to the capture module.
2. **Determinism** — wrap `java.util.Random`/`SecureRandom`; rewrite native clock call-sites
   (`System.currentTimeMillis`/`nanoTime`) via the agent, or **refuse** time-dependent code
   until that lands (never silently allow it).
3. **Replay** — compile each git worktree (Maven/Gradle), run a subprocess per version, reuse
   the comparator/soundness already here.

Contributions welcome against the [conformance suite](../../SPEC/conformance/).
