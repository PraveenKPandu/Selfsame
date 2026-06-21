"""Capture real call arguments by running a project's existing test command.

This is the pivot away from generating inputs: real tests already call the code
with realistic arguments, so we record those. A capture hook is injected into
every Python process the command spawns (via a generated `sitecustomize` on
PYTHONPATH), so it works with any runner — pytest, unittest, tox, or tests that
spawn their own subprocesses — not just in-process pytest. No type hints needed.

Run:
  cd /path/to/repo
  python3 -m probe.capture --modules inflection --out caps.pkl -- pytest -q
  python3 -m probe.capture --modules mypkg --out caps.pkl -- python -m unittest

Records are keyed "module::qualname" so functions and methods across modules and
classes don't collide.
"""

from __future__ import annotations

import argparse
import glob
import os
import pickle
import subprocess
import sys
import tempfile
from typing import Dict, List

_CAP_PER_FUNC = 300


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _merge(cap_dir: str) -> Dict[str, List[bytes]]:
    merged: Dict[str, List[bytes]] = {}
    seen: Dict[str, set] = {}
    for path in sorted(glob.glob(os.path.join(cap_dir, "cap-*.pkl"))):
        try:
            with open(path, "rb") as f:
                part = pickle.load(f)
        except Exception:
            continue
        for key, blobs in part.items():
            bucket = merged.setdefault(key, [])
            s = seen.setdefault(key, set())
            for b in blobs:
                if len(bucket) >= _CAP_PER_FUNC:
                    break
                h = hash(b)
                if h in s:
                    continue
                s.add(h)
                bucket.append(b)
    return merged


def capture_command(modules: List[str], command: List[str],
                    funcs: List[str] = None, cwd: str = None) -> Dict[str, List[bytes]]:
    """Run `command` with the capture hook injected; return merged records."""
    work = tempfile.mkdtemp(prefix="probe_cap_")
    cap_dir = os.path.join(work, "caps")
    os.makedirs(cap_dir, exist_ok=True)
    with open(os.path.join(work, "sitecustomize.py"), "w") as f:
        f.write("import probe._capture_hook  # installed by probe.capture\n")

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [work, _repo_root()] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env["PROBE_CAPTURE_DIR"] = cap_dir
    env["PROBE_CAPTURE_MODULES"] = ",".join(modules)
    if funcs:
        env["PROBE_CAPTURE_FUNCS"] = ",".join(funcs)

    subprocess.run(command, env=env, cwd=cwd)
    return _merge(cap_dir)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="probe.capture")
    ap.add_argument("--modules", required=True,
                    help="comma-separated module/package names to capture")
    ap.add_argument("--funcs", default=None,
                    help="optional comma-separated name/qualname allow-list")
    ap.add_argument("--out", required=True)
    # everything after `--` is the test command
    raw = list(sys.argv[1:] if argv is None else argv)
    if "--" not in raw:
        ap.error("provide the test command after `--`, e.g. -- pytest -q")
    split = raw.index("--")
    ns = ap.parse_args(raw[:split])
    command = raw[split + 1:]
    if not command:
        ap.error("empty test command after `--`")

    modules = [m for m in ns.modules.split(",") if m]
    funcs = [f for f in ns.funcs.split(",")] if ns.funcs else None
    records = capture_command(modules, command, funcs)

    with open(ns.out, "wb") as f:
        pickle.dump({"records": records}, f)
    total = sum(len(v) for v in records.values())
    print("\ncaptured %d distinct arg-sets across %d functions -> %s"
          % (total, len(records), ns.out))
    for key in sorted(records):
        print("  %-40s %d" % (key, len(records[key])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
