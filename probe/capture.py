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
import time
from typing import Dict, List

_CAP_PER_FUNC = 300
# Wall-clock ceiling on the capture command. Hypothesis / pytest-benchmark suites
# generate enormous call volumes that crawl under the capture hook (a real repo
# hung for ~40min); this bounds it and proceeds with whatever was captured.
# 0 disables the budget.
_CAPTURE_TIMEOUT = int(os.environ.get("PROBE_CAPTURE_TIMEOUT", "300"))


def _maybe_disable_benchmark(command: List[str]):
    """If this is a pytest run, append `-p no:benchmark` so pytest-benchmark's
    timing loops don't call the target thousands of times under the hook. Safe
    no-op when the plugin isn't installed. Opt out with PROBE_KEEP_BENCHMARK=1."""
    if os.environ.get("PROBE_KEEP_BENCHMARK"):
        return command, False
    joined = " ".join(command)
    toks = [os.path.basename(c) for c in command]
    is_pytest = any(t == "pytest" or t.startswith("pytest") for t in toks) \
        or ("-m" in command and "pytest" in command)
    if not is_pytest or "no:benchmark" in joined:
        return command, False
    return command + ["-p", "no:benchmark"], True


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
                    funcs: List[str] = None, cwd: str = None,
                    cap_dir: str = None) -> Dict[str, List[bytes]]:
    """Run `command` with the capture hook injected; return merged records.

    `cap_dir`, if given, is used as PROBE_CAPTURE_DIR (its location is printed so a
    long-running process can be snapshotted on demand with `probe attach <pid>`,
    which writes cap-<pid>.pkl there). If omitted, an ephemeral temp dir is used.
    """
    work = tempfile.mkdtemp(prefix="probe_cap_")
    if cap_dir is None:
        cap_dir = os.path.join(work, "caps")
    cap_dir = os.path.abspath(cap_dir)
    os.makedirs(cap_dir, exist_ok=True)
    with open(os.path.join(work, "sitecustomize.py"), "w") as f:
        f.write("import probe._capture_hook  # installed by probe.capture\n")

    env = dict(os.environ)
    extra = [work, _repo_root()]
    if cwd:  # make the project importable during its tests (flat or src layout)
        extra.append(cwd)
        src = os.path.join(cwd, "src")
        if os.path.isdir(src):
            extra.append(src)
    env["PYTHONPATH"] = os.pathsep.join(
        extra + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env["PROBE_CAPTURE_DIR"] = cap_dir
    env["PROBE_CAPTURE_MODULES"] = ",".join(modules)
    if funcs:
        env["PROBE_CAPTURE_FUNCS"] = ",".join(funcs)

    command, skipped_bench = _maybe_disable_benchmark(command)
    if skipped_bench:
        print("probe: disabled pytest-benchmark for capture (its timing loops "
              "blow up under the hook; set PROBE_KEEP_BENCHMARK=1 to keep it)",
              file=sys.stderr)

    print("probe: capture dir = %s" % cap_dir, file=sys.stderr)
    print("probe: to snapshot a long-running process without stopping it, run "
          "`probe attach <pid> --capture-dir %s`" % cap_dir, file=sys.stderr)
    from . import _procs
    budget = _CAPTURE_TIMEOUT if _CAPTURE_TIMEOUT > 0 else None
    started = time.monotonic()
    timed_out = False
    try:
        # tracked: reaped if probe is killed; graceful SIGTERM lets the hook flush
        _procs.run(command, env=env, cwd=cwd, timeout=budget, term_grace=5)
    except subprocess.TimeoutExpired:
        timed_out = True
        print("probe: capture exceeded the %ds budget (PROBE_CAPTURE_TIMEOUT) — "
              "stopping and using inputs captured so far. Heavy suite? "
              "property-based (hypothesis) or pytest-benchmark tests generate huge "
              "call volumes; scope with --changed-only or raise the budget."
              % budget, file=sys.stderr)
    merged = _merge(cap_dir)
    elapsed = time.monotonic() - started
    capped = sum(1 for v in merged.values() if len(v) >= _CAP_PER_FUNC)
    if not timed_out and (capped >= 3 or (budget and elapsed > budget * 0.5)):
        print("probe: heavy capture (%.0fs, %d function(s) hit the input cap) — "
              "if this is a hypothesis/benchmark suite, consider --changed-only "
              "for faster, scoped runs." % (elapsed, capped), file=sys.stderr)
    return merged


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="probe.capture")
    ap.add_argument("--modules", required=True,
                    help="comma-separated module/package names to capture")
    ap.add_argument("--funcs", default=None,
                    help="optional comma-separated name/qualname allow-list")
    ap.add_argument("--capture-dir", default=None,
                    help="directory for per-process cap-<pid>.pkl dumps "
                         "(default: an ephemeral temp dir). Use a stable path for "
                         "long-running processes so `probe attach` dumps land "
                         "somewhere you know.")
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
    # Run in the current directory and make it (and its src/) importable, so a
    # flat- or src-layout package under test imports during the command.
    records = capture_command(modules, command, funcs, cwd=os.getcwd(),
                              cap_dir=ns.capture_dir)

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
