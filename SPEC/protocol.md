# The Selfsame Protocol

**Status:** v0 (draft, normative for the Python reference implementation)
**Source of truth:** this document + the JSON Schemas in [`schemas/`](schemas/) + the
conformance vectors in [`conformance/`](conformance/).

Selfsame answers one question soundly, in any language: *do two versions of this code behave
the same on the inputs actually exercised?* The pipeline — **capture → replay → compare** —
and its **zero-false-confidence** guarantee are language-agnostic. This protocol defines the
parts every language implementation MUST share so that a verdict means the same thing
everywhere, and so a single comparator/reporter could consume observations from any runtime.

The Python package under [`packages/python/`](../packages/python/) is the reference
implementation. New languages (see [the roadmap](../docs/languages.md)) implement this
protocol and MUST pass the [conformance suite](conformance/).

The key words MUST, MUST NOT, SHOULD, and MAY are used as in RFC 2119.

---

## 1. The one invariant

> A reported `equivalent` or `divergent` verdict MUST be **sound** on the inputs checked: the
> tool MUST NOT report `equivalent` when behavior actually differs, nor `divergent` when it
> does not. Anything that cannot be compared soundly MUST be reported as `unverifiable`,
> `error`, or `skipped` — **never guessed**.

Every other rule in this document exists to preserve that invariant. An implementation that
cannot uphold a rule for a given value/effect MUST refuse (`unverifiable`) rather than
approximate.

---

## 2. Pipeline

```
capture  ──▶  replay  ──▶  compare  ──▶  report
   │             │            │             │
record real   re-run the   canonicalize  verdicts +
call inputs   SAME inputs  observations  witnesses
from a test   on each      and compare   (report.json)
or app run    version in   structurally;
              isolation     refuse if not
                            sound
```

Three stages vary the same engine along different axes; all feed one comparator + verdict
model:

| mode | varies | the "other side" |
|---|---|---|
| `verify` | the **code** (two refs) | base version |
| `drift` | the **code** (vs an accepted build) | a frozen snapshot |
| `adjudicate` *(experimental)* | an **assumption** (a violated boundary) | the code's own baseline |

---

## 3. Identity

A captured/compared unit is identified by a language-neutral **key**:

```
<module>::<qualname>
```

- `module` — the import path / package path of the symbol's defining unit
  (Python `pkg.mod`; JS `path/to/module`; Java fully-qualified class; etc.).
- `qualname` — the dotted path to the function/method within that module
  (`Class.method`, `outer.<locals>.inner`, …).

Keys MUST be stable across versions for the same logical symbol, so a renamed-but-equivalent
symbol is the implementer's responsibility to pair (or it is reported `skipped` as
added/removed).

---

## 4. Canonical form

`canonical(value) → JSON` converts a runtime value to a JSON-serializable form such that

> **two values share a canonical form iff they are observationally indistinguishable.**

This is the heart of the guarantee: equality is structural and *observable*, never `repr()`,
`toString()`, or identity. Every canonical form is a JSON array whose first element is a
string **tag**.

### 4.1 Core tags (every implementation MUST support)

| tag | form | notes |
|---|---|---|
| `none` | `["none"]` | the language's unit/null/None |
| `bool` | `["bool", v]` | checked **before** any integer type |
| `int` | `["int", v]` | arbitrary precision; encode as JSON number or decimal string if large |
| `float` | `["float", v \| "nan" \| "inf" \| "-inf"]` | `nan` canonicalized to `"nan"`; **`-0.0` normalized to `0.0`** |
| `str` | `["str", v]` | text |
| `bytes` | `["bytes", [int,…]]` | byte sequences |
| `list` | `["list", [c,…]]` | ordered sequence; recursive |
| `set` | `["set", [c,…]]` | **order-normalized** (sort the canonical children deterministically) |
| `dict` | `["dict", [[ck,cv],…]]` | **order-normalized** by canonical key |
| `callable` | `["callable", module, qualname]` | identity by name, not value |
| `class` | `["class", module, qualname]` | a type/class value |
| `obj` | `["obj", classname, c(state)]` | an instance, by its observable state (see §4.3) |
| `opaque` | `["opaque", classname, "<unrepresentable>"]` | **refused downstream** (see §6) |

