# Configuration

## Config file: `[tool.selfsame]`

Set defaults in `pyproject.toml` (or a standalone `selfsame.toml`) so everyday runs need no
flags. Explicit CLI flags always override the config.

```toml
[tool.selfsame]
base = "main"
modules = ["mypkg", "mypkg.utils"]
changed_only = true
strict = false
# head = "HEAD"
# python = "/path/to/python3.11"
```

```bash
selfsame verify -- pytest -q     # base/modules/etc. come from config
```

> Config parsing uses `tomllib`, so it requires **Python 3.11+**. On older interpreters the
> config is ignored (pass the flags instead).

## Reports

By default every `verify`/`drift` run writes a stable, agent-consumable report and prints a
one-line machine summary pointing at it:

```
selfsame: 3 equivalent · 1 divergent · 0 interface-change · 0 unverifiable · 0 error · 0 timeout · 2 unverified-changed  →  .selfsame/report.json
```

| file | contents |
|---|---|
| `.selfsame/report.json` | `schema`, `environment`, `summary`, `results[]` (per-function: `verdict`, `file`, `line`, `base`, `head`, witness, `minimized`, soundness `reason`), and `unverified_changed[]` |
| `.selfsame/report.md` | the same, structured for an LLM to read |
| `.selfsame/assumptions.json` + `.md` | *(experimental)* `adjudicate` output — per nominated `(target, boundary)`: the `load-bearing`/`not-load-bearing`/`unverifiable` verdict per violation, witness, and `boundary_invoked` |

- `--report-dir <dir>` — write the report somewhere else.
- `--no-report` — don't write the default files.
- `--json-out <path>` — additionally write the JSON to a specific path.
- `--junit-xml <path>` — write JUnit XML (divergent → failure, error/timeout → error,
  skipped/unverifiable/interface-change → skipped) for CI test reporters.

Tip: add `.selfsame/` to your `.gitignore`.

## Exit codes

| code | meaning |
|---|---|
| `0` | no divergence |
| `1` | at least one behavior divergence |
| `2` | usage error |
| `3` | `--strict` and at least one function couldn't be verified (error/timeout) |

`interface-change` and `skipped` are **not** failures (they aren't behavior regressions), so
they don't set a non-zero exit on their own.

## Environment variables

| variable | default | effect |
|---|---|---|
| `PROBE_WORKER_TIMEOUT` | `45` | per-function replay timeout (seconds). On overload a function is reported `timeout` — never a false pass. Raise it or reduce load. |
| `PROBE_CAPTURE_TIMEOUT` | `300` | wall-clock budget for the capture command. On expiry, capture stops and proceeds with whatever was recorded. `0` disables. |
| `PROBE_KEEP_BENCHMARK` | unset | keep `pytest-benchmark` during capture (it's auto-disabled by default — its timing loops blow up under the hook). |
| `PROBE_ITER_CAP` | `1000` | how many items of a lazy iterator/generator return value are materialized before it's refused as opaque. |
| `PROBE_REPLAY_MAX_ARGS` | off | cap the number of captured inputs replayed per function (speed vs. coverage — off by default so divergence-triggering inputs aren't dropped). |
| `PROBE_CAPTURE_FLUSH_SECS` | `5` | how often the capture hook flushes to disk, so an abrupt kill still leaves a usable capture. |
| `PROBE_CAPTURE_FLUSH_SIGNAL` | `SIGUSR1` | the signal `attach` sends to trigger an on-demand flush. |
| `PYTHONHASHSEED` | set to `0` | the engine fixes this in replay workers so hash/set ordering is deterministic across processes. |

## pytest plugin options

The plugin (see [AI workflows](ai-workflows.md#make-it-automatic-the-pytest-plugin)) is
**compare-only** and never re-baselines.

| option / ini | meaning |
|---|---|
| `--selfsame` *(CLI)* or `selfsame = true` *(ini)* | run a drift check at the end of the test session |
| `--selfsame-snapshot <path>` | snapshot to compare against (default `.selfsame/snapshot.json`) |
| `--selfsame-no-fail` | report drift but don't fail the pytest session |

```ini
[pytest]
selfsame = true
```
