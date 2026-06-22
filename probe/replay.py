"""Replay captured arguments against two versions of a repo and report, per
function, whether behavior is preserved.

Package-aware (each version is a real `git worktree`, so relative imports work)
and input-real (arguments come from probe.capture, not generation). Each version
runs in its own subprocess; observations are compared structurally with the same
soundness rules as the rest of the engine (uncontrolled I/O / threads / opaque
returns -> refuse, don't certify).

Run:  python3 -m probe.replay <repo> <base_ref> <head_ref> <capture.pkl>
"""

import base64
import concurrent.futures
import json
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional

from . import _procs

# Replay every captured arg-set by default: capping the count silently drops the
# inputs that trigger a divergence (a missed catch), and it doesn't rescue heavy
# functions anyway (they hit the worker timeout regardless). Speed comes from
# parallelism + the per-worker timeout. Users can opt into a cap for speed.
_REPLAY_MAX_ARGS = int(os.environ.get("PROBE_REPLAY_MAX_ARGS", "100000"))
_WORKER_TIMEOUT = int(os.environ.get("PROBE_WORKER_TIMEOUT", "45"))


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git(repo, *args):
    return subprocess.check_output(["git", "-C", repo] + list(args), text=True)


def _worker(worktree, module_name, qualname, blobs, python_exe=None) -> Dict:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONPATH"] = _repo_root() + os.pathsep + env.get("PYTHONPATH", "")
    job = json.dumps({
        "worktree": worktree, "module_name": module_name,
        "qualname": qualname,
        "args_b64": [base64.b64encode(b).decode("ascii") for b in blobs],
    })
    try:
        proc = _procs.run([python_exe or sys.executable, "-m", "probe._replay_worker"],
                          input=job, capture_output=True, text=True,
                          timeout=_WORKER_TIMEOUT, env=env, cwd=_repo_root())
    except subprocess.TimeoutExpired:
        return {"loaded": False, "error": "timeout", "obs": []}
    if proc.returncode != 0 or not proc.stdout.strip():
        tail = (proc.stderr.strip().splitlines() or ["nonzero exit"])[-1]
        return {"loaded": False, "error": tail, "obs": []}
    return json.loads(proc.stdout)


def _has_opaque(node) -> bool:
    if isinstance(node, list):
        if node and node[0] == "opaque":
            return True
        return any(_has_opaque(x) for x in node)
    return False


def _unsound(obs_list) -> Optional[str]:
    for o in obs_list:
        if o.get("nondet"):
            return "nondeterministic"
        if o.get("io", 0) > 0:
            return "uncontrolled-io"
        if o.get("threads", 0) > 0:
            return "concurrency"
        if "val" in o and _has_opaque(o["val"]):
            return "opaque-return"
        if o.get("self_after") is not None and _has_opaque(o["self_after"]):
            return "opaque-state"
    return None


def _same(a: Dict, b: Dict) -> bool:
    if ("exc" in a) != ("exc" in b):
        return False
    if "exc" in a:
        if a["exc"] != b["exc"]:
            return False
    elif a.get("val") != b.get("val"):
        return False
    return a.get("self_after") == b.get("self_after")  # method mutation is behavior


def _add_worktree(repo, ref) -> str:
    wt = tempfile.mkdtemp(prefix="probe_wt_")
    _git(repo, "worktree", "add", "--detach", wt, ref)
    return wt


def _rm_worktree(repo, wt) -> None:
    try:
        _git(repo, "worktree", "remove", "--force", wt)
    except Exception:
        shutil.rmtree(wt, ignore_errors=True)


def _split_key(key: str):
    """'module::Class.method' -> ('module', 'Class.method')."""
    if "::" in key:
        mod, qual = key.split("::", 1)
        return mod, qual
    return key, key  # legacy/loose form