### 4.2 Extension tags (value types compared by observable form)

Implementations SHOULD canonicalize common value types by a **deterministic, observable**
representation, so they (and any container holding them) are comparable rather than opaque.
The reference set:

| tag | form |
|---|---|
| `tuple` | `["tuple", [c,…]]` (a fixed-arity sequence, where the language distinguishes it from `list`) |
| `range` | `["range", start, stop, step]` |
| `datetime` | `["datetime", isoformat, fold, tzname]` |
| `date` | `["date", isoformat]` |
| `time` | `["time", isoformat, fold, tzname]` |
| `timedelta`/`duration` | `["timedelta", days, seconds, microseconds]` |
| `tzinfo` | `["tzinfo", tzname, offset_seconds]` |
| `decimal` | `["decimal", str \| "nan" \| "inf" \| "-inf"]` (exact string) |
| `complex` | `["complex", c(real), c(imag)]` |
| `fraction`/`rational` | `["fraction", numerator, denominator]` (normalized) |
| `path` | `["path", str]` |
| `match` | `["match", c(pattern), [span], c(groups), c(groupdict)]` |
| `pattern`/`regex` | `["pattern", c(pattern), flags]` |
| `singleton` | `["singleton", name]` (e.g. `"NotImplemented"`, `"Ellipsis"`) |
| `iter` | `["iter", [c,…]]` (lazy iterators materialized up to a cap; beyond the cap → `opaque`) |
| `pub-obj` | `["pub-obj", classname, snapshot]` (public Sequence/Set contents + public attrs) |
| `maxdepth` | `["maxdepth"]` (recursion guard) |

A language MAY add its own extension tags for native value types (JS `bigint`, `Map`, `Set`,
`symbol`; Java `BigDecimal`, records; …) provided the form is deterministic and faithful to
the type's **observable** behavior. New tags MUST be added to this document and the schema.

### 4.3 Normative rules (these protect the invariant)

1. **Tag-check order matters.** Subtype-before-supertype (`bool` before `int`; `datetime`
   before `date`; extension value types before the generic object path).
2. **Observable form only.** A value's canonical form MUST depend solely on observable
   behavior. If two values are observationally indistinguishable, their forms MUST be equal;
   if distinguishable, their forms MUST differ. No false equivalence, no false divergence.
3. **Order normalization.** Unordered collections (`set`, `dict`) MUST be normalized to a
   deterministic order so equal contents yield equal forms regardless of iteration order.
4. **Empty state is state.** An object with present-but-empty internal state canonicalizes to
   `obj` with empty state (it is comparable). Only a value with **no** introspectable state
   at all (and no observable snapshot) becomes `opaque`.
5. **Fail safe.** Canonicalizing a value that raises/throws MUST fall through to `opaque`,
   never crash the run.
6. **Opaque is contagious.** An `opaque` anywhere in a value's tree makes the enclosing
   observation `unverifiable` (§6).

---

## 5. Capture & observation

### 5.1 Capture record

A capture is a recorded call to a target, suitable for replay. Serialization of the argument
payload is language-specific (Python `pickle`, JS structured-clone/JSON, …); the protocol
fixes the **envelope** (see [`schemas/capture.schema.json`](schemas/capture.schema.json)):

```jsonc
{
  "key": "<module>::<qualname>",
  "is_method": false,
  "args_b64": "<base64 of the language-native serialized argument tuple>",
  "meta": { "lang": "python", "captured_with": "<tool version>" }
}
```

Inputs come from a **real run** of the code (its test suite or app). No type hints or
generated inputs are required for the primary path.

### 5.2 Observation

Replaying one input on one version yields one **observation**
([`schemas/canonical.schema.json#/$defs/observation`](schemas/canonical.schema.json)):

```jsonc
{
  "val": ["<canonical form of the return value>"],   // XOR "exc"
  "exc": "<exception/error type name>",               // present iff the call raised
  "self_after": ["<canonical form of the post-call receiver>"],  // methods only
  "io": 0,         // count of uncontrolled I/O operations observed
  "threads": 0,    // count of threads/goroutines started
  "nondet": false  // true iff two controlled runs of this input disagreed
}
```

