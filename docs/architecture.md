# Selfsame — architecture & engineering spec

This is the normative contract for the engine: the data formats, the canonical
comparison form, the soundness rules, the verdict model, and the module map. It
describes the code as of **v0.2.0**. User-facing docs live alongside this
([how-it-works](how-it-works.md), [commands](commands.md),
[configuration](configuration.md)); this document is for contributors and for
anything that *extends* the engine (e.g. a new perturbation source).

Two invariants govern everything below:

1. **Soundness — "zero false confidence."** The engine never reports
   `equivalent` when behavior differs, nor `divergent` when it doesn't. When it
   cannot compare deterministically it **refuses** (`unverifiable`) or reports a
   non-verdict (`error`/`skipped`). Every feature must preserve this.
2. **Pure standard library at runtime.** No third-party runtime dependencies.
   Anything heuristic or dependency-heavy (symbol resolution, linters) stays out
   of the core.

---

## 1. Pipeline

```
                 capture                replay                 compare
 your tests/   ──────────▶  inputs  ──────────▶  observations ──────────▶  verdict
 app run       (real call    (pickled   (one subprocess per     (canonical    (per
               arguments)    per func)   version / baseline)     form)         function)
```

- **verify** — base ref vs head ref. Both versions materialized as `git worktree`s.
- **drift** — current code vs a frozen **snapshot** baseline (no second branch).
- **capture/replay** — the two halves exposed separately (capture from any run,
  replay later across two refs).

The comparison stage and its verdict model are shared by all three.

---

## 2. Identifiers

A captured/replayed unit is keyed by:

```
key := "<module>::<qualname>"      e.g.  "myapp.billing::Invoice.total"
```

- `module` is the import name (path-derived, `src/` stripped — see
  `extract._module_file`/`_path_to_module`).
- `qualname` is `__qualname__`; methods are `Class.method`. The receiver `self`
  is captured as the first positional argument.
- `extract._split_key(key) -> (module, qualname)` is the canonical parser.

---

## 3. On-disk & wire formats

### 3.1 Capture file — `cap-<pid>.pkl`
One per process the capture command spawns. A pickle of:

```python
{ key: [ blob, ... ] }          # blob = pickle.dumps(list_of_bound_arg_values)
```

- Values are the call's arguments **bound to a positional list with defaults
  applied** (`inspect.Signature.bind` + `apply_defaults`); functions with
  `*args`/`**kwargs` fall back to raw positional args.
- Per-key cap: **`_CAP_PER_FUNC = 300`** distinct blobs (dedup by `hash(blob)`).
- `capture._merge()` merges all per-process files into `{key: [blob]}`.

### 3.2 Snapshot file — `.selfsame/snapshot.json`
A frozen behavioral baseline (produced by `snapshot`):

```jsonc
{
  "schema": 1,
  "modules": ["myapp"],
  "git_rev": "<full sha or null>",
  "records": {
    "<key>": {
      "blobs": ["<base64 of a capture blob>", ...],
      "base":  { /* a Worker Output object (§3.4) for the accepted code */ }
    }
  }
}
```

`drift` replays each record's `blobs` against the working tree and compares to
its stored `base`.

### 3.3 Worker job (stdin JSON)
`replay._worker` → `_replay_worker` per (version, key):

```jsonc
{ "worktree": "<path>", "module_name": "<module>", "qualname": "<qualname>",
  "args_b64": ["<base64 capture blob>", ...] }
```

### 3.4 Worker output (stdout JSON)

```jsonc
{
  "loaded":  true,                 // module imported and target resolved & callable
  "error":   null,                 // str on import/unpickle/internal failure
  "absent":  false,                // true: module loaded but qualname not found (added/removed)
  "params":  ["self", "x"] | null, // parameter names of the resolved callable
  "obs": [ <observation>, ... ]    // one per input blob, in order
}
```

An **observation** record:

```jsonc
{
  "io": 0, "threads": 0,           // counts from the determinism harness
  "nondet": true,                  // present iff the two determinism runs disagreed
  "val":  <canonical>,             // present iff the call returned (mutually excl. with exc)
  "exc":  "ValueError",            // present iff the call raised (exception type name)
  "self_after": <canonical>        // present for methods: receiver state after the call
}
```

Determinism check: each input is run **twice** under the harness; if the two
runs' `(return/exc, self_after)` disagree, the record is `{"nondet": true}` only.

