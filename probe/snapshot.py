"""Behavioral snapshots: freeze a confirmed version's behavior, then measure how
much later code deviates from it — without needing two git branches.

This is the shape that fits AI-driven development: a user accepts a build, then an
agent keeps generating features. The risk is silent regression — "a new feature,
but the existing functionality is gone." Snapshot the accepted build's behavior;
after the next change, replay the SAME captured inputs against the current code and
report how far it drifted.

  selfsame snapshot --modules mypkg -- pytest -q      # freeze accepted behavior
  # ... AI develops the next feature ...
  selfsame drift                                       # how much deviated?

`snapshot` records, per function, the captured inputs AND the canonical behavior
(return / exception / receiver-state, plus io/threads/nondeterminism flags) of the
CURRENT code. `drift` replays those stored inputs on the working tree and compares
to the frozen behavior — same sound verdicts as verify (equivalent / divergent /
interface-change / unverifiable), never a false pass.
"""

import argparse
import base64
import concurrent.futures
import json
import os
import subprocess
import sys

from .capture import capture_command
from .extract import changed_keys, function_references
from .replay import _emit_results, _split_key, _verdict, _worker

_DEFAULT_PATH = os.path.join(".selfsame", "snapshot.json")


def _in_modules(key, modules):
    mod = key.split("::", 1)[0]
    return any(mod == m or mod.startswith(m + ".") for m in modules)


def _git_rev(repo):
    try:
        return subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"],
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def record_snapshot(repo, modules, command, out_path, python_exe=None):
    """Capture inputs from the test command and freeze the current code's
    behavior on them into a JSON snapshot."""
    records = capture_command(modules, command, cwd=repo)
    if not records:
        return None
    snap = {"schema": 1, "modules": modules, "git_rev": _git_rev(repo),
            "records": {}}
    keys = sorted(records)
    parallelism = min(8, (os.cpu_count() or 2))

    def _freeze(key):
        module, qual = _split_key(key)
        out = _worker(repo, module, qual, records[key], python_exe)
        return key, out

    with concurrent.futures.ThreadPoolExecutor(max_workers=parallelism) as ex:
        for key, out in ex.map(_freeze, keys):
            snap["records"][key] = {
                "blobs": [base64.b64encode(b).decode("ascii") for b in records[key]],
                "base": out,
            }
    d = os.path.dirname(out_path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(snap, f)
    return snap


def _drift_row(repo, key, base_out, blobs, python_exe):
    module, qual = _split_key(key)
    head = _worker(repo, module, qual, blobs, python_exe)
    verdict, note, _idx, detail = _verdict(base_out, head, blobs)
    detail["key"] = key
    return (qual, len(blobs), verdict, note, detail)


def check_drift(repo, snapshot_path, python_exe=None, strict=False,
                report_dir=".selfsame", write_report=True, changed_only=False):
    """Replay a snapshot's stored inputs on the working tree and report drift."""
    with open(snapshot_path) as f:
        snap = json.load(f)
    records = snap.get("records", {})
    if not records:
        print("snapshot has no records: %s" % snapshot_path)
        return 2
    rev = snap.get("git_rev")
    modules = snap.get("modules", [])
    snap_keys = set(records)

    # Functions whose source changed since the snapshot was taken (snapshot rev
    # -> working tree). Used to scope --changed-only and to find changed code
    # that has no behavioral baseline (blind spots).
    changed = None
    if rev:
        try:
            changed = changed_keys(repo, rev, "WORKTREE")
        except Exception:
            changed = None

    if changed_only:
        if changed is None:
            print("note: --changed-only needs the snapshot's git rev; "
                  "checking all functions instead.")
        else:
            records = {k: v for k, v in records.items() if k in changed}
            print("scoped to changed functions: %d of %d snapshot function(s) "
                  "changed since %s (indirect divergences via changed callees "
                  "may be missed — run full drift to be exhaustive)"
                  % (len(records), len(snap_keys), rev[:10]))

    # changed since the snapshot but no captured baseline -> can't be verified
    uncovered = []
    if changed is not None:
        uncovered = sorted(k for k in changed
                           if k not in snap_keys and _in_modules(k, modules))

    if not records:
        print("\nNo changed-and-baselined functions to check.")
        if uncovered:
            print("(%d changed function(s) have no snapshot baseline)" % len(uncovered))
        return 0

    print("Drift vs snapshot %s%s  (%d functions)"
          % (snapshot_path, (" @ " + rev[:10]) if rev else "", len(records)))
    print("=" * 74)

    keys = sorted(records)
    parallelism = min(8, (os.cpu_count() or 2))

    def _one(key):
        blobs = [base64.b64decode(b) for b in records[key]["blobs"]]
        return _drift_row(repo, key, records[key]["base"], blobs, python_exe)

    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallelism) as ex:
        for row in ex.map(_one, keys):
            rows.append(row)
    rows.sort(key=lambda r: r[0])

    refs = function_references(repo, set(records) | set(uncovered))
    env = {"python": python_exe or sys.executable, "snapshot": snapshot_path,
           "snapshot_rev": rev, "modules": ",".join(modules)}
    return _emit_results("snapshot..WORKTREE", rows, strict=strict, refs=refs,
                         env=env, report_dir=report_dir, write_report=write_report,
                         extra=uncovered, header="Functions checked")


