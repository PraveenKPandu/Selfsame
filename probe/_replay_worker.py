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
import os
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
        # Support both flat (pkg/) and src (src/pkg/) layouts; insert at front so
        # the worktree version shadows any installed copy of the package.
        wt = job["worktree"]
        for p in (os.path.join(wt, "src"), wt):
            if os.path.isdir(p):
                sys.path.insert(0, p)
        import importlib

        from probe import harness
        from probe.canonical import canonical

        module = importlib.import_module(job["module_name"])
        try:
            fn = _resolve(module, job["qualname"])
        except AttributeError:
            # module imported fine but the function isn't here: it was added or
            # removed across versions. Report 'absent' (not an error) so the
            # verdict can be 'skipped', not a spurious failure.
            out["absent"] = True
            print(json.dumps(out))
            return 0
        if not callable(fn):
            out["error"] = "not callable in this version"
            print(json.dumps(out))
            return 0
        out["loaded"] = True
        try:
            out["params"] = list(inspect.signature(fn).parameters)
        except (TypeError, ValueError):
            out["params"] = None
        import copy
        bound_classmethod = inspect.ismethod(fn)  # cls already bound
        qualname = job["qualname"]
        is_method = ("." in qualname) and not bound_classmethod

        def run_once(values):
            # Deep-copy so a mutating call doesn't taint the next run, and so we
            # can read the receiver's post-call state. Behavior of a method =
            # return value PLUS how it mutated self.
            try:
                args = copy.deepcopy(values)
            except Exception:
                args = values
            call = tuple(args[1:]) if bound_classmethod else tuple(args)
            o = harness.observe(fn, call)
            ret = ("exc", o.exception) if o.exception is not None \
                else ("val", canonical(o.value))
            state = None
            if is_method and args:
                try:
                    state = canonical(args[0])
                except Exception:
                    state = ["opaque", "self"]
            return ret, state, o.counts.get("io", 0), o.counts.get("threads", 0)

        for blob in job["args_b64"]:
            values = pickle.loads(base64.b64decode(blob))
            r1, s1, io, th = run_once(values)
            r2, s2, _, _ = run_once(values)  # determinism guard (fresh copy)
            rec = {"io": io, "threads": th}
            if r1 != r2 or s1 != s2:
                rec["nondet"] = True
            else:
                if r1[0] == "exc":
                    rec["exc"] = r1[1]
                else:
                    rec["val"] = r1[1]
                if is_method:
                    rec["self_after"] = s1
            out["obs"].append(rec)
    except Exception as e:  # import / relative-import / unpickle error
        out["error"] = "%s: %s" % (type(e).__name__, e)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