### 3.5 Report — `.selfsame/report.json` (+ `report.md`)

```jsonc
{
  "tool": "selfsame", "schema": 1,
  "label": "base..head",                 // or "snapshot..WORKTREE"
  "environment": { "python": "...", "base": "...", "head": "...", "modules": "..." },
  "summary": { "equivalent": 0, "divergent": 0, "unverifiable": 0,
               "interface_change": 0, "error": 0, "timeout": 0, "skipped": 0,
               "functions_checked": 0 },
  "results": [
    { "function": "<qualname>", "key": "<key>", "inputs": 0, "verdict": "<verdict>",
      "file": "pkg/mod.py", "line": 12,     // when resolvable (extract.function_references)
      /* divergent: */ "input_index": 0, "input": "...", "base": "...", "head": "...",
                        "minimized": "...", "receiver_state_differs": true,
      /* unverifiable: */ "reason": "opaque-return",
      /* error: */ "error": "...", /* interface-change: */ "interface": "added x",
                        "base_params": [...], "head_params": [...] }
  ],
  "unverified_changed": [ { "key": "<key>", "file": "...", "line": 0 } ]
}
```

`report.md` is the same content rendered for an LLM. `--json-out` writes the JSON
to an extra path; `--junit-xml` maps verdicts to a JUnit suite (divergent →
failure, error/timeout → error, skipped/unverifiable/interface-change → skipped).

---

## 4. Canonical form (`probe/canonical.py`)

`canonical(value) -> JSON` converts a Python value to a JSON-serializable form
such that **two values share a canonical form iff they are observationally
indistinguishable.** This is the heart of the soundness guarantee: equality is
structural/observable, never `repr()` or identity.

Every form is a list whose first element is a tag:

| tag | form | notes |
|---|---|---|
| `none` | `["none"]` | |
| `bool` `int` | `["bool", v]` `["int", v]` | bool checked before int |
| `float` | `["float", v \| "nan" \| 0.0]` | `nan` and `-0.0` normalized |
| `str` | `["str", v]` | |
| `bytes` | `["bytes", [int,...]]` | bytes/bytearray |
| `list` `tuple` | `["list", [c,...]]` `["tuple", [c,...]]` | recursive |
| `set` | `["set", [c,...]]` | order-normalized (sorted by `json.dumps`) |
| `dict` | `["dict", [[ck,cv],...]]` | order-normalized |
| `callable` | `["callable", module, qualname]` | identity by name, not value |
| `class` | `["class", module, qualname]` | |
| `range` | `["range", start, stop, step]` | not materialized |
| `datetime` | `["datetime", isoformat, fold, tzname]` | observable form |
| `date` | `["date", isoformat]` | |
| `time` | `["time", isoformat, fold, tzname]` | |
| `timedelta` | `["timedelta", days, seconds, microseconds]` | |
| `tzinfo` | `["tzinfo", tzname, offset_seconds]` | standalone tzinfo |
| `decimal` | `["decimal", str \| "nan" \| "inf" \| "-inf"]` | exact string form |
| `complex` | `["complex", c(real), c(imag)]` | |
| `fraction` | `["fraction", numerator, denominator]` | normalized |
| `path` | `["path", str]` | `PurePath` |
| `match` | `["match", c(pattern), [span], c(groups), c(groupdict)]` | `re.Match` |
| `pattern` | `["pattern", c(pattern), flags]` | `re.Pattern` |
| `singleton` | `["singleton", "NotImplemented" \| "Ellipsis"]` | |
| `iter` | `["iter", [c,...]]` | lazy iterators, materialized ≤ `_ITER_CAP` |
| `pub-obj` | `["pub-obj", classqualname, snapshot]` | public Sequence/Set contents + public attrs |
| `obj` | `["obj", classqualname, c(state)]` | private `__dict__`/`__slots__` state |
| `opaque` | `["opaque", classqualname, "<unrepresentable>"]` ; `["opaque", "iterator-truncated"]` | **refused** downstream |
| `maxdepth` | `["maxdepth"]` | depth > `_MAX_DEPTH` |

Rules that protect soundness:
- **Order of checks matters** (e.g. `datetime` before `date`; leaf value types
  before the generic object path). New types must be inserted with subclass order
  in mind.
