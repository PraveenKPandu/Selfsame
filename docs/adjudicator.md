# Design: the assumption adjudicator (experimental)

> **Status:** MVP **implemented** (experimental), targeting v0.3.0 — `selfsame
> adjudicate`, `probe/adjudicate.py` + `probe/_adjudicate_worker.py`. Staged like
> `fuzz` (not blessed as sound until the `experiments/` corpus shows 0%
> confidently-wrong). This document specifies it against the engine contract in
> [architecture.md](architecture.md); section references below (§N) point there.
>
> **MVP scope shipped:** violations `none`/`raises`/`wrong-type`/`zero`/`negative`;
> CLI (`--assume`) + `.selfsame/assumptions.toml` nomination; baseline from a test
> command or `--snapshot`; in-worker witness minimization; report written to
> `.selfsame/assumptions.json` + `.md` (a **separate artifact** from verify/drift's
> `report.json`, to keep the two blindspot types distinct — see §3); advisory exit
> (`--fail-on-load-bearing` to gate). **Deferred (v0.3.x):** shape-aware
> `empty`/`missing-key`/`reordered`, candidate ranking, an out-of-core heuristic
> proposer.
>
> **Known MVP limitation:** witness minimization can over-reduce a numeric witness
> to a degenerate case (e.g. `amount=0`, where the divergence is only `0` vs `0.0`).
> The verdict stays sound; the witness is just less illustrative. Tracked for
> v0.3.x.

## 1. What it is — in one sentence

It takes a single assumption that code is silently resting on, deliberately
**violates** that assumption at its dependency boundary, re-runs the *same* code on
the *same captured inputs*, and reports — soundly — whether the passing behavior
actually depended on it.

