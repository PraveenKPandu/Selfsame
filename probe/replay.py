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


# Safe file types / locations to carry into a fresh worktree (see
# _copy_generated_sources). Deliberately narrow: source-ish files only, never
# build output or caches.
_PREP_OK_EXT = (".py", ".pyi", ".txt", ".json", ".cfg", ".ini")
_PREP_SKIP = ("/__pycache__/", ".egg-info/", "/build/", "/dist/", "/.tox/")


def _pkg_dirs(repo, modules):
    """Repo-relative directories that hold the target packages' source."""
    dirs = []
    for m in modules:
        top = str(m).split(".")[0]
        for cand in (top, os.path.join("src", top)):
            if os.path.isdir(os.path.join(repo, cand)):
                dirs.append(cand)
    return dirs


def _copy_generated_sources(repo, wt, modules):
    """Copy build-generated, git-IGNORED source files (e.g. setuptools-scm /
    hatch-vcs `_version.py`) from the live working tree into a fresh worktree, so
    a dynamically-versioned package can still import during replay.

    A plain `git worktree add` only materializes tracked files, so an ignored
    generated module is missing on the base side and every function errors with
    `ModuleNotFoundError`. Scoped to the target package dirs and safe file types;
    skips caches/build output. Returns the list of copied repo-relative paths."""
    dirs = _pkg_dirs(repo, modules)
    if not dirs:
        return []
    try:
        out = _git(repo, "ls-files", "--others", "--ignored",
                   "--exclude-standard", "--", *dirs)
    except Exception:
        return []
    copied = []
    for rel in out.splitlines():
        rel = rel.strip()
        if not rel or not rel.endswith(_PREP_OK_EXT):
            continue
        if any(s in ("/" + rel) for s in _PREP_SKIP):
            continue
        src = os.path.join(repo, rel)
        dst = os.path.join(wt, rel)
        if os.path.isfile(src) and not os.path.exists(dst):
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                copied.append(rel)
            except Exception:
                continue
    return copied


def _add_worktree(repo, ref, modules=()) -> str:
    wt = tempfile.mkdtemp(prefix="probe_wt_")
    _git(repo, "worktree", "add", "--detach", wt, ref)
    if modules:
        copied = _copy_generated_sources(repo, wt, modules)
        if copied:
            shown = ", ".join(copied[:3]) + ("..." if len(copied) > 3 else "")
            print("  prepared worktree (%s): copied %d git-ignored generated "
                  "file(s): %s" % (ref, len(copied), shown))
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


