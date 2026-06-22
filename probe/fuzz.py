"""Capture-seeded differential fuzzing (prototype).

Capture-replay alone is bounded to the inputs your tests already exercise. This
takes those real captured inputs as *seeds*, mutates around them (probe._mutate)
to reach inputs the tests never covered, replays both versions on the result, and
reports divergences — partitioned into:
  - "seed"      : differs at an input your tests already use (rerunning the suite
                  would likely catch it too)
  - "FUZZ-ONLY" : the seeds all agreed, but a *mutated* input made the versions
                  diverge — a behavior difference beyond your test coverage

Soundness is preserved: an input where either version is nondeterministic / does
uncontrolled I/O / spawns threads / returns something opaque is skipped, never
reported as a divergence. A reported divergence is a real behavior difference at
that input (whether it's a *bug* is for a human to judge — the input may be
out-of-contract).

Run:  python3 -m probe.fuzz <repo> <base> <head> <capture.pkl> [budget]
"""

import base64
import json
import os
import pickle
import subprocess
import sys

from .replay import _add_worktree, _repo_root, _rm_worktree, _same, _split_key, _unsound, _worker

_FUZZ_TIMEOUT = 90


def _fuzz_inputs(worktree, module, qualname, seed_blobs, budget, python_exe=None):
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONPATH"] = _repo_root() + os.pathsep + env.get("PYTHONPATH", "")
    job = json.dumps({
        "worktree": worktree, "module_name": module, "qualname": qualname,
        "seeds_b64": [base64.b64encode(b).decode("ascii") for b in seed_blobs],
        "budget": budget,
    })
    try:
        proc = subprocess.run([python_exe or sys.executable, "-m", "probe._fuzz_worker"],
                              input=job, capture_output=True, text=True,
                              timeout=_FUZZ_TIMEOUT, env=env, cwd=_repo_root())
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return json.loads(proc.stdout)


def fuzz_paths(base_path, head_path, records, label, budget=200, python_exe=None):
    print("Capture-seeded differential fuzz: %s  (%d functions)" % (label, len(records)))
    print("=" * 74)
    seed_div_total = fuzz_div_total = skipped_total = checked = funcs_fuzz_only = 0
    rows = []

    for key in sorted(records):
        module, qual = _split_key(key)
        fi = _fuzz_inputs(head_path, module, qual, records[key], budget, python_exe)
        if not fi or fi.get("error") or not fi.get("inputs"):
            continue
        inputs = fi["inputs"]
        blobs = [base64.b64decode(i["b64"]) for i in inputs]
        b = _worker(base_path, module, qual, blobs, python_exe)
        h = _worker(head_path, module, qual, blobs, python_exe)
        if not b.get("loaded") or not h.get("loaded"):
            continue
        bobs, hobs = b["obs"], h["obs"]
        if len(bobs) != len(inputs) or len(hobs) != len(inputs):
            continue

        checked += 1
        seed_div = fuzz_div = 0
        witness = None
        n_fuzz = sum(1 for i in inputs if i["origin"] == "fuzz")
        for idx, inp in enumerate(inputs):
            ob, oh = bobs[idx], hobs[idx]
            if _unsound([ob]) or _unsound([oh]):
                skipped_total += 1
                continue
            if not _same(ob, oh):
                if inp["origin"] == "seed":
                    seed_div += 1
                else:
                    fuzz_div += 1
                    if witness is None:
                        witness = inp["repr"]
        seed_div_total += seed_div
        fuzz_div_total += fuzz_div
        if seed_div == 0 and fuzz_div > 0:
            funcs_fuzz_only += 1
        if seed_div or fuzz_div:
            rows.append((qual, n_fuzz, seed_div, fuzz_div, witness))

    for qual, n_fuzz, sd, fd, witness in rows:
        tag = "FUZZ-ONLY" if (sd == 0 and fd) else ("seed+fuzz" if sd and fd else "seed")
        line = "  %-28s fuzz_inputs=%-4d seed_div=%d fuzz_div=%d  [%s]" % (
            qual, n_fuzz, sd, fd, tag)
        if fd and witness:
            line += "\n      first fuzz divergence @ %s" % witness
        print(line)

    print("\n" + "-" * 74)
    print("Functions fuzzed                       : %d" % checked)
    print("Divergences at TEST inputs (seeds)     : %d" % seed_div_total)
    print("Divergences found ONLY by fuzzing      : %d  (in %d functions whose "
          "seeds all agreed)" % (fuzz_div_total, funcs_fuzz_only))
    print("Inputs skipped (unsound: io/threads/nondet/opaque): %d" % skipped_total)
    return 1 if (seed_div_total or fuzz_div_total) else 0


def fuzz(repo, base, head, capture_path, budget=200, python_exe=None):
    with open(capture_path, "rb") as f:
        cap = pickle.load(f)
    records = cap["records"]
    base_wt = _add_worktree(repo, base)
    head_wt = repo if head == "WORKTREE" else _add_worktree(repo, head)
    try:
        return fuzz_paths(base_wt, head_wt, records, "%s..%s" % (base, head),
                          budget, python_exe)
    finally:
        _rm_worktree(repo, base_wt)
        if head_wt != repo:
            _rm_worktree(repo, head_wt)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 4:
        print(__doc__)
        return 2
    repo, base, head, cap = argv[:4]
    budget = int(argv[4]) if len(argv) > 4 else 200
    return fuzz(repo, base, head, cap, budget)


if __name__ == "__main__":
    raise SystemExit(main())
