"""Mutation worker: expand captured seeds into mutated inputs.

Runs in a worktree (so captured objects like a method's `self` can be unpickled
against their real classes), generates mutations with probe._mutate, and returns
the full input set — seeds + mutations — as base64 pickles tagged by origin, each
with a safe repr for display. The orchestrator then replays this SAME set on both
versions, so base and head see identical inputs.

stdin  JSON: {worktree, module_name, qualname, seeds_b64: [...], budget}
stdout JSON: {error, inputs: [{origin: "seed"|"fuzz", b64, repr}]}
"""

import base64
import json
import os
import pickle
import sys


def main() -> int:
    job = json.load(sys.stdin)
    out = {"error": None, "inputs": []}
    try:
        wt = job["worktree"]
        for p in (os.path.join(wt, "src"), wt):
            if os.path.isdir(p):
                sys.path.insert(0, p)
        # importing the module makes captured classes resolvable for unpickling
        import importlib

        from probe._mutate import arg_set_mutations
        try:
            importlib.import_module(job["module_name"])
        except Exception:
            pass  # primitive-only seeds still work without the module

        budget = int(job.get("budget", 200))
        seen = set()
        inputs = []

        def add(values, origin):
            try:
                blob = pickle.dumps(list(values))
            except Exception:
                return
            h = hash(blob)
            if h in seen:
                return
            seen.add(h)
            try:
                rep = repr(tuple(values))
            except Exception:
                rep = "<unreprable>"
            if len(rep) > 120:
                rep = rep[:117] + "..."
            inputs.append({"origin": origin,
                           "b64": base64.b64encode(blob).decode("ascii"),
                           "repr": rep})

        seeds = []
        for b in job["seeds_b64"]:
            try:
                seeds.append(pickle.loads(base64.b64decode(b)))
            except Exception:
                continue

        for s in seeds:
            add(s, "seed")
        for s in seeds:
            for m in arg_set_mutations(s):
                if len([i for i in inputs if i["origin"] == "fuzz"]) >= budget:
                    break
                add(m, "fuzz")

        out["inputs"] = inputs
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
