# AI workflows

Selfsame is built to sit alongside AI coding agents. The problem it solves there is the one
everyone hits once an agent is generating code daily:

> A new feature works in the demo — but somewhere in those thousands of generated lines, an
> existing capability quietly broke. Tests are green on both sides; nobody notices until a
> user does.

There's usually **no clean "before" branch** to diff — there's a build you accepted and
whatever the agent did next. Selfsame reframes the comparison from *git branches* to
*accepted baseline → current code*.

## The loop: snapshot → generate → drift

```bash
# 1. A build passes review. Freeze its behavior as the accepted baseline.
selfsame snapshot --modules myapp -- pytest -q          # → .selfsame/snapshot.json

# 2. The agent develops the next feature (new code + edits to existing code).

# 3. Did any accepted behavior change?
selfsame drift                                          # exit 1 on any deviation
```

`snapshot` records, per function the tests exercise, the **real inputs** *and* the
**canonical behavior** of the accepted code (return value, exception, post-call object
state, plus io/threads/nondeterminism flags and the signature). It also stores the git rev
of the accepted build.

`drift` replays those **same inputs** against the current working tree and compares to the
frozen behavior — using the exact same sound verdicts as `verify`. No base worktree, no
second branch: the baseline *is* the snapshot file.

## A worked example

Start from an accepted build:

```python
# myapp/core.py  (the build you confirmed)
def discount(price, pct):
    return round(price * (1 - pct / 100), 2)

def greet(name):
    return "Hello, " + name + "!"

def total(items):
    return sum(items)
```

```bash
selfsame snapshot --modules myapp -- pytest -q
# froze 4 input(s) across 3 function(s) -> .selfsame/snapshot.json
```

Now the agent ships "the next feature" — it adds a function, refactors one, makes a
backward-compatible API tweak, and *accidentally changes an existing behavior*:

```python
def discount(price, pct, currency="$"):     # added an OPTIONAL param
    return round(price * (1 - pct / 100), 2)

def greet(name):
    return "Hi, " + name                     # ← silent regression

def total(items):
    acc = 0                                   # rewritten — same behavior
    for x in items:
        acc += x
    return acc

def tax(price, rate):                         # brand-new feature
    return round(price * rate / 100, 2)
```

```bash
selfsame drift
```

```
~ discount   n=2   interface-change   signature changed (added currency) — back-compatible
X greet      n=1   divergent          base 'Hello, Sam!'  →  head 'Hi, Sam'
  total      n=1   equivalent

selfsame: 1 equivalent · 1 divergent · 1 interface-change · 0 unverifiable · 1 unverified-changed
```

What each verdict tells the agent (or you):

| function | verdict | meaning |
|---|---|---|
| `greet` | **divergent** | the regression — existing behavior changed at a tested input. **This is the alarm.** |
| `total` | equivalent | rewritten, but provably behaves the same on the tested inputs |
| `discount` | interface-change | gained an *optional* parameter; old calls still behave identically (back-compatible, not a regression) |
| `tax` | *(not shown)* | brand-new — no baseline to deviate from, so it's not noise |
| `new_helper`* | unverified-changed | changed code with **no test baseline** — listed so you know it's a blind spot |

`drift` exits non-zero because of `greet`, so it blocks the build the same way a failing test
would.

## "Won't this flag thousands of changes at LLM velocity?"

No — and this is the key property. **The output scales with tested behavioral surface that
actually changed, not with lines of code:**

- Brand-new functions/features → no baseline → **0 flags**.
- Rewrites that preserve behavior → `equivalent` → **0 flags**.
- Back-compatible signature additions → `interface-change` → **not a regression**.
- Only a *real* behavior change at a *tested* input → `divergent`.

A 100,000-line generated change that adds features and preserves existing behavior produces
~zero divergences. You get flagged exactly where established behavior broke.

For very high change volume, scope the replay to what moved:

```bash
selfsame drift --changed-only      # replay only functions whose source changed since the snapshot
```

This makes cost track the touched surface (replay "50 of 5,000", not all 5,000) and lists
changed functions that have **no baseline** separately, so unverified new code is visible
rather than silently ignored. (Trade-off: it replays only *directly* changed functions, so a
divergence in an unchanged caller of a changed callee can be missed — run full `drift`
periodically to be exhaustive.)

## Make it automatic: the pytest plugin

Install the plugin so a drift check runs at the end of every normal test run — no separate
command to remember:

```ini
# pyproject.toml  ·  [tool.pytest.ini_options]   (or pytest.ini / tox.ini)
[pytest]
selfsame = true
```

or per-run:

