# Selfsame documentation

Selfsame is a **sound behavior checker** for Python: it captures real call arguments,
replays two versions of your code in isolated subprocesses, and compares the results
structurally — never reporting a verdict it can't stand behind.

Start here:

1. **[Getting started](getting-started.md)** — install and run your first check in a few minutes.
2. **[AI workflows](ai-workflows.md)** — the snapshot/drift loop, the pytest plugin, and agent-consumable reports for AI-driven development.
3. **[Command reference](commands.md)** — every command and flag.
4. **[Configuration](configuration.md)** — config file, environment variables, exit codes.
5. **[How it works](how-it-works.md)** — the capture → replay → compare engine and the soundness model.
6. **[Limitations](limitations.md)** — the honest boundaries; read this before you depend on a green result.
7. **[Architecture & spec](architecture.md)** — the normative engineering contract (data formats, canonical-form schema, soundness rules, verdict model, module map). For contributors and anyone extending the engine.

### Experimental

- **[Assumption adjudicator](adjudicator.md)** (`selfsame adjudicate`) — proves, soundly, whether a *nominated* assumption in code is load-bearing: perturb the assumption at its dependency boundary, re-run on captured inputs, compare. MVP shipped (experimental); specced against the architecture above.

## The core idea in one picture

```
  your tests / app run                two versions                  verdict
 ┌────────────────────┐   capture   ┌──────────────┐   replay    ┌──────────────┐
 │ real calls into     │ ─────────▶ │ base  (git/   │ ─────────▶ │ equivalent   │
 │ your code           │  (inputs)  │  snapshot)    │  same       │ divergent    │
 │                     │            │ head  (now)   │  inputs     │ unverifiable │
 └────────────────────┘            └──────────────┘             │ interface-…  │
                                                                  └──────────────┘
```

- **Inputs are real** — recorded from a run of your code, so no type hints or input
  generation are needed (methods, packages, relative imports all work).
- **Comparison is structural** — return value + exception + post-call object state, in a
  cross-process canonical form — not `repr()` string matching.
- **The guarantee is soundness** — anything that can't be compared deterministically
  (uncontrolled I/O, threads, nondeterminism, opaque values) is *refused*, never certified.

## Two ways to use it

| You have… | Use | Page |
|---|---|---|
| Two git refs / a working-tree refactor | `selfsame verify` | [Getting started](getting-started.md) |
| An accepted build + continuous (often AI-generated) changes | `selfsame snapshot` + `selfsame drift` | [AI workflows](ai-workflows.md) |
