"""Check a real refactor: are the functions behavior-equivalent across two
versions of a module?

Usage:
  # two files on disk
  python3 -m probe.check before.py after.py

  # two git refs + a path in the repo
  python3 -m probe.check --git BASE HEAD path/to/module.py
  python3 -m probe.check --git main HEAD app/calc.py

Each matched function is checked in an isolated subprocess. The verdict per
function is one of:
  equivalent   - same behavior on all generated inputs (a trustworthy pass)
  divergent    - behavior changed (shows the input + before -> after)
  unverifiable - nondeterministic; can't make a trustworthy verdict (+cause)
  unsupported  - no input-generation strategy for its parameter types
  error/timeout- failed to load or ran too long
"""

import json
import os
import subprocess
import sys
from typing import Dict, List, Optional

from .extract import pair_functions, source_from_file, source_from_git

_TIMEOUT_S = 15


def _check_one(before: str, after: str, name: str, repo_root: str) -> Dict:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
    payload = json.dumps({"before": before, "after": after, "name": name})
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "probe._worker"],
            input=payload, capture_output=True, text=True,
            timeout=_TIMEOUT_S, env=env, cwd=repo_root)
    except subprocess.TimeoutExpired:
        return {"verdict": "timeout", "cause": "exceeded %ds" % _TIMEOUT_S,
                "witness": None, "detail": None}
    if proc.returncode != 0 or not proc.stdout.strip():
        return {"verdict": "error",
                "cause": (proc.stderr.strip().splitlines() or ["nonzero exit"])[-1],
                "witness": None, "detail": None}
    return json.loads(proc.stdout)


_GLYPH = {"equivalent": "=", "divergent": "x", "unverifiable": "?",
          "unsupported": "-", "error": "!", "timeout": "!"}


def run(before_src: str, after_src: str, label: str, repo_root: str) -> int:
    pairing = pair_functions(before_src, after_src)
    print("Coverage Probe — checking %s" % label)
    print("=" * 64)

    results = []
    for name in pairing.matched:
        r = _check_one(before_src, after_src, name, repo_root)
        results.append((name, r))
        g = _GLYPH.get(r["verdict"], "?")
        line = "  [%s] %-26s %s" % (g, name, r["verdict"])
        if r["verdict"] == "divergent":
            line += "  @ %s" % r["witness"]
            if r.get("detail"):
                line += "  [%s]" % r["detail"]
        elif r.get("cause"):
            line += "  (%s)" % r["cause"]
        print(line)

    def _note(title, names):
        if names:
            print("\n%s: %s" % (title, ", ".join(names)))

    _note("Signature changed (not checked)", pairing.sig_changed)
    _note("Added (new, nothing to compare)", pairing.added)
    _note("Removed (gone, nothing to compare)", pairing.removed)

    counts: Dict[str, int] = {}
    for _, r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    verifiable = counts.get("equivalent", 0) + counts.get("divergent", 0)
    checked = len(results)

    print("\n" + "-" * 64)
    print("Functions matched      : %d" % checked)
    if checked:
        print("Verifiable coverage    : %.0f%%  (%d/%d got a trustworthy verdict)"
              % (100.0 * verifiable / checked, verifiable, checked))
    print("  equivalent           : %d" % counts.get("equivalent", 0))
    print("  divergent (changed)  : %d" % counts.get("divergent", 0))
    print("  unverifiable         : %d" % counts.get("unverifiable", 0))
    print("  unsupported          : %d" % counts.get("unsupported", 0))
    errs = counts.get("error", 0) + counts.get("timeout", 0)
    if errs:
        print("  error/timeout        : %d" % errs)

    # Exit non-zero if any real behavioral change was caught — useful in CI.
    return 1 if counts.get("divergent", 0) else 0


def _repo_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    repo_root = _repo_root()

    if argv and argv[0] == "--git":
        if len(argv) != 4:
            print(__doc__)
            return 2
        _, base, head, path = argv
        before = source_from_git(base, path)
        after = source_from_git(head, path)
        return run(before, after, "%s..%s : %s" % (base, head, path), repo_root)

    if len(argv) == 2:
        before = source_from_file(argv[0])
        after = source_from_file(argv[1])
        return run(before, after, "%s -> %s" % (argv[0], argv[1]), repo_root)

    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
