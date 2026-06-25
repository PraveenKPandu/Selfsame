"""Assumption adjudicator (experimental) — prove whether a NOMINATED assumption
in your code is load-bearing.

It is a judge, not a detective: you (or a tool) nominate `(target, boundary)`
candidates; it holds the code fixed, violates the assumed contract at the
boundary, re-runs on the target's captured inputs, and reports — soundly —
load-bearing / not-load-bearing / unverifiable, with a minimized witness.

  selfsame adjudicate --assume target=pkg::format_invoice,boundary=pkg::fx_rate -- pytest -q
  selfsame adjudicate --assumptions .selfsame/assumptions.toml --snapshot snap.json

Advisory by default (exit 0); pass --fail-on-load-bearing to gate CI. See
docs/adjudicator.md.
"""

import argparse
import base64
import json
import os
import sys

from . import _procs
from .capture import capture_command
from .extract import function_references
from .replay import _WORKER_TIMEOUT, _repo_root, _split_key

_DEFAULT_VIOLATIONS = ["none", "raises", "wrong-type", "zero", "negative"]
_DEFAULT_REPORT = os.path.join(".selfsame", "assumptions.json")


def _parse_assume(spec):
    """'target=K,boundary=K[,violations=none|raises]' -> dict, or None if invalid."""
    fields = {}
    for part in spec.split(","):
        if "=" not in part:
            return None
        k, v = part.split("=", 1)
        fields[k.strip()] = v.strip()
    if "target" not in fields or "boundary" not in fields:
        return None
    cand = {"target": fields["target"], "boundary": fields["boundary"]}
    if fields.get("violations"):
        cand["violations"] = [v for v in fields["violations"].split("|") if v]
    return cand


def _load_assumptions_file(path):
    try:
        import tomllib
    except ModuleNotFoundError:
        print("--assumptions needs Python 3.11+ (tomllib); use --assume instead")
        return None
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        print("could not read %s: %s" % (path, e))
        return None
    out = []
    for c in data.get("assume", []):
        if c.get("target") and c.get("boundary"):
            out.append(c)
    return out


def _run_candidate(repo, target, boundary, blobs, violations, python_exe):
    tmod, tqual = _split_key(target)
    bmod, bname = _split_key(boundary)
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONPATH"] = _repo_root() + os.pathsep + env.get("PYTHONPATH", "")
    job = json.dumps({
        "worktree": repo, "module_name": tmod, "qualname": tqual,
        "boundary_module": bmod, "boundary_name": bname,
        "violations": violations,
        "args_b64": [base64.b64encode(b).decode("ascii") for b in blobs],
    })
    try:
        proc = _procs.run([python_exe, "-m", "probe._adjudicate_worker"],
                          input=job, capture_output=True, text=True,
                          timeout=_WORKER_TIMEOUT, env=env, cwd=_repo_root())
    except Exception:
        return {"loaded": False, "error": "timeout"}
    if proc.returncode != 0 or not proc.stdout.strip():
        tail = (proc.stderr.strip().splitlines() or ["nonzero exit"])[-1]
        return {"loaded": False, "error": tail}
    try:
        return json.loads(proc.stdout)
    except Exception:
        return {"loaded": False, "error": "bad worker output"}


def _candidate_verdict(out):
    """Aggregate a worker result into a candidate-level verdict + violations."""
    if out.get("error"):
        return "unverifiable", out["error"], []
    vios = out.get("violations", [])
    load = [v for v in vios if v.get("result") == "load-bearing"]
    if load:
        return "load-bearing", "", vios
    if vios and all(v.get("result") == "unverifiable" for v in vios):
        return "unverifiable", vios[0].get("reason", "unverifiable"), vios
    note = "" if out.get("boundary_invoked", True) else "boundary not invoked"
    return "not-load-bearing", note, vios


def _baseline_records(ns, repo, modules, command):
    """Return {target_key: [blob bytes]} from a snapshot or a fresh capture."""
    if ns.snapshot:
        try:
            with open(ns.snapshot) as f:
                snap = json.load(f)
        except OSError as e:
            print("could not read snapshot %s: %s" % (ns.snapshot, e))
            return None
        return {k: [base64.b64decode(b) for b in rec.get("blobs", [])]
                for k, rec in snap.get("records", {}).items()}
    if command:
        print("Capturing baseline inputs from: %s" % " ".join(command))
        return capture_command(modules, command, cwd=repo)
    print("provide a baseline: a test command after `--`, or --snapshot PATH")
    return None


def _write_report(report, report_dir):
    if not report_dir:
        return None
    try:
        os.makedirs(report_dir, exist_ok=True)
        jp = os.path.join(report_dir, "assumptions.json")
        with open(jp, "w") as f:
            json.dump(report, f, indent=2)
        with open(os.path.join(report_dir, "assumptions.md"), "w") as f:
            f.write(_render_md(report))
        return jp
    except OSError:
        return None