Normal Selfsame holds the **input** fixed and varies the **code** ("did the
refactor change behavior?"). The adjudicator holds the **code** fixed and varies
an **assumption** ("does this behavior secretly depend on X?"). It is a fourth
input source (§9) feeding the same canonical comparator and soundness model.

## 2. Why it exists (the wedge)

LLM-generated code frequently passes its tests while leaning on something the
model never saw — `fx_rate` "never returns None", a dict "has this key", a list
"is ordered". Every AI-review tool guesses, via model reasoning, whether such an
assumption matters, and drowns in false positives. **Nobody proves it.** Selfsame
can: perturb the assumed value, compare canonically, and render a sound verdict
with a witness. That mechanism — deterministic, no model call, reproducible — is
the one thing the landscape lacks.

## 3. Judge, not detective (the hard scope boundary)

The adjudicator **does not discover** which assumptions exist. Enumeration —
symbol resolution, wrapping pyright/ruff, stub-spotting — is heuristic, has a
known ~70% ceiling, and is dependency-heavy (pyright runs on Node). It would
break **both** engine invariants (§ "zero false confidence", pure stdlib). So:

- **Out of core:** enumeration. A user, an agent, or a clearly-labeled optional
  out-of-core helper **nominates** candidate assumptions.
- **In core:** adjudication. Given a nominated candidate, render a sound,
  witnessed verdict on whether it is load-bearing.

### Two blindspots — keep them distinct (naming discipline)
- **Coverage blindspot** *(already shipped, 0.2.0)* — "I never tested this":
  changed functions with no captured inputs, in `report.json.unverified_changed`.
- **Assumption blindspot** *(this design)* — "this passes, but the green rests on
  X, which was never verified": a load-bearing dependency, in a new
  `report.json.assumptions` section.

The first says *what I didn't look at*; the second says *what the passing verdict
is standing on*. They must never share a label or a report field.

## 4. The model

For a candidate `(target, boundary)` and each captured input of `target`:

```
baseline   = observe(target(input))                      # boundary behaves normally
perturbed  = observe(target(input))  with boundary made to violate the assumption
compare(baseline, perturbed)         # same canonical form + _same as §5.2
```

Per input × violation:

| outcome | meaning |
|---|---|
| sound divergence (`not _same`) | **load-bearing** — the behavior depended on it; emit the minimized witness |
| sound equality (`_same`) | **not-load-bearing** — the code already tolerates it; no noise |
| either run `_unsound` (§5.1), or boundary not injectable | **unverifiable** — refuse, don't guess |

This is the engine's existing two-observation comparison (§6) with `base =
baseline`, `head = perturbed` — but relabeled, because the *question* is
different (load-bearingness, not version divergence).

## 5. Inputs

### 5.1 Candidate
A candidate is `(target, boundary, violations?)`:

- **target** — `module::qualname` (§2 of the spec) of the function under
  adjudication. Must have a baseline (captured inputs or a snapshot record).
- **boundary** — the symbol whose result the target assumes, expressed as the
  **reference site as seen by the target** (e.g. `myapp.billing::fx_rate` when
  `billing.py` did `from myapp.fx import fx_rate`). This makes injection robust to
  import-binding (see §6.1). The boundary's defining module
  (`myapp.fx::fx_rate`) is also accepted.
- **violations** — optional subset of the library (§7); default = all applicable.

Nomination formats (any one):
```toml
# .selfsame/assumptions.toml
[[assume]]
target     = "myapp.billing::format_invoice"
boundary   = "myapp.billing::fx_rate"
violations = ["none", "raises", "zero"]     # optional
```
```bash
selfsame adjudicate --assume target=myapp.billing::format_invoice,boundary=myapp.billing::fx_rate -- pytest -q
selfsame adjudicate --assumptions .selfsame/assumptions.toml --snapshot .selfsame/snapshot.json
```

### 5.2 Baseline
Captured inputs for `target`, from either:
- a fresh capture (`-- <test cmd>`, like `verify`/`snapshot`), or
- an existing `--snapshot` / capture pickle.

If `target` has no captured inputs, the candidate is `unverifiable`
("no baseline") — and surfaced as a coverage blindspot too.

## 6. Mechanism against the v0.2.0 internals

New, isolated pieces (everything else is reuse):
- `probe/adjudicate.py` — orchestrator + CLI (`record_*`/`main`), sibling to
  `fuzz.py`.
- `probe/_adjudicate_worker.py` — per-candidate subprocess, mirrors
  `_replay_worker.py` (§3.3/3.4).
- new CLI subcommand `adjudicate` in `cli.py`.

Reused unchanged: capture (§3.1) / snapshot (§3.2); `harness.observe` (§5.2);
`canonical` (§4); `_unsound` / `_same` (§5); `_minimize` (§6); `_emit_results` /
`_build_report` (§3.5) extended with one new section.

### 6.1 Boundary injection (the one genuinely new bit)
In the worker, for the perturbed run:

```python
mod, name = split(boundary)            # the reference site
orig = getattr(mod, name)
setattr(mod, name, violation_stub)     # stub ignores args, returns/raises the violation
try:
    perturbed = harness.observe(target, args)
finally:
    setattr(mod, name, orig)
```

- The stub is a fixed, deterministic callable: `lambda *a, **k: <violation value>`
  (or one that raises). It replaces *what the boundary returns*, which is exactly
  "the assumption about the boundary's result is wrong".
- **Injection precision.** Patching a module attribute only affects look-ups
  through that attribute at call time. Code that bound the name at import
  (`from x import f`) holds its own reference; that is why a candidate names the
  **reference site as seen by the target** (§5.1). The worker patches there. If
  the target also reaches the boundary via the defining module, patch both sites.
- **Injectability check.** Before adjudicating, confirm the symbol exists at the
  patch site and the baseline run actually invokes it (instrument the stub with a
  call counter on a no-op pass). If the symbol is absent → `unverifiable`
  ("boundary not found"). If the boundary is **never invoked** for an input, the
  violation cannot matter → that input is `not-load-bearing` *and* flagged
  `boundary-not-invoked` so a nominator knows the candidate was inert.

This keeps soundness: we never emit `load-bearing`/`not-load-bearing` unless the
injection demonstrably took effect and both runs were sound; otherwise we refuse.

## 7. Violation library (per the assumed contract)

Each violation encodes a thing the model implicitly assumed wouldn't happen. The
adjudicator tries the applicable set; the **first sound divergence proves
load-bearingness** for that candidate (the rest still run, to report which
violations matter).

| violation | stub returns / does | the assumption it breaks |
|---|---|---|
| `none` | `None` | "the result is never None" |
| `raises` | raises `RuntimeError` | "this call never fails" |
| `empty` | `""` / `[]` / `{}` / `set()` | "the result is non-empty" (shape-matched to baseline return) |
| `wrong-type` | a value of a different category (str↔int↔list) | "the result has the type I expect" |
| `zero` / `negative` | `0` / `-1` | "the number is positive / non-zero" |
| `missing-key` *(v0.3.x)* | baseline dict minus one key | "this key is present" |
| `reordered` *(v0.3.x)* | baseline sequence reversed | "ordering is stable" |

`empty`/`missing-key`/`reordered` are **shape-aware**: they read the baseline
return value to construct a faithful violation (e.g. only apply `reordered` if the
boundary returned a sequence). MVP (v0.3.0) ships the shape-free ones (`none`,
`raises`, `wrong-type`, `zero`/`negative`); shape-aware ones follow in v0.3.x.

## 8. Verdict & output

### 8.1 Vocabulary
Per candidate (aggregated across its violations):

- **load-bearing** — ≥ 1 violation produced a sound divergence. Carries the
  offending violation(s), the `base`→`perturbed` rendered results, and a
  **minimized witness** input.
- **not-load-bearing** — all applicable violations were sound and left behavior
  unchanged (on the captured inputs).
- **unverifiable** — could not compare soundly (io/threads/nondeterminism/opaque,
  per §5.1) or could not inject the boundary.

Same three-state, zero-false-confidence shape as the rest of the engine; new
labels keep it distinct from `divergent`/`equivalent`.

### 8.2 Report (`report.json`, new section — see spec §3.5)
```jsonc
"assumptions": [
  {
    "target": "myapp.billing::format_invoice",
    "boundary": "myapp.billing::fx_rate",
    "verdict": "load-bearing",
    "file": "myapp/billing.py", "line": 12,
    "violations": [
      { "violation": "none",  "result": "load-bearing",
        "witness": "(Order(currency='XYZ', amount=10),)",
        "base": "9.99", "perturbed": "raises TypeError" },
      { "violation": "raises", "result": "load-bearing", "witness": "..." },
      { "violation": "zero",   "result": "not-load-bearing" }
    ]
  }
]
```

### 8.3 Exit code — advisory, not a gate
Blindspot detection is an **advisory** signal (especially for an agent mid-task),
not a pass/fail gate like `verify`/`drift`. Default: **exit 0** regardless of
findings; print the ranked list + write the report. Opt in to gating with
`--fail-on-load-bearing` (→ exit 1 if any load-bearing). This is the "two output
modes, one engine" rule — don't force the gate API onto the advisory use.

## 9. Worked example

```python
# myapp/billing.py
from myapp.fx import fx_rate
def format_invoice(order):
    rate = fx_rate(order.currency)        # assumed: returns a number, never None
    return round(order.amount * rate, 2)
```

Candidate: `target = myapp.billing::format_invoice`, `boundary =
myapp.billing::fx_rate`. Captured inputs come from the suite.

- violation `none` → `fx_rate` returns `None` → `order.amount * None` raises
  `TypeError`; baseline returned `9.99` → **sound divergence → load-bearing**,
  witness = the minimized order.
- violation `raises` → propagates → divergence → **load-bearing**.
- violation `zero` → returns `0.0` → `round(amount*0, 2) == 0.0`; baseline `9.99`
  → divergence → **load-bearing** (the result depends on the rate's magnitude).

Verdict: `format_invoice` rests load-bearingly on `fx_rate`'s contract; here are
the witnesses. Contrast: if the code were `rate = fx_rate(...) or 1.0`, the
`none` violation would be **not-load-bearing** — no noise.

## 10. Soundness analysis (why "green means green" survives)

- **load-bearing** is emitted only when both baseline and perturbed runs are sound
  (§5.1) *and* their canonical forms differ (§5.2) *and* the injection provably
  took effect (§6.1). That is a proven causal dependency at a real input — not a
  guess.
- **not-load-bearing** requires all runs sound and equal; it is scoped to the
  captured inputs and tried violations (same coverage caveat as everywhere — the
  report still names untested targets as coverage blindspots).
- Anything that cannot be compared or injected → **unverifiable**. The engine
  never invents a verdict.
- The perturbation is deterministic; the determinism harness still runs each
  configuration twice and refuses on `nondet`.

## 11. Staging & validation

- Ship **experimental**, like `fuzz` — not blessed as sound until the
  `experiments/` corpus (with positive controls: known load-bearing and known
  tolerated assumptions) shows **0% confidently-wrong**.
- Sequencing: this is a v0.3+ increment **after** the verify/drift/coverage-
  blindspot loop has real users. Don't let it pull focus from making "zero false
  confidence" felt.

## 12. Phasing

- **v0.3.0 MVP** — `selfsame adjudicate`; violations `none`/`raises`/`wrong-type`/
  `zero`/`negative`; CLI + `.selfsame/assumptions.toml` nomination; `assumptions`
  report section; advisory exit (opt-in gate); experiments corpus.
- **v0.3.x** — shape-aware violations (`empty`/`missing-key`/`reordered`);
  candidate ranking by blast radius; an optional, clearly-labeled, out-of-core
  heuristic **candidate proposer** (wraps pyright/ruff) that pipes nominations in
  — never touching the core.

## 13. Open questions / risks

- **Injection binding** — the import-by-name case (§6.1). Mitigated by nominating
  the reference site and refusing when not injectable. Worth a small test matrix.
- **Broad except in the target** swallows perturbations → reports
  not-load-bearing. This is *correct* by the behavioral definition, but may
  surprise; document it.
- **Shape-aware violations** need to read the baseline return to construct a
  faithful violation — adds a dependency on having observed it; defer to v0.3.x.
- **Candidate explosion** — many targets × boundaries × violations. Bound it
  (cap violations per candidate; reuse `_REPLAY_MAX_ARGS`-style limits) and lean
  on the advisory, ranked output rather than exhaustive runs.
