# Command reference

Every command is available as `selfsame <cmd>` (alias `probe <cmd>`) or
`python -m probe.<cmd>`. Anything after `--` is a command **you** provide that runs your code.

---

## `verify` — compare two versions on your test inputs

```bash
selfsame verify --base <ref> [--head <ref>] --modules <pkgs> [options] -- <test command>
```

Captures inputs from the test command, replays base vs head in isolated subprocesses, and
prints a per-function verdict.

| flag | default | meaning |
|---|---|---|
| `--base <ref>` | *(required¹)* | git ref to compare against |
| `--head <ref>` | `WORKTREE` | git ref to compare (default: current working tree) |
| `--modules <csv>` | *(required¹)* | comma-separated modules/packages to watch |
| `--python <path>` | this interpreter | interpreter to run the tests + replay workers under |
| `--changed-only` | off | only check functions whose body changed between base and head |
| `--strict` | off | exit `3` if any function couldn't be verified (error/timeout) |
| `--no-minimize` | off | don't shrink divergence witnesses to a minimal input |
| `--json-out <path>` | — | also write the JSON report here |
| `--junit-xml <path>` | — | write a JUnit XML report (for CI test reporters) |
| `--report-dir <dir>` | `.selfsame` | where `report.json` + `report.md` go |
| `--no-report` | off | don't write the default report files |

¹ `--base` and `--modules` may instead come from `[tool.selfsame]` (see [Configuration](configuration.md)).

Exit codes: `0` clean · `1` divergence · `2` usage · `3` `--strict` and something unverifiable.

---

## `snapshot` — freeze the accepted build's behavior

```bash
selfsame snapshot --modules <pkgs> [--out <path>] [--python <path>] -- <test command>
```

Captures inputs and records the current code's canonical behavior into a baseline file
(default `.selfsame/snapshot.json`, with the build's git rev). This is the **only** way to
establish or move the baseline — by design.

| flag | default | meaning |
|---|---|---|
| `--modules <csv>` | *(required)* | modules/packages to snapshot |
| `--out <path>` | `.selfsame/snapshot.json` | snapshot file to write |
| `--python <path>` | this interpreter | interpreter to run tests + workers under |

---

## `drift` — measure deviation from the baseline

```bash
selfsame drift [--snapshot <path>] [--changed-only] [--strict] [options]
```

Replays the snapshot's stored inputs against the current working tree and reports deviation.
Needs no test command — the inputs come from the snapshot.

| flag | default | meaning |
|---|---|---|
| `--snapshot <path>` | `.selfsame/snapshot.json` | baseline to compare against |
| `--python <path>` | this interpreter | interpreter for replay workers |
| `--changed-only` | off | replay only functions whose source changed since the snapshot |
| `--strict` | off | exit `3` if any function couldn't be verified |
| `--report-dir <dir>` | `.selfsame` | where the report goes |
| `--no-report` | off | don't write the report files |

Same exit codes and report format as `verify`.

---

## `capture` — record inputs from any run

```bash
selfsame capture --modules <pkgs> --out caps.pkl [--funcs <csv>] [--capture-dir <dir>] -- <command>
```

Records real call arguments while *any* command runs your code (tests, a script, a server),
into a pickle you can replay later. The capture hook is injected into every spawned process,
so it works across subprocesses too.

| flag | meaning |
|---|---|
| `--modules <csv>` | modules/packages to capture (required) |
| `--out <path>` | output pickle (required) |
| `--funcs <csv>` | optional allow-list of names/qualnames |
| `--capture-dir <dir>` | stable directory for per-process dumps (useful with `attach`) |

---

## `replay` — replay a capture across two refs

```bash
selfsame replay <repo> <base_ref> <head_ref> <caps.pkl>
```

The replay half of `capture` + `replay`, when you captured separately (e.g. from a real app
run). Materializes each ref as a git worktree and compares.

---

## `attach` — dump a running process's captures

```bash
selfsame attach <pid> --capture-dir <dir>
```

Sends the capture hook's flush signal (default `SIGUSR1`, see `PROBE_CAPTURE_FLUSH_SIGNAL`) to
a **process already started under the hook**, so it writes its current captures without
stopping. It does *not* inject into an arbitrary unmodified process.

```bash
# start under capture with a known dump dir, then dump it later from another shell
selfsame capture --modules myapp --capture-dir ./caps --out caps.pkl -- python -m myapp serve
selfsame attach <pid> --capture-dir ./caps      # writes ./caps/cap-<pid>.pkl, process keeps running
```

---

## `check` — generated inputs for typed pure functions

```bash
selfsame check before.py after.py
selfsame check --git <base> <head> path/to/file.py
```

The original, generation-based path: it extracts top-level functions present in both
versions, pairs those with unchanged signatures, generates inputs from type hints, and
checks each in isolation. Works on **deterministic, type-hinted functions**; for real
packages and untyped code, prefer `verify`/`snapshot`. See
[How it works → generation vs capture](how-it-works.md#two-ways-to-get-inputs).

---

## `fuzz` *(experimental)* — find divergences beyond your tests

```bash
selfsame fuzz <repo> <base> <head> <caps.pkl> [budget]
```

Capture-seeded differential fuzzing: mutates the real captured inputs (coverage-guided
havoc, dictionary tokens, crossover) to reach inputs your tests never exercised, then reports
any divergence. Soundness is preserved — unsound inputs are skipped, never reported.

---

## `adjudicate` *(experimental)* — prove whether a nominated assumption is load-bearing

```bash
selfsame adjudicate --assume target=pkg::fn,boundary=pkg::dep -- pytest -q
selfsame adjudicate --assumptions .selfsame/assumptions.toml --snapshot .selfsame/snapshot.json
```

Holds the code fixed, deliberately **violates** a nominated assumption at its dependency
`boundary` (returns `none`/`zero`/`negative`/`wrong-type`, or `raises`), re-runs `target`
on its captured inputs, and compares to the baseline — reporting **load-bearing** (with a
minimized witness), **not-load-bearing**, or **unverifiable**. It is a *judge, not a
detective*: you nominate candidates (`--assume`, repeatable; or a `[[assume]]` TOML via
`--assumptions`); it never enumerates them. Advisory by default (exit 0);
`--fail-on-load-bearing` gates CI. Writes `.selfsame/assumptions.json` + `.md`. Full design:
[adjudicator.md](adjudicator.md).

---

## `demo`

```bash
selfsame demo
```

Runs the engine against the bundled corpus (`units/`) end-to-end — a quick way to see the
verdicts (including the positive controls firing).

---

## Verdicts

| verdict | meaning |
|---|---|
| `equivalent` | provably the same behavior on every tested input |
| `divergent` | behavior changed at a tested input (shows input + base→head + minimized witness) |
| `interface-change` | a signature change makes the versions un-callable on the same args (not a behavior regression) |
| `unverifiable` | refused — uncontrolled I/O / threads / nondeterminism / opaque value (with the cause) |
| `skipped` | function absent in one version (added/removed) |
| `error` / `timeout` | couldn't run (import error, replay exceeded `PROBE_WORKER_TIMEOUT`) — never a false pass |
| `unsupported` | (`check` only) no input-generation strategy for the parameter types |
