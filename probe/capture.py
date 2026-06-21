"""Capture real call arguments by observing an existing test run.

This is the pivot away from generating inputs: real tests already call the code
with realistic, type-correct arguments, so we record those instead of trying to
synthesise them. A `sys.setprofile` hook watches every call and pickles the
arguments of functions defined in the target module. Works with any test
framework (it doesn't wrap anything) and needs no type hints.

Run:  python3 -m probe.capture <module_name> <pytest_target> --out caps.pkl
e.g.  (cd repo && python3 -m probe.capture inflection tests.py --out /tmp/caps.pkl)
"""

from __future__ import annotations

import argparse
import pickle
import sys
from typing import Dict, List, Optional, Set

_PER_FUNC_CAP = 300  # keep replay bounded


class _Recorder:
    def __init__(self, module_name: str, func_names: Optional[Set[str]]):
        self.module_name = module_name
        self.func_names = func_names
        self.records: Dict[str, List[bytes]] = {}
        self._seen: Dict[str, set] = {}

    def profile(self, frame, event, arg):
        if event != "call":
            return
        code = frame.f_code
        name = code.co_name
        if self.func_names is not None and name not in self.func_names:
            return
        if frame.f_globals.get("__name__") != self.module_name:
            return
        bucket = self.records.setdefault(name, [])
        if len(bucket) >= _PER_FUNC_CAP:
            return
        try:
            varnames = code.co_varnames[:code.co_argcount]
            values = [frame.f_locals[v] for v in varnames]
            blob = pickle.dumps(values)
        except Exception:
            return
        seen = self._seen.setdefault(name, set())
        h = hash(blob)
        if h in seen:
            return
        seen.add(h)
        bucket.append(blob)


def capture(module_name: str, pytest_args: List[str],
            func_names: Optional[Set[str]] = None) -> Dict[str, List[bytes]]:
    import importlib

    import pytest
    importlib.import_module(module_name)  # ensure the target is importable
    rec = _Recorder(module_name, func_names)
    sys.setprofile(rec.profile)
    try:
        pytest.main(list(pytest_args))
    finally:
        sys.setprofile(None)
    return rec.records


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("module_name")
    ap.add_argument("pytest_target", nargs="+")
    ap.add_argument("--funcs", default=None, help="comma-separated function names")
    ap.add_argument("--out", required=True)
    ns = ap.parse_args(argv)
    funcs = set(ns.funcs.split(",")) if ns.funcs else None
    records = capture(ns.module_name, ns.pytest_target, funcs)
    with open(ns.out, "wb") as f:
        pickle.dump({"module": ns.module_name, "records": records}, f)
    total = sum(len(v) for v in records.values())
    print("captured %d distinct arg-sets across %d functions -> %s"
          % (total, len(records), ns.out))
    for name in sorted(records):
        print("  %-20s %d" % (name, len(records[name])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
