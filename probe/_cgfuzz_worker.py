"""Coverage-guided exploration worker (AFL-style feedback loop).

Runs in the head worktree. Starting from captured seeds, it repeatedly: pick a
corpus input, havoc-mutate it (probe._mutate.mutate_one), run the function while
tracing which branch EDGES (prev_line -> cur_line) of the target module execute,
and — if the run hit a *new* edge — keep the mutated input in the corpus. Edge
coverage drills through nested branches that blind one-shot mutation can't reach.
Deterministic (seeded RNG).

It only *explores* (head version, for coverage) and emits an enriched input
corpus; the sound base-vs-head differential comparison happens later in fuzz.py.

stdin  JSON: {worktree, module_name, qualname, seeds_b64, budget, cap}
stdout JSON: {error, inputs: [{origin, b64, repr}], coverage: {seed, total,
              execs, corpus}}
"""

import base64
import copy
import inspect
import json
import os
import pickle
import random
import sys


def main() -> int:
    job = json.load(sys.stdin)
    out = {"error": None, "inputs": [], "coverage": {}}
    try:
        wt = job["worktree"]
        for p in (os.path.join(wt, "src"), wt):
            if os.path.isdir(p):
                sys.path.insert(0, p)
        import importlib

        from probe._mutate import alphabet_from, mutate_one
        from probe.canonical import canonical

        module = importlib.import_module(job["module_name"])
        fn = module
        for part in job["qualname"].split("."):
            fn = getattr(fn, part)
        bound_classmethod = inspect.ismethod(fn)
        try:
            target_file = inspect.getsourcefile(fn) or getattr(module, "__file__", None)
        except TypeError:
            target_file = getattr(module, "__file__", None)

        seeds = []
        for b in job["seeds_b64"]:
            try:
                seeds.append(pickle.loads(base64.b64decode(b)))
            except Exception:
                continue
        alphabet = alphabet_from(seeds)
        budget = int(job.get("budget", 2000))
        cap = int(job.get("cap", 200))
        rng = random.Random(0)

        covered = set()
        seen_outcomes = set()   # distinct head outputs/exceptions seen
        corpus = []             # (values, origin, blob)
        seen = set()

        def trace_run(values):
            cov = set()
            last = [None]   # previous line in the target file (for edge coverage)

            def gtr(frame, event, arg):
                if event == "call" and frame.f_code.co_filename == target_file:
                    return ltr
                return None

            def ltr(frame, event, arg):
                if event == "line":
                    # branch-EDGE coverage: (prev_line -> cur_line). Finer than
                    # line coverage — distinguishes different control-flow paths
                    # through the same set of lines.
                    cov.add((last[0], frame.f_lineno))
                    last[0] = frame.f_lineno
                return ltr

            call = list(values[1:]) if bound_classmethod else list(values)
            try:
                call = copy.deepcopy(call)
            except Exception:
                pass
            sys.settrace(gtr)
            outcome = None
            try:
                rv = fn(*call)
                try:
                    outcome = json.dumps(canonical(rv))
                except Exception:
                    outcome = "<unrepr>"
            except Exception as e:
                outcome = "exc:" + type(e).__name__
            finally:
                sys.settrace(None)
            return cov, outcome

        def add(values, origin):
            try:
                blob = pickle.dumps(list(values))
            except Exception:
                return False
            h = hash(blob)
            if h in seen:
                return False
            seen.add(h)
            corpus.append((values, origin, blob))
            return True

        for s in seeds:
            if add(s, "seed"):
                cov, outcome = trace_run(s)
                covered |= cov
                seen_outcomes.add(outcome)
        seed_edges = len(covered)

        execs = 0
        n_fuzz = 0
        while execs < budget and corpus and n_fuzz < cap:
            execs += 1
            base_values = rng.choice(corpus)[0]
            mutated = mutate_one(base_values, rng, alphabet)
            cov, outcome = trace_run(mutated)
            # Keep an input that reaches a new EDGE (branchy code) OR produces a
            # new OUTPUT (data-driven code where control flow stays flat but
            # behavior varies) — robust across both styles.
            if (cov - covered) or (outcome not in seen_outcomes):
                covered |= cov
                seen_outcomes.add(outcome)
                if add(mutated, "fuzz"):
                    n_fuzz += 1

        for values, origin, blob in corpus:
            try:
                rep = repr(tuple(values))
            except Exception:
                rep = "<unreprable>"
            if len(rep) > 120:
                rep = rep[:117] + "..."
            out["inputs"].append({"origin": origin,
                                  "b64": base64.b64encode(blob).decode("ascii"),
                                  "repr": rep})
        out["coverage"] = {"seed": seed_edges, "total": len(covered),
                           "execs": execs, "corpus": len(corpus)}
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
