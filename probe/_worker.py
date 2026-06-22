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
        from probe.extract import build_function, io_capability
        from probe.generators import literal_seeds, mine_literals
        from probe.model import EXPECT_UNKNOWN, Unit
        from probe.runner import run_unit

        # Static I/O quarantine: refuse functions that can touch the network /
        # subprocess even if the sampled inputs never reach that path.
        io_reason = io_capability(job["before"], name) or io_capability(job["after"], name)
        if io_reason:
            print(json.dumps({"verdict": "unverifiable", "cause": "uncontrolled-io",
                              "witness": None, "detail": io_reason}))
            return 0

        orig = build_function(job["before"], name)
        ref = build_function(job["after"], name)

        # Mine magic values from both versions and feed them as inputs, so bugs
        # that hinge on a specific literal aren't missed by the fixed pool.
        lits = mine_literals(job["before"], name)
        for t, vals in mine_literals(job["after"], name).items():
            for v in vals:
                if v not in lits[t]:
                    lits[t].append(v)

        unit = Unit(name, "extracted", orig, ref, expect=EXPECT_UNKNOWN)
        try:
            unit.seeds = literal_seeds(orig, lits)
        except Exception:
            pass
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
