"""Replay worker: load ONE version of a module (package-aware, from a git
worktree) and run a function over captured arguments, emitting canonical
observations. Run as a subprocess so two versions of the same package never
share an interpreter.

stdin  JSON: {worktree, module_name, func_name, args_b64: [...]}
stdout JSON: {"loaded": bool, "error": str|null, "obs": [ {exc|val, io, threads}, ... ]}
"""

import base64
import json
import pickle
import sys


def main() -> int:
    job = json.load(sys.stdin)
    out = {"loaded": False, "error": None, "obs": []}
    try:
        sys.path.insert(0, job["worktree"])
        import importlib

        from probe import harness
        from probe.canonical import canonical

        module = importlib.import_module(job["module_name"])
        fn = getattr(module, job["func_name"], None)
        if not callable(fn):
            out["error"] = "function not found in this version"
            print(json.dumps(out))
            return 0
        out["loaded"] = True

        for blob in job["args_b64"]:
            values = pickle.loads(base64.b64decode(blob))
            obs = harness.observe(fn, tuple(values))
            rec = {"io": obs.counts.get("io", 0),
                   "threads": obs.counts.get("threads", 0)}
            if obs.exception is not None:
                rec["exc"] = obs.exception
            else:
                rec["val"] = canonical(obs.value)
            out["obs"].append(rec)
    except Exception as e:  # import/relative-import/etc.
        out["error"] = "%s: %s" % (type(e).__name__, e)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