- **Leaf value types use observable form** so equal-canonical ⟺ observationally
  equal, in both directions (no false equivalence, no false divergence). Adding a
  leaf type means: pick a representation that is deterministic and faithful to the
  type's *observable* behavior. Guard it — a value that raises while being
  canonicalized must fall through, never crash a run.
- **Mappings are excluded** from the `pub-obj` public-snapshot path (their
  `__getitem__` can mutate caches); they fall back to `obj`/`opaque`.
- An `opaque` anywhere in a value's tree makes the enclosing return/state
  unverifiable (`_has_opaque` walks the form).

`probe/equality.py` is an **in-process** mirror used by the legacy `check` path;
`canonical.py` is the cross-process source of truth. (These currently duplicate
logic — keep them in sync, or unify; see Extension points.)

---

## 5. Soundness model

### 5.1 Refuse conditions — `replay._unsound(obs_list) -> reason | None`
A unit is **`unverifiable`** if any observation is, in priority order:

| condition | reason string | source |
|---|---|---|
| determinism runs disagreed | `nondeterministic` | `obs.nondet` |
| uncontrolled I/O occurred | `uncontrolled-io` | `obs.io > 0` |
| a thread was started | `concurrency` | `obs.threads > 0` |
| return value is opaque | `opaque-return` | `_has_opaque(obs.val)` |
| post-call receiver state is opaque | `opaque-state` | `_has_opaque(obs.self_after)` |

### 5.2 Determinism harness — `probe/harness.py`
`observe(fn, args)` runs `fn` under `_Controlled`, returning value/exception and
counts. `_Controlled`:
- **Freezes time** to `FROZEN_NOW = 1_700_000_000.0`: `time.time/monotonic/
  perf_counter` (+ `_ns`), and `datetime.datetime`/`datetime.date`
  `now/utcnow/today` (by patching the classes on the `datetime` module).
- **Seeds entropy**: `random` (seeded), `os.urandom`, `uuid1/4`, `secrets`.
- **Counts** `io` (`builtins.open`, `os.open`, `socket.connect`) and `threads`
  (`threading.Thread.start`). Counts > 0 → refuse.
- I/O routed through the recorded `Effects` shim (`probe/effects.py`) stays
  verifiable.

**Known, documented gaps** (surface as `unverifiable`, never as false
confidence): a reference captured at import (`from datetime import datetime`) and
per-instance `random.Random(...)` are *not* intercepted; C-level entropy/time in
extensions is not intercepted.

