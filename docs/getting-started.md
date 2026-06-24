# Getting started

## Install

```bash
pip install selfsame        # or: pipx install selfsame · uv tool install selfsame
```

- Installs the `selfsame` command (and `probe` as an alias). Everything is also runnable as
  `python -m probe.<command>`.
- Pure standard library — **no runtime dependencies**. Python 3.8+.

## Verify a refactor (two versions, your test inputs)

The main path: run it from your repo root and point it at the package you changed. Selfsame
runs your tests to capture real inputs, then replays the base version and your working tree
on those same inputs.

```bash
selfsame verify --base main --modules mypkg -- pytest -q
```

- `--base main` — the version to compare against (any git ref).
- `--head` — the version to compare; defaults to `WORKTREE` (your current checkout).
- `--modules mypkg` — comma-separated packages/modules to watch.
- Everything after `--` is **your** test command (pytest, unittest, tox, or even an app script).

Reading the output:

```
  parse_args                     n=11   equivalent
X slugify                        n=102  divergent     @ input #0
      input : ('Café', max_length=3)
      base  : 'caf'
      head  : 'caf-'
      minimized: ('ab', max_length=1)
  smart_truncate                 n=26   equivalent

----------------------------------------------------------------
Functions with captured inputs : 3
Sound auto-verify              : 3/3 = 100%
  verified -> equivalent : 2   divergent : 1   unverifiable : 0
  not verified -> skipped : 0   interface-change : 0   error : 0   timeout : 0
  ** 1 DIVERGENCE(S): behavior changed at a tested input **

selfsame: 2 equivalent · 1 divergent · ...  →  .selfsame/report.json
```

- `n=` is how many distinct captured inputs were replayed for that function.
- A **divergence** shows the exact input, the `base` vs `head` result, and a *minimized*
  witness (the smallest input that still diverges).
- The last line is a machine summary pointing at the report files (see
  [Configuration → Reports](configuration.md#reports)).

### Exit codes (drop it in CI)

| code | meaning |
|---|---|
| `0` | no divergence — safe |
| `1` | at least one behavior divergence |
| `2` | usage error |
| `3` | with `--strict`: a function couldn't be verified (error/timeout) |

### Only check what changed

On a PR you usually only care about functions whose body changed:

```bash
selfsame verify --base main --modules mypkg --changed-only -- pytest -q
```

## Your first snapshot + drift (no second branch)

When there's no "before" branch — you just have a working build and ongoing edits — freeze
the accepted behavior and measure deviation later. This is the recommended loop for
AI-generated code.

```bash
# freeze the behavior of the build you trust
selfsame snapshot --modules myapp -- pytest -q     # writes .selfsame/snapshot.json

# ...change things (or let an agent change them)...

# what deviated from the accepted behavior?
selfsame drift                                     # exit 1 if anything diverged
```

Full details and the AI integration (pytest plugin, working at high change velocity):
**[AI workflows](ai-workflows.md)**.

## Matching the target's Python

Because Selfsame **runs your code and tests**, it must use a Python your project supports.
If your repo declares `requires-python >= 3.10`, point Selfsame at a matching interpreter:

```bash
selfsame verify --base main --modules mypkg \
        --python /path/to/python3.10 -- python -m pytest -q
```

The repo's `requires-python` is checked and a mismatch is reported loudly instead of
silently capturing nothing.

## Less typing: a config file

Put your defaults in `pyproject.toml` so day-to-day runs need no flags:

```toml
[tool.selfsame]
base = "main"
modules = ["mypkg"]
changed_only = true
```

```bash
selfsame verify -- pytest -q     # base/modules/changed-only come from config
```

See **[Configuration](configuration.md)** for all options.

## Next steps

- [AI workflows](ai-workflows.md) — the snapshot/drift loop, the pytest plugin, and proving
  whether an assumption is load-bearing (`adjudicate`).
- [Command reference](commands.md) — every command and flag.
- [Limitations](limitations.md) — what a green result does and doesn't promise.