```bash
pytest --selfsame -q
```

It is **compare-only by design**: at session end it replays the accepted baseline against
the current code and reports deviation, and **it never re-baselines**. A regression
therefore can't silently become the new "correct" behavior. You bless a new accepted build
*explicitly*:

```bash
selfsame snapshot --modules myapp -- pytest -q      # the only way to move the baseline
```

On drift the plugin fails the pytest session (non-zero exit) so CI catches it; add
`--selfsame-no-fail` to report without failing.

## The report: built for an agent to consume

Every `verify`/`drift` run writes a stable, machine-readable report so an AI agent knows it
ran and can act on it:

- `.selfsame/report.json` — `schema`, `summary`, per-function `verdict` with **`file:line`**,
  rendered `base`/`head`, the witness + minimized witness, soundness reason, and
  `unverified_changed` (changed functions with no baseline).
- `.selfsame/report.md` — the same, structured for an LLM to read.
- A one-line machine summary on stdout pointing at them.

```jsonc
// .selfsame/report.json (excerpt)
{
  "summary": { "equivalent": 1, "divergent": 1, "interface_change": 1, ... },
  "results": [
    { "function": "greet", "key": "myapp.core::greet", "verdict": "divergent",
      "file": "myapp/core.py", "line": 4,
      "input": "('Sam',)", "base": "'Hello, Sam!'", "head": "'Hi, Sam'" }
  ],
  "unverified_changed": [ { "key": "myapp.core::new_helper", "file": "myapp/core.py", "line": 10 } ]
}
```

An agent can read this, jump to `file:line`, see the exact before→after, and decide whether
the change was intended (then `snapshot` to bless it) or a regression (then fix it).

Relocate with `--report-dir`, or disable with `--no-report`. Also available:
`--json-out path` and `--junit-xml path` for pipelines.

## Proving a silent assumption is load-bearing (`adjudicate`, experimental)

Drift answers "did behavior change?" The adjudicator answers a sharper question for
AI-generated code: **this passes — but does the green secretly rest on something the model
never verified?** LLM code routinely leans on an unstated belief (`fx_rate` "never returns
None", a dict "has this key", a list "is ordered") it couldn't confirm under context limits.

`selfsame adjudicate` is a **judge, not a detective**: you (or an agent/tool) *nominate* a
candidate `(target, boundary)`; it holds the code fixed, deliberately violates the assumed
contract at the boundary (returns `none`/`zero`/`negative`/`wrong-type`, or `raises`), re-runs
on the captured inputs, and compares to the baseline:

```bash
selfsame adjudicate --assume target=myapp.billing::format_invoice,boundary=myapp.billing::fx_rate -- pytest -q
```
```
! format_invoice  assumes  fx_rate   load-bearing
    none   base 9.99 -> raises TypeError ...   @ (Order(currency='XYZ', amount=10),)
    raises base 9.99 -> raises RuntimeError ...
```

- **load-bearing** — a violation changed the result (with a minimized witness). The passing
  verdict was standing on this assumption.
- **not-load-bearing** — the code already tolerates it; no noise. (If a nomination never took
  effect, it says so: *boundary not invoked* — it can't masquerade as "tolerant".)
- **unverifiable** — couldn't compare soundly (io/threads/nondeterminism/opaque) → refuses.

Same three-state, zero-false-confidence model, pointed at a new axis. It uniquely *proves*
load-bearingness — every AI-review tool guesses and drowns in false positives. Advisory by
default (exit 0; `--fail-on-load-bearing` to gate), written to `.selfsame/assumptions.json`
(a separate artifact from drift's `report.json`). Full design and the violation set:
**[adjudicator.md](adjudicator.md)**.

## Where AI workflows fit — and where they don't

**Great fit**

- Regression guarding across agent iterations (the loop above).
- A CI gate that says "the accepted behavior still holds" after each generated change.
- Giving an agent a precise, navigable behavioral diff to reason about.

**Not what it does**

- It measures **deviation, not correctness.** It tells you behavior *changed*, not whether
  the new behavior is *right*. Correctness needs a spec/oracle independent of the AI — which
  a deterministic tool can't supply.
- Its resolution is your **test coverage.** A change on a path no test exercises won't show
  up as a divergence — but the report names those changed-but-untested functions so the
  blind spot is explicit. Value compounds as the accepted build's tests grow.
- The very first generation, with no baseline and no tests, can only be *characterized*, not
  verified. Accept it, snapshot it, and the safety net starts on the next iteration.

See [Limitations](limitations.md) for the full list, and [How it works](how-it-works.md) for
why the verdicts are trustworthy.