For a method, the **post-call receiver state** (`self_after`) is part of the observation: a
refactor that changes how a method mutates its receiver MUST be caught.

---

## 6. Soundness model

An observation (or a unit's set of observations) is **`unverifiable`** if any of the
following hold, evaluated in this priority order. The matching `reason` string is normative:

| condition | `reason` |
|---|---|
| two controlled runs of the same input disagreed | `nondeterministic` |
| uncontrolled I/O occurred (file/socket/…) | `uncontrolled-io` |
| a thread / goroutine was started | `concurrency` |
| the return value's canonical form contains `opaque` | `opaque-return` |
| the post-call receiver state contains `opaque` | `opaque-state` |

Implementations MUST refuse (not approximate) in every case above. I/O that is routed through
a **recorded deterministic shim** does not count as uncontrolled.

---

## 7. Determinism requirements

Before comparison, each input MUST be run under a **controlled** environment and run **twice**;
if the two runs' observations differ, the input is `nondeterministic` and refused. An
implementation MUST control (freeze/seed) at minimum:

- **the clock** — wall/monotonic/high-resolution time sources;
- **entropy** — the language's PRNGs, cryptographic randomness, and UUID generation;
- **hash/iteration order** — so set/map ordering is stable across processes.

Whatever it cannot control, it MUST detect and refuse (via the nondeterminism guard or the
I/O / concurrency counters), never silently allow. A language that cannot generically control
the clock/entropy of arbitrary code (e.g. statically compiled targets with no interception
point) does **not** satisfy this protocol's full guarantee and MUST NOT claim it; such a
language is "held" until it can (see [the roadmap](../docs/languages.md)).

---

## 8. Verdict model

For each unit, the comparator produces one verdict, evaluated in order
([`schemas/report.schema.json`](schemas/report.schema.json)):

| verdict | when |
|---|---|
| `error` | a version failed to run, or observation counts mismatched |
| `skipped` | the unit is absent in one/both versions (added/removed), or not loaded |
| `unverifiable` | the soundness model (§6) refused either version, with its `reason` |
| `interface-change` | parameters differ **and** the divergence is an arity error (a version can't accept the captured args) — not a behavior regression |
| `divergent` | the first input where the two versions' observations are not equal |
| `equivalent` | all inputs agree |

- `timeout` is an `error` whose note is exactly `"timeout"`; it MUST be counted separately
  and MUST NOT read as a divergence.
- A `divergent` verdict SHOULD carry a **minimized witness**: the diverging input reduced by
  type-aware simplification while it still diverges.
- Two observations are **equal** iff: exception-ness matches; if both raised, the error type
  names match; otherwise the `val` canonical forms are equal; **and** the `self_after`
  canonical forms are equal.

### 8.1 Exit codes

| code | meaning |
|---|---|
| `0` | no divergence |
| `1` | ≥ 1 divergence |
| `2` | usage error |
| `3` | strict mode **and** some unit was `error`/`timeout` |

`interface-change` and `skipped` are not failures and MUST NOT set a non-zero code on their
own.

---

## 9. Report

Every run MUST write a machine-readable report (`report.json`) and SHOULD write a Markdown
sibling (`report.md`). See [`schemas/report.schema.json`](schemas/report.schema.json). The
report MUST include: a `schema` version, an `environment` block, a `summary` of verdict
counts, a `results[]` array (per unit: `key`/`function`, `verdict`, `file`, `line`, `base`,
`head`, witness, soundness `reason`), and **`unverified_changed[]`** — units that changed but
had no captured inputs, so the coverage blind spot is explicit rather than hidden.

---

## 10. Conformance

An implementation conforms to this protocol if it passes the vectors in
[`conformance/`](conformance/): canonical-comparison cases (do two observations compare
equal?) and soundness cases (is an observation refused, and with which `reason`?). These
vectors are language-neutral JSON and MUST be run against every implementation's comparator
and soundness gate in CI. See [`conformance/README.md`](conformance/README.md).

---

## 11. Versioning

This protocol is versioned independently of any implementation. Breaking changes to a tag's
form, the verdict vocabulary, the soundness `reason` strings, or the report schema bump the
protocol version. Implementations declare which protocol version they target.