def record_main(argv=None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if "--" not in raw:
        print("usage: selfsame snapshot --modules PKG [--out PATH] -- pytest -q")
        return 2
    split = raw.index("--")
    command = raw[split + 1:]
    if not command:
        print("empty test command after `--`")
        return 2
    ap = argparse.ArgumentParser(prog="probe.snapshot")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--modules", required=True,
                    help="comma-separated module/package names to snapshot")
    ap.add_argument("--out", default=_DEFAULT_PATH,
                    help="snapshot file path (default .selfsame/snapshot.json)")
    ap.add_argument("--python", default=None,
                    help="interpreter to run the tests + workers under")
    ns = ap.parse_args(raw[:split])

    repo = os.path.abspath(ns.repo)
    modules = [m for m in ns.modules.split(",") if m]
    python_exe = ns.python or sys.executable
    if ns.python and command[0] in ("python", "python3"):
        command[0] = python_exe

    print("Snapshotting behavior from: %s" % " ".join(command))
    snap = record_snapshot(repo, modules, command, ns.out, python_exe)
    if not snap:
        print("No inputs captured — do the tests import and call %s?" % ns.modules)
        return 2
    n_funcs = len(snap["records"])
    n_inputs = sum(len(r["blobs"]) for r in snap["records"].values())
    print("froze %d input(s) across %d function(s) -> %s"
          % (n_inputs, n_funcs, ns.out))
    print("now develop the next feature, then run `selfsame drift` to see "
          "how much the accepted behavior deviated.")
    return 0


def drift_main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="probe.drift")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--snapshot", default=_DEFAULT_PATH,
                    help="snapshot file to compare against (default %s)" % _DEFAULT_PATH)
    ap.add_argument("--python", default=None,
                    help="interpreter to run replay workers under")
    ap.add_argument("--strict", action="store_true",
                    help="exit 3 if any function could not be verified")
    ap.add_argument("--changed-only", action="store_true",
                    help="only replay functions whose source changed since the "
                         "snapshot (faster at high change volume; may miss "
                         "indirect divergences via changed callees)")
    ap.add_argument("--report-dir", default=".selfsame")
    ap.add_argument("--no-report", action="store_true")
    ns = ap.parse_args(list(sys.argv[1:] if argv is None else argv))

    repo = os.path.abspath(ns.repo)
    if not os.path.isfile(ns.snapshot):
        print("no snapshot at %s — run `selfsame snapshot ... -- pytest -q` first"
              % ns.snapshot)
        return 2
    return check_drift(repo, ns.snapshot, python_exe=ns.python or sys.executable,
                       strict=ns.strict, report_dir=ns.report_dir,
                       write_report=not ns.no_report, changed_only=ns.changed_only)