def _render_md(report):
    s = report["summary"]
    out = ["# Selfsame — assumption blindspots", "",
           "Load-bearing: **%d** · not-load-bearing: %d · unverifiable: %d"
           % (s["load_bearing"], s["not_load_bearing"], s["unverifiable"]), ""]
    lb = [a for a in report["assumptions"] if a["verdict"] == "load-bearing"]
    if lb:
        out += ["## Load-bearing assumptions (behavior depends on these)", ""]
        for a in lb:
            loc = (" — `%s:%s`" % (a["file"], a["line"])) if a.get("file") else ""
            out.append("### `%s` assumes `%s`%s" % (a["target"], a["boundary"], loc))
            for v in a["violations"]:
                if v.get("result") == "load-bearing":
                    out.append("- if it %s → base `%s` vs `%s`  (witness `%s`)"
                               % (v["violation"], v.get("base", "?"),
                                  v.get("perturbed", "?"), v.get("witness", "?")))
            out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    command = []
    if "--" in raw:
        i = raw.index("--")
        command = raw[i + 1:]
        raw = raw[:i]
    ap = argparse.ArgumentParser(prog="probe.adjudicate")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--assume", action="append", default=[],
                    help="target=KEY,boundary=KEY[,violations=none|raises|...]")
    ap.add_argument("--assumptions", default=None,
                    help="TOML file with [[assume]] candidates (Python 3.11+)")
    ap.add_argument("--snapshot", default=None,
                    help="baseline inputs from a snapshot instead of a test run")
    ap.add_argument("--python", default=None)
    ap.add_argument("--fail-on-load-bearing", action="store_true",
                    help="exit non-zero if any assumption is load-bearing")
    ap.add_argument("--report-dir", default=".selfsame")
    ap.add_argument("--no-report", action="store_true")
    ns = ap.parse_args(raw)

    repo = os.path.abspath(ns.repo)
    python_exe = ns.python or sys.executable
    if ns.python and command and command[0] in ("python", "python3"):
        command[0] = python_exe

    candidates = []
    for spec in ns.assume:
        c = _parse_assume(spec)
        if not c:
            print("bad --assume %r (need target=...,boundary=...)" % spec)
            return 2
        candidates.append(c)
    if ns.assumptions:
        fromfile = _load_assumptions_file(ns.assumptions)
        if fromfile is None:
            return 2
        candidates.extend(fromfile)
    if not candidates:
        print("no candidates — pass --assume or --assumptions")
        return 2

    modules = sorted({_split_key(c["target"])[0] for c in candidates})
    records = _baseline_records(ns, repo, modules, command)
    if records is None:
        return 2

    _procs.install()
    refs = function_references(repo, {c["target"] for c in candidates})
    print("Adjudicating %d assumption candidate(s)" % len(candidates))
    print("=" * 74)

    assumptions = []
    tally = {"load-bearing": 0, "not-load-bearing": 0, "unverifiable": 0}
    for c in candidates:
        target, boundary = c["target"], c["boundary"]
        violations = c.get("violations") or _DEFAULT_VIOLATIONS
        blobs = records.get(target)
        if not blobs:
            verdict, note, vios = "unverifiable", "no captured inputs for target", []
        else:
            out = _run_candidate(repo, target, boundary, blobs, violations, python_exe)
            verdict, note, vios = _candidate_verdict(out)
        tally[verdict] = tally.get(verdict, 0) + 1
        mark = {"load-bearing": "!", "unverifiable": "?"}.get(verdict, " ")
        line = "%s %-40s assumes %-28s %s" % (mark, target, boundary, verdict)
        if note:
            line += "  (%s)" % note
        print(line)
        for v in vios:
            if v.get("result") == "load-bearing":
                print("    %-10s base %s -> %s   @ %s"
                      % (v["violation"], v.get("base"), v.get("perturbed"),
                         v.get("witness")))
        entry = {"target": target, "boundary": boundary, "verdict": verdict,
                 "violations": vios}
        if note:
            entry["note"] = note
        if refs.get(target):
            entry.update(refs[target])
        assumptions.append(entry)

    summary = {"load_bearing": tally["load-bearing"],
               "not_load_bearing": tally["not-load-bearing"],
               "unverifiable": tally["unverifiable"],
               "candidates": len(candidates)}
    report = {"tool": "selfsame", "schema": 1, "label": "assumptions",
              "environment": {"python": python_exe, "modules": ",".join(modules)},
              "summary": summary, "assumptions": assumptions}
    written = None if ns.no_report else _write_report(report, ns.report_dir)

    print("\n" + "-" * 74)
    print("selfsame adjudicate: %d load-bearing · %d not-load-bearing · "
          "%d unverifiable%s"
          % (summary["load_bearing"], summary["not_load_bearing"],
             summary["unverifiable"],
             ("  ->  " + written) if written else ""))
    if ns.fail_on_load_bearing and summary["load_bearing"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
