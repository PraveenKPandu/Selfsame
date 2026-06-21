"""Replay worker: load ONE version of a module (package-aware, from a git
worktree) and run a function/method over captured arguments, emitting canonical
observations. Runs as a subprocess so two versions of the same package never
share an interpreter.

stdin  JSON: {worktree, module_name, qualname, args_b64: [...]}
stdout JSON: {"loaded": bool, "error": str|null, "obs": [ {val|exc|nondet, io, threads}, ... ]}

qualname may be dotted ("ClassName.method"). For an instance method the captured
args[0] is `self`, which pickle rebuilds as THIS version's class (the worktree is
on sys.path), so the method runs against the right version. Classmethods (bound)
get their captured `cls` dropped.
"""

import base64
import inspect
import json
import pickle
import sys


def _resolve(module, qualname):
    obj = module
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj


def main() -> int:
    job = json.load(sys.stdin)
    out = {"loaded": False, "error": None, "obs": []}
    try:
        sys.path.insert(0, job["worktree"])
        import importlib

        from probe import harness
        from probe.canonical import canonical

        module = importlib.import_module(job["module_name"])
        fn = _resolve(module, job["qualname"])
        if not callable(fn):
            out["error"] = "not callable in this version"
            print(json.dumps(out))
            return 0
        out["loaded"] = True
        bound_classmethod = inspect.ismethod(fn)  # cls already bound

        for blob in job["args_b64"]:
            values = pickle.loads(base64.b64decode(blob))
            call_args = tuple(values[1:]) if bound_classmethod else tuple(values)
            o1 = harness.observe(fn, call_args)
            o2 = harness.observe(fn, call_args)  # cheap determinism guard
            rec = {"io": o1.counts.get("io", 0), "threads": o1.counts.get("threads", 0)}
            if not o1.same_behavior(o2):
                rec["nondet"] = True
            elif o1.exception is not None:
                rec["exc"] = o1.exception
            else:
                rec["val"] = canonical(o1.value)
            out["obs"].append(rec)
    except Exception as e:  # import / relative-import / unpickle error
        out["error"] = "%s: %s" % (type(e).__name__, e)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