def _simpler(v):
    """Smaller candidate values of the same type, for witness minimization."""
    out = []
    if isinstance(v, str) and v:
        out += ["", v[:1], v[:len(v) // 2]]
    elif isinstance(v, (bytes, bytearray)) and v:
        out += [type(v)(), v[:len(v) // 2]]
    elif isinstance(v, (list, tuple)) and v:
        t = type(v)
        out += [t(), t(list(v)[:len(v) // 2]), t(list(v)[1:])]
    elif isinstance(v, dict) and v:
        out += [{}]
    elif isinstance(v, bool):
        pass
    elif isinstance(v, int) and v not in (0,):
        out += [0, v // 2]
    elif isinstance(v, float) and v == v and v not in (0.0,):
        out += [0.0]
    return out


def _diverges_on(base_path, head_path, module, qual, values, python_exe):
    """True iff base and head soundly disagree on a single input `values`."""
    blob = [pickle.dumps(list(values))]
    b = _worker(base_path, module, qual, blob, python_exe)
    h = _worker(head_path, module, qual, blob, python_exe)
    if not (b.get("loaded") and h.get("loaded")) or not b.get("obs") or not h.get("obs"):
        return False
    ob, oh = b["obs"][0], h["obs"][0]
    if _unsound([ob]) or _unsound([oh]):
        return False
    return not _same(ob, oh)


def _minimize(base_path, head_path, module, qual, values, python_exe, cap=30):
    """Shrink a diverging witness to a smaller still-diverging input (bounded)."""
    cur = list(values)
    evals = 0
    changed = True
    while changed and evals < cap:
        changed = False
        for i in range(len(cur)):
            for cand in _simpler(cur[i]):
                if evals >= cap:
                    break
                evals += 1
                trial = list(cur)
                trial[i] = cand
                if _diverges_on(base_path, head_path, module, qual, trial, python_exe):
                    cur = trial
                    changed = True
                    break
    return cur


def _check_key(base_path, head_path, key, blobs, python_exe, minimize=True):
    module_name, qualname = _split_key(key)
    blobs = blobs[:_REPLAY_MAX_ARGS]
    b = _worker(base_path, module_name, qualname, blobs, python_exe)
    h = _worker(head_path, module_name, qualname, blobs, python_exe)
    verdict, note, idx, detail = _verdict(b, h, blobs)
    if verdict == "divergent" and minimize and idx is not None:
        orig = _decode_blob(blobs[idx])
        if orig is not None:
            mini = _minimize(base_path, head_path, module_name, qualname, orig,
                             python_exe)
            try:
                smaller = len(pickle.dumps(mini)) < len(pickle.dumps(list(orig)))
            except Exception:
                smaller = False
            if smaller:
                note += "\n      minimized: %s" % _short(mini)
                detail["minimized"] = _short(mini)
    return (qualname, len(blobs), verdict, note, detail)


def _write_machine_reports(label, rows, tally, n_timeout, uncovered,
                           json_out, junit_out):
    summary = {
        "equivalent": tally.get("equivalent", 0),
        "divergent": tally.get("divergent", 0),
        "unverifiable": tally.get("unverifiable", 0),
        "error": tally.get("error", 0) - n_timeout,
        "timeout": n_timeout,
        "skipped": tally.get("skipped", 0),
    }
    results = [dict(function=r[0], inputs=r[1], verdict=r[2], **r[4]) for r in rows]
    if json_out:
        payload = {"label": label, "summary": summary, "results": results,
                   "unverified_changed": list(uncovered)}
        try:
            with open(json_out, "w") as f:
                json.dump(payload, f, indent=2)
        except OSError:
            pass
    if junit_out:
        _write_junit(label, rows, junit_out)


def _xml_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _write_junit(label, rows, path):
    n_fail = sum(1 for r in rows if r[2] == "divergent")
    n_err = sum(1 for r in rows if r[2] == "error")
    n_skip = sum(1 for r in rows if r[2] in ("skipped", "unverifiable"))
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<testsuite name="selfsame %s" tests="%d" failures="%d" errors="%d" '
             'skipped="%d">' % (_xml_escape(label), len(rows), n_fail, n_err, n_skip)]
    for r in rows:
        name, verdict, note = r[0], r[2], r[3]
        lines.append('  <testcase name="%s">' % _xml_escape(name))
        if verdict == "divergent":
            lines.append('    <failure message="behavior changed">%s</failure>'
                         % _xml_escape(note))
        elif verdict == "error":
            lines.append('    <error message="%s"/>' % _xml_escape(note))
        elif verdict in ("skipped", "unverifiable"):
            lines.append('    <skipped message="%s"/>' % _xml_escape(note))
        lines.append('  </testcase>')
    lines.append('</testsuite>')
    try:
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass


def replay_paths(base_path: str, head_path: str, records: Dict[str, List[bytes]],
                 label: str, python_exe: str = None, strict: bool = False,
                 minimize: bool = True, json_out: str = None,
                 junit_out: str = None, extra=None) -> int:
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
        futures = [ex.submit(_check_key, base_path, head_path, k, records[k],
                             python_exe, minimize)
                   for k in keys]
        for fut in concurrent.futures.as_completed(futures):
            rows.append(fut.result())
    rows.sort(key=lambda r: r[0])

    tally: Dict[str, int] = {}
    for r in rows:
        tally[r[2]] = tally.get(r[2], 0) + 1

    # A timeout is an error subtype; track it separately so it never reads as a
    # divergence (the two looked identical before).
    n_timeout = sum(1 for r in rows if r[2] == "error" and r[3] == "timeout")
    n_error = tally.get("error", 0) - n_timeout
    n_skipped = tally.get("skipped", 0)
    n_div = tally.get("divergent", 0)

    if json_out or junit_out:
        _write_machine_reports(label, rows, tally, n_timeout, extra or [],
                               json_out, junit_out)

    for name, n, verdict, note in (r[:4] for r in rows):
        mark = "X" if verdict == "divergent" else ("!" if verdict == "error" else " ")
        print("%s %-30s n=%-4d %-13s %s" % (mark, name, n, verdict, note))

    gen_err = sum(1 for r in rows
                  if r[2] == "error" and "No module named" in (r[3] or ""))
    if gen_err:
        print("\nNote: %d function(s) errored with a missing module. A version "
              "ref's worktree may lack a build-generated file that isn't in git "
              "(e.g. setuptools-scm/hatch-vcs _version.py). probe auto-copies "
              "git-ignored files under the package dir; if this persists, "
              "generate/build it in your working tree first." % gen_err)

    checked = sum(1 for r in rows
                  if r[2] in ("equivalent", "divergent", "unverifiable"))
    verifiable = tally.get("equivalent", 0) + n_div
    print("\n" + "-" * 74)
    print("Functions with captured inputs : %d" % len(rows))
    if checked:
        print("Sound auto-verify              : %d/%d = %.0f%%"
              % (verifiable, checked, 100.0 * verifiable / checked))
    print("  verified -> equivalent : %d   divergent : %d   unverifiable : %d"
          % (tally.get("equivalent", 0), n_div, tally.get("unverifiable", 0)))
    print("  not verified -> skipped : %d   error : %d   timeout : %d"
          % (n_skipped, n_error, n_timeout))
    if n_div:
        print("  ** %d DIVERGENCE(S): behavior changed at a tested input **" % n_div)
    if n_timeout:
        print("  note: %d hit the %ds worker timeout (PROBE_WORKER_TIMEOUT) — "
              "raise it or reduce load; a timeout is NOT a divergence."
              % (n_timeout, _WORKER_TIMEOUT))

    code = _exit_code(rows, strict)
    if code == 3:
        print("  strict: %d function(s) could not be verified -> failing (exit 3)."
              % (n_error + n_timeout))
    return code


def _exit_code(rows, strict) -> int:
    """Map verdict rows to a process exit code: 1 = divergence (always),
    3 = --strict and some function was unverifiable (error/timeout), 0 = clean.
    `skipped` (absent in a version) is intentional, not a failure."""
    div = any(r[2] == "divergent" for r in rows)
    incomplete = any(r[2] == "error" for r in rows)
    if div:
        return 1
    if strict and incomplete:
        return 3
    return 0


def replay(repo: str, base: str, head: str, capture_path: str,
           python_exe: str = None) -> int:
    with open(capture_path, "rb") as f:
        cap = pickle.load(f)
    records: Dict[str, List[bytes]] = cap["records"]
    modules = sorted({_split_key(k)[0] for k in records})
    base_wt = _add_worktree(repo, base, modules)
    head_wt = repo if head == "WORKTREE" else _add_worktree(repo, head, modules)
    try:
        return replay_paths(base_wt, head_wt, records, "%s..%s" % (base, head),
                            python_exe)
    finally:
        _rm_worktree(repo, base_wt)
        if head_wt != repo:
            _rm_worktree(repo, head_wt)


def _render_canon(c, _d=0):
    """Render a canonical observation form (canonical.py) back into a short,
    human-readable string for divergence reports."""
    try:
        if not isinstance(c, list) or not c:
            return json.dumps(c)
        tag = c[0]
        if tag == "none":
            return "None"
        if tag in ("bool", "int"):
            return repr(c[1])
        if tag == "float":
            return "nan" if c[1] == "nan" else repr(c[1])
        if tag == "str":
            return repr(c[1])
        if tag == "bytes":
            return repr(bytes(c[1]))
        if tag in ("list", "tuple", "iter", "set"):
            items = c[1]
            shown = ", ".join(_render_canon(x, _d + 1) for x in items[:8])
            if len(items) > 8:
                shown += ", ..."
            wrap = {"list": "[%s]", "tuple": "(%s)", "set": "{%s}",
                    "iter": "iter[%s]"}[tag]
            return wrap % shown
        if tag == "dict":
            pairs = ", ".join("%s: %s" % (_render_canon(k, _d + 1),
                                          _render_canon(v, _d + 1))
                              for k, v in c[1][:8])
            return "{%s}" % pairs
        if tag in ("callable", "class"):
            return "<%s %s>" % (tag, c[-1])
        if tag == "range":
            return "range(%r, %r, %r)" % (c[1], c[2], c[3])
        if tag == "pub-obj":
            inner = c[2][1][1] if len(c) > 2 and len(c[2]) > 1 else []
            shown = ", ".join(_render_canon(x, _d + 1) for x in inner[:8])
            return "%s(%s)" % (c[1], shown)
        if tag == "obj":
            return "%s(...)" % c[1]
        if tag == "opaque":
            return "<opaque %s>" % (c[1] if len(c) > 1 else "")
        if tag == "maxdepth":
            return "<...>"
        return json.dumps(c)
    except Exception:
        return json.dumps(c) if isinstance(c, (list, dict, str, int, float)) else "?"


def _render_obs(o):
    if "exc" in o:
        return "raises %s" % o["exc"]
    if "val" in o:
        return _render_canon(o["val"])
    return "?"


def _decode_blob(blob):
    try:
        return pickle.loads(blob)
    except Exception:
        return None


def _short(values, limit=120):
    try:
        r = repr(tuple(values)) if isinstance(values, (list, tuple)) else repr(values)
    except Exception:
        return "<unreprable>"
    return r if len(r) <= limit else r[:limit - 3] + "..."


def _verdict(b: Dict, h: Dict, blobs):
    """Return (verdict, note, div_idx, detail). div_idx is the diverging input
    index for 'divergent' (so the caller can minimize), else None. detail is a
    structured dict for machine-readable output."""
    if b.get("error") or h.get("error"):
        msg = b.get("error") or h.get("error")
        return "error", msg, None, {"error": msg}
    if not b.get("loaded") or not h.get("loaded"):
        return "skipped", "not present in both versions", None, {}
    flag = _unsound(b["obs"]) or _unsound(h["obs"])
    if flag:
        return "unverifiable", flag, None, {"reason": flag}
    if len(b["obs"]) != len(h["obs"]):
        return "error", "observation count mismatch", None, \
            {"error": "observation count mismatch"}
    for i, (ob, oh) in enumerate(zip(b["obs"], h["obs"])):
        if not _same(ob, oh):
            arg = _decode_blob(blobs[i])
            inp, base_s, head_s = _short(arg), _render_obs(ob), _render_obs(oh)
            note = ("@ input #%d\n      input : %s\n      base  : %s"
                    "\n      head  : %s" % (i, inp, base_s, head_s))
            detail = {"input_index": i, "input": inp, "base": base_s,
                      "head": head_s}
            # method that returns the same value but mutates self differently
            if ob.get("val") == oh.get("val") and ob.get("exc") == oh.get("exc") \
                    and ob.get("self_after") != oh.get("self_after"):
                note += "\n      (receiver state differs after the call)"
                detail["receiver_state_differs"] = True
            return "divergent", note, i, detail
    return "equivalent", "", None, {}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 4:
        print(__doc__)
        return 2
    repo, base, head, capture_path = argv
    return replay(repo, base, head, capture_path)


if __name__ == "__main__":
    raise SystemExit(main())
