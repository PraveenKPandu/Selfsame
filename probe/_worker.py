"""Isolated worker: check one extracted function in its own process.

Reads a JSON job {before, after, name} from stdin, builds both versions of the
function, runs the full self-check + diff pipeline, and writes a JSON verdict to
stdout. Running per-unit in a subprocess contains crashes, infinite loops
(killed by the parent's timeout), and side effects of executing real code.

Note: isolation is per-unit, not per-call — the harness still runs the function
several times within this process. True per-call sandboxing (containers) is out
of scope for v0.1; see README.
"""

import json
import sys


def main() -> int:
    job = json.load(sys.stdin)
    name = job["name"]
    try:
        from probe.extract import build_function
        from probe.model import EXPECT_UNKNOWN, Unit
        from probe.runner import run_unit

        orig = build_function(job["before"], name)
        ref = build_function(job["after"], name)
        unit = Unit(name, "extracted", orig, ref, expect=EXPECT_UNKNOWN)
        res = run_unit(unit)
        out = {
            "verdict": res.verdict,
            "cause": res.cause,
            "witness": repr(res.witness) if res.witness is not None else None,
            "detail": res.detail,
        }
    except Exception as e:  # loading/parse/exec failure -> report, don't crash silently
        out = {"verdict": "error", "cause": "%s: %s" % (type(e).__name__, e),
               "witness": None, "detail": None}
    sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
