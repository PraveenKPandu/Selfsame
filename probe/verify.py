"""One command: verify a refactor didn't change behavior, using the repo's own
tests for inputs.

  capture real call args from the test suite  ->  replay both versions  ->  report

Run from the repo root:
  python3 -m probe.verify --base <ref> --modules <pkg> -- pytest -q
  python3 -m probe.verify --base main --head HEAD --modules mypkg -- python -m unittest

--head defaults to WORKTREE (your current checkout). Exit codes: 0 = no
divergence, 1 = at least one divergence, 2 = usage error, 3 = --strict and some
functions could not be verified (error/timeout). Drop it in CI.

Because the probe RUNS the target's code and tests, it must use a Python the
target supports. Pass --python /path/to/pythonX.Y to run the test command and the
replay workers under that interpreter; the repo's requires-python is checked and
a mismatch is reported loudly instead of silently capturing nothing.

Tuning env vars:
  PROBE_WORKER_TIMEOUT   per-function replay timeout, seconds (default 45). Under
                         heavy load functions can time out -> reported `timeout`
                         (never a false divergence); raise this or reduce load.
  PROBE_CAPTURE_TIMEOUT  wall-clock budget for the capture command (default 300).
"""

import argparse
import configparser
import os
import re
import subprocess
import sys

from .capture import capture_command
from .extract import changed_keys
from .replay import _add_worktree, _rm_worktree, replay_paths


def _requires_python(repo: str):
    """Best-effort read of the target's minimum Python (e.g. '3.10'), or None."""
    pp = os.path.join(repo, "pyproject.toml")
    if os.path.isfile(pp):
        with open(pp) as f:
            m = re.search(r'requires-python\s*=\s*["\']([^"\']+)["\']', f.read())
        if m:
            mm = re.search(r'(\d+)\.(\d+)', m.group(1))
            if mm:
                return (int(mm.group(1)), int(mm.group(2)))
    sc = os.path.join(repo, "setup.cfg")
    if os.path.isfile(sc):
        cp = configparser.ConfigParser()
        try:
            cp.read(sc)
            val = cp.get("options", "python_requires", fallback="")
            mm = re.search(r'(\d+)\.(\d+)', val)
            if mm:
                return (int(mm.group(1)), int(mm.group(2)))
        except Exception:
            pass
    return None


def _key_in_modules(key: str, modules) -> bool:
    """True if a 'module::qualname' key belongs to one of the target modules."""
    mod = key.split("::", 1)[0]
    return any(mod == m or mod.startswith(m + ".") for m in modules)


def _py_version(python_exe: str):
    try:
        out = subprocess.check_output(
            [python_exe, "-c", "import sys;print('%d %d'%sys.version_info[:2])"],
            text=True)
        a, b = out.split()
        return (int(a), int(b))
    except Exception:
        return None


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
    ap.add_argument("--python", default=None,
                    help="interpreter to run tests + replay workers under")
    ap.add_argument("--changed-only", action="store_true",
                    help="only check functions that changed between base and head")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero (3) if any function could not be verified "
                         "(error/timeout), not just on divergence")
    ap.add_argument("--no-minimize", action="store_true",
                    help="don't shrink divergence witnesses to a minimal input")
    ns = ap.parse_args(raw[:split])

    repo = os.path.abspath(ns.repo)
    modules = [m for m in ns.modules.split(",") if m]
    python_exe = ns.python or sys.executable

    # If --python is given and the command starts with python/python3, use it.
    if ns.python and command[0] in ("python", "python3"):
        command[0] = python_exe

    # Version sanity check against the target's declared requirement.
    need = _requires_python(repo)
    have = _py_version(python_exe)
    if need and have and have < need:
        print("WARNING: %s declares requires-python >= %d.%d but the probe is "
              "using Python %d.%d (%s)." % (os.path.basename(repo), need[0],
              need[1], have[0], have[1], python_exe))
        print("         Tests may fail to import and capture nothing. "
              "Pass --python /path/to/python%d.%d" % (need[0], need[1]))

    print("Capturing inputs from: %s" % " ".join(command))
    records = capture_command(modules, command, cwd=repo)
    if not records:
        msg = "No inputs captured — do the tests import and call %s?" % ns.modules
        if need and have and have < need:
            msg += " (likely the Python-version mismatch above)"
        print(msg)
        return 2
    total = sum(len(v) for v in records.values())
    print("captured %d arg-sets across %d functions" % (total, len(records)))

    # Blind-spot report: which functions changed between base and head but have
    # NO captured inputs — i.e. no test exercises them, so they cannot be
    # verified. This keeps "all equivalent" honest about what was NOT checked.
    changed = changed_keys(repo, ns.base, ns.head)
    changed_here = {k for k in changed if _key_in_modules(k, modules)}
    uncovered = sorted(changed_here - set(records))

    if ns.changed_only:
        records = {k: v for k, v in records.items() if k in changed}
        print("diff %s..%s touches %d changed function(s) in %s; %d have "
              "captured inputs" % (ns.base, ns.head, len(changed_here),
                                   ns.modules, len(records)))

    if changed_here:
        covered = len(changed_here) - len(uncovered)
        print("\nChanged functions in %s: %d  (with test inputs: %d, WITHOUT: %d)"
              % (ns.modules, len(changed_here), covered, len(uncovered)))
        if uncovered:
            print("  unverified — no test exercises these:")
            for k in uncovered[:25]:
                print("    - %s" % k)
            if len(uncovered) > 25:
                print("    ... and %d more" % (len(uncovered) - 25))

    if ns.changed_only and not records:
        print("\nNo changed-and-tested functions to check — nothing to verify.")
        return 0
    print("")

    base_path = _add_worktree(repo, ns.base, modules)
    head_path = (repo if ns.head == "WORKTREE"
                 else _add_worktree(repo, ns.head, modules))
    try:
        label = "%s..%s" % (ns.base, ns.head)
        return replay_paths(base_path, head_path, records, label, python_exe,
                            strict=ns.strict, minimize=not ns.no_minimize)
    finally:
        _rm_worktree(repo, base_path)
        if head_path != repo:
            _rm_worktree(repo, head_path)


if __name__ == "__main__":
    raise SystemExit(main())
