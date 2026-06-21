"""One command: verify a refactor didn't change behavior, using the repo's own
tests for inputs.

  capture real call args from the test suite  ->  replay both versions  ->  report

Run from the repo root:
  python3 -m probe.verify --base <ref> --modules <pkg> -- pytest -q
  python3 -m probe.verify --base main --head HEAD --modules mypkg -- python -m unittest

--head defaults to WORKTREE (your current, possibly uncommitted, checkout), so
the common use is "did my working-tree refactor change anything vs main?".
Exits non-zero if any divergence is caught — drop it in CI.
"""

import argparse
import os
import sys

from .capture import capture_command
from .replay import _add_worktree, _rm_worktree, replay_paths


def main(argv=None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if "--" not in raw:
        print(__doc__)
        return 2
    split = raw.index("--")
    command = raw[split + 1:]
    if not command:
        print("empty test command after `--`")
        return 2

    ap = argparse.ArgumentParser(prog="probe.verify")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--base", required=True, help="ref to compare against")
    ap.add_argument("--head", default="WORKTREE",
                    help="ref to compare (default: current working tree)")
    ap.add_argument("--modules", required=True,
                    help="comma-separated module/package names to verify")
    ns = ap.parse_args(raw[:split])

    repo = os.path.abspath(ns.repo)
    modules = [m for m in ns.modules.split(",") if m]

    print("Capturing inputs from: %s" % " ".join(command))
    records = capture_command(modules, command, cwd=repo)
    if not records:
        print("No inputs captured — do the tests import and call %s?" % ns.modules)
        return 2
    total = sum(len(v) for v in records.values())
    print("captured %d arg-sets across %d functions\n" % (total, len(records)))

    base_path = _add_worktree(repo, ns.base)
    head_path = repo if ns.head == "WORKTREE" else _add_worktree(repo, ns.head)
    try:
        label = "%s..%s" % (ns.base, ns.head)
        return replay_paths(base_path, head_path, records, label)
    finally:
        _rm_worktree(repo, base_path)
        if head_path != repo:
            _rm_worktree(repo, head_path)


if __name__ == "__main__":
    raise SystemExit(main())
