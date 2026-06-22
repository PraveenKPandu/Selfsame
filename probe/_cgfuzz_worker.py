"""Coverage-guided exploration worker (AFL-style feedback loop).

Runs in the head worktree. Starting from captured seeds, it repeatedly: pick a
corpus input (energy-weighted — fresh/smaller inputs preferred), havoc-mutate it
(probe._mutate.mutate_one), run the function while
tracing which branch EDGES (prev_line -> cur_line) of the target module execute
and how many times (AFL hit-count bucketing), and — if the run hit a *new* edge
or hit-count bucket — keep the mutated input in the corpus. Edge coverage drills
through nested branches that blind one-shot mutation can't reach; bucketing
retains loop-depth-diverse inputs. Deterministic (seeded RNG).

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


def _bucket(n):
    """AFL hit-count buckets: 1, 2, 3, 4-7, 8-15, 16-31, 32-127, 128+.
    Coverage key is (edge, bucket(count)) so taking a loop more times counts as
    new coverage — retains loop-depth-diverse inputs."""
    if n <= 3:
        return n
    if n <= 7:
        return 4
    if n <= 15:
        return 8
    if n <= 31:
        return 16
    if n <= 127:
        return 32
    return 128


def main() -> int:
    job = json.load(sys.stdin)
    out = {"error": None, "inputs": [], "coverage": {}}
    try:
        wt = job["worktree"]
        for p in (os.path.join(wt, "src"), wt):
            if os.path.isdir(p):
                sys.path.insert(0, p)
        import importlib

        from probe._mutate import alphabet_from, mutate_one, tokens_from_source
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
        tokens = {}
        try:
            if target_file and os.path.isfile(target_file):
                with open(target_file, encoding="utf-8") as f:
                    tokens = tokens_from_source(f.read())
        except Exception:
            tokens = {}
        budget = int(job.get("budget", 2000))
        cap = int(job.get("cap", 200))
        rng = random.Random(0)

        covered = set()
        seen_outcomes = set()   # distinct head outputs/exceptions seen
        corpus = []             # (values, origin, blob)
        energy = []             # times each corpus entry has been chosen (parallel)
        seen = set()

        def trace_run(values):
            hits = {}       # edge (prev_line, cur_line) -> times fired this run
            last = [None]   # previous line in the target file

            def gtr(frame, event, arg):
                if event == "call" and frame.f_code.co_filename == target_file:
                    return ltr
                return None

            def ltr(frame, event, arg):
                if event == "line":
                    # branch-EDGE coverage with AFL hit-count bucketing: count how
                    # many times each (prev_line -> cur_line) edge fires; the
                    # bucketed count joins the coverage key below.
                    edge = (last[0], frame.f_lineno)
                    hits[edge] = hits.get(edge, 0) + 1
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
            cov = {(edge, _bucket(c)) for edge, c in hits.items()}
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
            energy.append(0)
            return True

        def pick():
            # Energy-weighted corpus scheduling: favor inputs chosen FEWER times
            # (fresh finds get drilled before over-explored seeds) and SMALLER
            # inputs (cheaper to run, easier to reason about). AFL-style.
            weights = [1.0 / (1.0 + energy[i]) / (1.0 + len(corpus[i][2]) / 128.0)
                       for i in range(len(corpus))]
            idx = rng.choices(range(len(corpus)), weights=weights, k=1)[0]
            energy[idx] += 1
            return corpus[idx][0]

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
            base_values = pick()
            # a second energy-weighted parent enables crossover/splice
            partner = pick() if len(corpus) > 1 else None
            mutated = mutate_one(base_values, rng, alphabet, tokens, partner)
            cov, outcome = trace_run(mutated)
            # Keep an input that reaches a new EDGE/bucket (branchy or loopy code)
            # OR produces a new OUTPUT (data-driven code where control flow stays
            # flat but behavior varies) — robust across both styles.
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