def _check_key(base_path, head_path, key, blobs, python_exe):
    module_name, qualname = _split_key(key)
    blobs = blobs[:_REPLAY_MAX_ARGS]
    b = _worker(base_path, module_name, qualname, blobs, python_exe)
    h = _worker(head_path, module_name, qualname, blobs, python_exe)
    verdict, note = _verdict(b, h, blobs)
    return (qualname, len(blobs), verdict, note)


def replay_paths(base_path: str, head_path: str, records: Dict[str, List[bytes]],
                 label: str, python_exe: str = None) -> int:
    """Compare two already-materialized versions (directories on disk).

    Per-function checks run in parallel (each spawns two short-lived worker
    subprocesses), and each function replays at most _REPLAY_MAX_ARGS inputs."""
    print("Replay: %s  (%d functions, real captured inputs)" % (label, len(records)))
    print("=" * 74)
    _procs.install()  # main thread: ensure worker subprocesses are reaped on kill

    keys = sorted(records)
    parallelism = min(8, (os.cpu_count() or 2))
    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallelism) as ex:
        futures = [ex.submit(_check_key, base_path, head_path, k, records[k], python_exe)
                   for k in keys]
        for fut in concurrent.futures.as_completed(futures):
            rows.append(fut.result())
    rows.sort(key=lambda r: r[0])

    tally: Dict[str, int] = {}
    for _name, _n, verdict, _note in rows:
        tally[verdict] = tally.get(verdict, 0) + 1

    for name, n, verdict, note in rows:
        print("  %-30s n=%-4d %-13s %s" % (name, n, verdict, note))

    checked = sum(1 for _n, _c, v, _t in rows
                  if v in ("equivalent", "divergent", "unverifiable"))
    verifiable = tally.get("equivalent", 0) + tally.get("divergent", 0)
    print("\n" + "-" * 74)
    print("Functions with captured inputs : %d" % len(rows))
    if checked:
        print("Sound auto-verify              : %d/%d = %.0f%%"
              % (verifiable, checked, 100.0 * verifiable / checked))
    print("  equivalent : %d   divergent : %d   unverifiable : %d   not-comparable : %d"
          % (tally.get("equivalent", 0), tally.get("divergent", 0),
             tally.get("unverifiable", 0),
             tally.get("skipped", 0) + tally.get("error", 0)))
    return 1 if tally.get("divergent", 0) else 0


def replay(repo: str, base: str, head: str, capture_path: str,
           python_exe: str = None) -> int:
    with open(capture_path, "rb") as f:
        cap = pickle.load(f)
    records: Dict[str, List[bytes]] = cap["records"]
    base_wt = _add_worktree(repo, base)
    head_wt = repo if head == "WORKTREE" else _add_worktree(repo, head)
    try:
        return replay_paths(base_wt, head_wt, records, "%s..%s" % (base, head),
                            python_exe)
    finally:
        _rm_worktree(repo, base_wt)
        if head_wt != repo:
            _rm_worktree(repo, head_wt)


def _verdict(b: Dict, h: Dict, blobs):
    if b.get("error") or h.get("error"):
        return "error", (b.get("error") or h.get("error"))
    if not b.get("loaded") or not h.get("loaded"):
        return "skipped", "not present in both versions"
    flag = _unsound(b["obs"]) or _unsound(h["obs"])
    if flag:
        return "unverifiable", flag
    if len(b["obs"]) != len(h["obs"]):
        return "error", "observation count mismatch"
    for i, (ob, oh) in enumerate(zip(b["obs"], h["obs"])):
        if not _same(ob, oh):
            try:
                arg = pickle.loads(base64.b64decode(
                    base64.b64encode(blobs[i]).decode("ascii")))
            except Exception:
                arg = "?"
            return "divergent", "@ input #%d %r" % (i, arg)
    return "equivalent", ""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 4:
        print(__doc__)
        return 2
    repo, base, head, capture_path = argv
    return replay(repo, base, head, capture_path)


if __name__ == "__main__":
    raise SystemExit(main())