Equivalence of two observations — `replay._same(a, b)`:
- exception-ness must match; if both raised, exception **type names** must match;
- else `val` canonical forms must be equal;
- and `self_after` canonical forms must be equal (a method's mutation is behavior).

---

## 6. Verdict model

`replay._verdict(base, head, blobs) -> (verdict, note, div_idx, detail)`, in
order:

| verdict | when |
|---|---|
| `error` | either worker `error`, or observation-count mismatch |
| `skipped` | `absent` in one/both versions (added/removed), or not loaded in both |
| `unverifiable` | `_unsound(base.obs)` or `_unsound(head.obs)` returns a reason |
| `interface-change` | params differ **and** the divergence is an arity `TypeError` (one version can't accept the captured args) — not a behavior regression |
| `divergent` | first input where `not _same(base.obs[i], head.obs[i])` |
| `equivalent` | all inputs agree |

`timeout` is an `error` whose note is exactly `"timeout"` (a worker that exceeds
`_WORKER_TIMEOUT`); it is counted separately in the summary and **never** reads
as a divergence.

Divergent verdicts carry a **minimized witness** (`replay._minimize`): the
diverging input is reduced by type-aware simplification (`_simpler`) while it
still diverges, bounded by a candidate cap.

### 6.1 Exit codes — `replay._exit_code(rows, strict)`
| code | meaning |
|---|---|
| `0` | no divergence |
| `1` | ≥ 1 divergence |
| `2` | usage error (CLI) |
| `3` | `--strict` **and** some function was `error`/`timeout` |

`interface-change` and `skipped` are **not** failures and do not set a non-zero
code on their own.

---

## 7. Isolation & determinism guarantees

- Each (version, key) runs in its **own subprocess** from its own worktree/
  baseline — two versions of a package never share an interpreter; crashes and
  runaway loops are contained.
- Replay workers run with **`PYTHONHASHSEED=0`** for stable hash/set ordering
  across processes.
- Arguments are **deep-copied per run**, so a mutating call can't taint the next
  run and the post-call receiver state can be read.
- Per-function checks run in a thread pool (`min(8, cpu)`), each spawning short-
  lived workers; `_procs` reaps the whole subtree on kill.

### Tunable constants
| constant | default | env |
|---|---|---|
| `_CAP_PER_FUNC` | 300 | — |
| `_MAX_DEPTH` (canonical) | 60 | — |
| `_ITER_CAP` | 1000 | `PROBE_ITER_CAP` |
| `_WORKER_TIMEOUT` | 45 | `PROBE_WORKER_TIMEOUT` |
| `_CAPTURE_TIMEOUT` | 300 | `PROBE_CAPTURE_TIMEOUT` |
| `_REPLAY_MAX_ARGS` | off (1e5) | `PROBE_REPLAY_MAX_ARGS` |
| capture flush | 5s | `PROBE_CAPTURE_FLUSH_SECS` |
| `FROZEN_NOW` | 1_700_000_000.0 | — |

---

## 8. Module map

| module | responsibility |
|---|---|
| `cli.py` | subcommand dispatcher; installs the `_procs` reaper |
| `verify.py` | branch-vs-branch verify; config (`[tool.selfsame]`), refs, blind-spot report |
| `snapshot.py` | `snapshot` (freeze baseline) + `drift` (compare to baseline); `--changed-only` |
| `capture.py` | run a command with the hook injected; merge per-process captures; budget + benchmark guard |
| `_capture_hook.py` | import-hook wrapping of target functions; flush daemon; re-entrancy guard; entry-script profile |
| `replay.py` | orchestration: worker spawn, `_verdict`/`_unsound`/`_same`/`_minimize`, `_build_report`/`_render_markdown`/`_write_junit`, `_emit_results`, worktree mgmt, `_exit_code` |
| `_replay_worker.py` | per-version observation subprocess (functions + methods) |
| `canonical.py` | cross-process canonical form (§4); `_leaf_value` registry |
| `equality.py` | in-process structural equality (legacy `check` path) |
| `harness.py` | determinism control + `observe` (§5.2) |
| `effects.py` | recorded deterministic effect shims; `FROZEN_NOW` |
| `extract.py` | function pairing; `changed_keys`; `function_references` (file:line); module/path mapping |
| `_procs.py` | child-process reaper (no orphans) |
| `attach.py` | on-demand capture flush of a running hook-enabled process |
| `pytest_plugin.py` | compare-only drift gate at pytest session end |
| `generators.py` | type-hint input generation (legacy `check`) |
| `check.py` · `runner.py` · `model.py` | generation-based `check`; corpus demo; `Unit` dataclass |
| `fuzz.py` · `_cgfuzz_worker.py` · `_fuzz_worker.py` · `_mutate.py` | **experimental** capture-seeded differential fuzzing |

---

## 9. Invariants & extension points

**Invariants any change must keep**
- A reported `equivalent`/`divergent` is sound on the inputs checked; anything
  not soundly comparable is `unverifiable`/`error`/`skipped`, never a guess.
- Coverage equals the inputs the run exercised; what was *not* covered is
  surfaced (`unverified_changed`), never hidden.
- No third-party runtime dependency enters the core; heuristic/dep-heavy work
  stays optional and out-of-core.

**Where new perturbation sources plug in.** The engine separates *how inputs are
obtained* from *the sound comparator*. Today there are three input sources, all
feeding the same `canonical` + `_same` + verdict model:
1. **captured** (real args) — trusted; used by verify/snapshot/drift.
2. **generated** (type hints) — weak; legacy `check`.
3. **mutated** (havoc/coverage-guided) — experimental `fuzz`.

A new source (e.g. *perturbed values at a nominated dependency boundary* — the
assumption adjudicator) is a **fourth input source**: it produces observations
from the same worker/harness/canonical machinery, and its result is judged by the
same soundness model and serialized into a **distinct** report section. Keep any
*enumeration* of what to perturb out of the core (heuristic); the core only
*adjudicates* nominated candidates. See the design in
[adjudicator.md](adjudicator.md).

**Known debt**
- `canonical.py` and `equality.py` duplicate structural logic — unify or keep in
  lockstep.
- `check`/`generators` are the legacy generation path; capture-replay is the
  main path.
