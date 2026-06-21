"""Measure sound auto-verify rate on a REAL repo's REAL commits.

For a tracked file, walk its commit history, and for every consecutive commit
pair where a top-level function's *body actually changed*, run the isolated
probe and record the verdict. This is the decisive go/no-go number: of the real
changes the probe can even see (same-name, same-signature top-level functions),
what fraction does it reach a trustworthy verdict on vs. honestly refuse.

Run:  python3 experiments/real_repo.py <repo_path> <file_path_in_repo> [max_pairs]
"""

import ast
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from probe.check import _check_one, _repo_root  # noqa: E402
from probe.extract import pair_functions  # noqa: E402


def git(repo, *args):
    return subprocess.check_output(["git", "-C", repo] + list(args), text=True)


def func_source(source, name):
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            seg = ast.get_source_segment(source, node)
            return seg if seg is not None else ast.dump(node)
    return None


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    repo, path = sys.argv[1], sys.argv[2]
    max_pairs = int(sys.argv[3]) if len(sys.argv) > 3 else 80
    probe_root = _repo_root()

    commits = git(repo, "log", "--format=%H", "--", path).split()
    print("Real-repo measurement: %s :: %s" % (os.path.basename(repo.rstrip("/")), path))
    print("file touched in %d commits; scanning up to %d pairs" % (len(commits), max_pairs))
    print("=" * 74)

    tally = {}
    changed = 0
    rows = []
    pairs = 0
    for newer, older in zip(commits, commits[1:]):
        if pairs >= max_pairs:
            break
        pairs += 1
        try:
            before = git(repo, "show", "%s:%s" % (older, path))
            after = git(repo, "show", "%s:%s" % (newer, path))
        except subprocess.CalledProcessError:
            continue
        for name in pair_functions(before, after).matched:
            if func_source(before, name) == func_source(after, name):
                continue  # body unchanged in this pair — not a real change
            changed += 1
            r = _check_one(before, after, name, probe_root)
            v = r["verdict"]
            tally[v] = tally.get(v, 0) + 1
            rows.append((newer[:8], name, v, r.get("cause") or r.get("detail") or ""))

    for sha, name, v, note in rows:
        print("  %s  %-16s %-13s %s" % (sha, name, v, note))

    verifiable = tally.get("equivalent", 0) + tally.get("divergent", 0)
    refused = tally.get("unverifiable", 0) + tally.get("unsupported", 0)
    errors = tally.get("error", 0) + tally.get("timeout", 0)

    print("\n" + "-" * 74)
    print("Real changed functions checked : %d  (across %d commit pairs)" % (changed, pairs))
    if changed:
        pct = lambda n: 100.0 * n / changed
        print("Sound auto-verify              : %d/%d = %.0f%%   (equivalent+divergent)"
              % (verifiable, changed, pct(verifiable)))
        print("  equivalent                   : %d" % tally.get("equivalent", 0))
        print("  divergent                    : %d" % tally.get("divergent", 0))
        print("Honestly refused               : %d/%d = %.0f%%"
              % (refused, changed, pct(refused)))
        print("  unsupported                  : %d" % tally.get("unsupported", 0))
        print("  unverifiable                 : %d" % tally.get("unverifiable", 0))
        print("Extraction errors              : %d/%d = %.0f%%   (load/relative-import/timeout)"
              % (errors, changed, pct(errors)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
