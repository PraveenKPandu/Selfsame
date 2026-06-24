"""Assumption-adjudication worker (experimental).

Runs ONE candidate `(target, boundary)` against the current code: for each
captured input of `target`, observe it once normally (baseline) and once with the
`boundary` symbol monkeypatched to VIOLATE the assumed contract (return None,
raise, return a wrong type, ...), then compare canonically. A sound divergence
proves the behavior is load-bearing on that assumption.

Holds the code fixed and varies an assumption — the mirror image of the replay
worker, which holds the input fixed and varies the code. Reuses the same
harness/canonical/soundness machinery so the verdict carries the same
zero-false-confidence guarantee. See docs/adjudicator.md.

stdin  JSON: {worktree, module_name, qualname, boundary_module, boundary_name,
              violations: [...], args_b64: [...]}
stdout JSON: {loaded, error, boundary_invoked, violations: [
              {violation, result, witness?, base?, perturbed?, reason?}]}
"""

import base64
import copy
import inspect
import json
import os
import pickle
import sys
import tempfile

_WRONG_TYPE = "selfsame::wrong-type"


def _fresh_bytecode():
    """Compile the target from current source, never a stale .pyc (see
    probe/_replay_worker.py for why this matters on a live working tree)."""
    try:
        sys.dont_write_bytecode = True
        sys.pycache_prefix = tempfile.mkdtemp(prefix="probe_pyc_")
    except Exception:
        pass


def _make_stub(violation, counter):
    """A deterministic callable that replaces the boundary and emits a violation
    of the assumed contract. `counter` records that the boundary was reached."""
    def stub(*args, **kwargs):
        counter[0] += 1
        if violation == "none":
            return None
        if violation == "raises":
            raise RuntimeError("selfsame: assumption violated (boundary raised)")
        if violation == "zero":
            return 0
        if violation == "negative":
            return -1
        if violation == "empty":
            return ""
        if violation == "wrong-type":
            return _WRONG_TYPE
        return None
    return stub


def main() -> int:
    _fresh_bytecode()
    job = json.load(sys.stdin)
    out = {"loaded": False, "error": None, "boundary_invoked": False,
           "violations": []}
    try:
        wt = job["worktree"]
        for p in (os.path.join(wt, "src"), wt):
            if os.path.isdir(p):
                sys.path.insert(0, p)
        import importlib

        from probe import harness
        from probe.canonical import canonical
        from probe.replay import _render_obs, _same, _short, _simpler, _unsound

        module = importlib.import_module(job["module_name"])
        fn = module
        for part in job["qualname"].split("."):
            fn = getattr(fn, part)
        if not callable(fn):
            out["error"] = "target not callable"
            print(json.dumps(out))
            return 0
        out["loaded"] = True

        bmod = importlib.import_module(job["boundary_module"])
        bname = job["boundary_name"]
        if not hasattr(bmod, bname):
            out["error"] = ("boundary %s::%s not found (nominate the symbol as the "
                            "target references it)" % (job["boundary_module"], bname))
            print(json.dumps(out))
            return 0
        orig = getattr(bmod, bname)

        bound_classmethod = inspect.ismethod(fn)
        is_method = ("." in job["qualname"]) and not bound_classmethod

        def run_once(values):
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

        def observe(values):
            r1, s1, io, th = run_once(values)
            r2, s2, _, _ = run_once(values)   # determinism guard
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
            return rec

        blobs = [base64.b64decode(b) for b in job["args_b64"]]
        values_list = []
        for b in blobs:
            try:
                values_list.append(pickle.loads(b))
            except Exception:
                pass
        if not values_list:
            out["error"] = "no decodable inputs"
            print(json.dumps(out))
            return 0

        # Baseline (boundary normal). If we can't soundly establish the baseline,
        # the whole candidate is unverifiable — never guess.
        setattr(bmod, bname, orig)
        base_obs = [observe(v) for v in values_list]
        base_flag = _unsound(base_obs)
        if base_flag:
            out["violations"].append({"violation": "*", "result": "unverifiable",
                                      "reason": "baseline " + base_flag})
            print(json.dumps(out))
            return 0

        counter = [0]

        def perturbed_obs(values, stub):
            setattr(bmod, bname, stub)
            try:
                return observe(values)
            finally:
                setattr(bmod, bname, orig)

        def diverges(values, stub):
            pert = perturbed_obs(values, stub)
            base = observe(values)
            if _unsound([base]) or _unsound([pert]):
                return None
            return (not _same(base, pert)), base, pert

        def minimize(values, stub, cap=30):
            cur = list(values)
            evals = 0
            changed = True
            while changed and evals < cap:
                changed = False
                for i in range(len(cur)):
                    for cand in _simpler(cur[i]):
                        if evals >= cap:
                            break
                        evals += 1
                        trial = list(cur)
                        trial[i] = cand
                        r = diverges(trial, stub)
                        if r and r[0]:
                            cur = trial
                            changed = True
                            break
            return cur

        for violation in job["violations"]:
            stub = _make_stub(violation, counter)
            pert_obs = [perturbed_obs(v, stub) for v in values_list]
            flag = _unsound(pert_obs)
            if flag:
                out["violations"].append({"violation": violation,
                                          "result": "unverifiable", "reason": flag})
                continue
            witness_idx = None
            for i, (ob, oh) in enumerate(zip(base_obs, pert_obs)):
                if not _same(ob, oh):
                    witness_idx = i
                    break
            if witness_idx is None:
                out["violations"].append({"violation": violation,
                                          "result": "not-load-bearing"})
                continue
            mini = minimize(values_list[witness_idx], stub)
            base_at = observe(mini)
            pert_at = perturbed_obs(mini, stub)
            out["violations"].append({
                "violation": violation, "result": "load-bearing",
                "witness": _short(mini),
                "base": _render_obs(base_at), "perturbed": _render_obs(pert_at),
            })

        out["boundary_invoked"] = counter[0] > 0
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
