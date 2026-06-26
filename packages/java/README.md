# selfsame (JVM / Java)

> **Status: alpha — end-to-end.** Capture (a `-javaagent`) → replay → compare works for
> **public static methods**, and the comparator core passes the cross-language
> [conformance suite](../../SPEC/conformance/). Instance-method receivers, a one-command
> `verify`, and I/O quarantine are the next steps (see below).

A JVM implementation of the [Selfsame Protocol](../../SPEC/protocol.md): sound,
zero-false-confidence behavior checking. It captures the *real* arguments your tests/app feed
your code (via bytecode instrumentation), replays two versions in isolated JVMs, and compares
the results structurally.

> **The one promise: zero false confidence.** When it can't compare soundly it refuses
> (`unverifiable`) rather than guess. Determinism is enforced by a run-twice guard: a method
> whose two runs disagree is reported nondeterministic and refused.

Java 17+. **Your project adds no dependency** — ByteBuddy is shaded inside the agent jar (the
same way the OpenTelemetry/Datadog Java agents work), so nothing enters your build.

## Use

```bash
# 1. Capture real inputs by running your program/tests with the agent attached
java -jar selfsame.jar capture --target com.acme --cp <your-classpath> --out .selfsame --main com.acme.Main

# 2. Replay the captures against two compiled versions and get a per-method verdict
java -jar selfsame.jar replay --before <classpath-A> --after <classpath-B> --captures .selfsame
```

```
X applyDiscount  n=4  divergent  @ input #1
      base : ["int",91]
      head : ["int",90]
```

`--target` is a class-name prefix; methods of matching classes are instrumented. Exit code is
non-zero on any divergence, so it drops into CI.

## How it maps to the protocol

| protocol piece | this implementation |
|---|---|
| **Capture** (§5) | a `-javaagent` (ByteBuddy `Advice`) records args to matching classes' public static methods; round-tripped by `ValueCodec` |
| **Canonicalize** (§4) | `Canonical.java` — integers/`BigInteger`, `double` (NaN/±inf/-0), `BigDecimal` (keeps scale), `String`/`char`, `byte[]`, arrays, `List`/`Set`/`Map` (order-normalized), `java.time`, `enum`, `Class`, POJO/record by state; unrepresentable → `opaque` |
| **Soundness** (§6) + **compare** (§8) | `Soundness.java` — passes the conformance vectors |
| **Determinism** (§7) | run-twice guard (nondeterministic methods refused). *Clock/entropy freezing and I/O quarantine are not yet implemented — see limits.* |
| **Replay** (§2) | a worker JVM per version (`ReplayWorker`) |

## Honest limitations (alpha)

- **Public static methods only.** Instance methods need receiver reconstruction across versions
  (the same problem Python solves with pickle, JS with `v8.serialize`) — next.
- **Argument types** are limited to what `ValueCodec` round-trips (primitives, `String`,
  `BigInteger`/`BigDecimal`, `byte[]`, `List`/`Map`/`Object[]`); a call with an unsupported arg
  is skipped — sound under-capture, never a wrong reconstruction.
- **No I/O / thread quarantine yet.** Unlike Python/JS, this MVP doesn't count uncontrolled I/O
  or threads; soundness rests on the run-twice determinism guard (nondeterministic code is
  refused). Deterministic I/O is compared as-is.
- **Directory-pair replay** (`--before`/`--after` classpaths); a git-worktree + Maven/Gradle
  `verify` (build each ref automatically) is not built yet.

## Build & test

```bash
cd packages/java
mvn -DskipTests package      # builds the shaded target/selfsame.jar (agent + cli + worker)
bash e2e.sh                  # capture -> replay end-to-end

# the pure-JDK comparator core also builds + tests without Maven:
javac -d out src/main/java/dev/selfsame/*.java src/test/java/dev/selfsame/*.java
java -cp out dev.selfsame.TestMain   # conformance + canonical golden tests
```

See the [language roadmap](../../docs/languages.md). Contributions welcome against the
[conformance suite](../../SPEC/conformance/).
