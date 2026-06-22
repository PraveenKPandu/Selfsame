"""In-process capture hook, installed into every Python process a test command
spawns (via a generated sitecustomize on PYTHONPATH). Configured by env vars:

  PROBE_CAPTURE_DIR     directory to write per-process capture files into
  PROBE_CAPTURE_MODULES comma-separated module names (prefix-matched, so a
                        package name captures its submodules too)
  PROBE_CAPTURE_FUNCS   optional comma-separated allow-list of names/qualnames

Records are keyed by *qualified* name so methods on different classes don't
collide: a method call keys as "ClassName.method", a classmethod as
"ClassName.classmethod", a plain function as "function". The first argument
(`self`/`cls`) is captured too, so a method can be replayed against either
version's class. Stdlib-only and defensive: any failure to record is swallowed
so it can never break the test run.
"""

import atexit
import os
import pickle
import sys
import threading

_DIR = os.environ.get("PROBE_CAPTURE_DIR")
_MODULES = tuple(m for m in os.environ.get("PROBE_CAPTURE_MODULES", "").split(",") if m)
_FUNCS = set(f for f in os.environ.get("PROBE_CAPTURE_FUNCS", "").split(",") if f)
_CAP_PER_FUNC = 300
# Safety valve: stop profiling after this many call events so a heavy suite
# (stress/integration) can't make capture run unboundedly. We keep what we have.
_MAX_EVENTS = int(os.environ.get("PROBE_CAPTURE_MAX_EVENTS", "3000000"))

_records = {}   # qualname -> list[pickled values]
_seen = {}      # qualname -> set[hash]
_lock = threading.Lock()
_events = 0
_stopped = False


def _is_test_module(name):
    for part in name.split("."):
        if part in ("tests", "test", "conftest") or part.startswith("test_") \
                or part.endswith("_test"):
            return True
    return False


def _module_matches(name):
    if not name or _is_test_module(name):
        return False  # don't capture the test code itself, only the code under test
    for m in _MODULES:
        if name == m or name.startswith(m + "."):
            return True
    return False


def _qualname(code, values):
    name = code.co_name
    if code.co_argcount and values:
        first = code.co_varnames[0]
        try:
            if first == "self":
                return type(values[0]).__qualname__ + "." + name
            if first == "cls":
                return values[0].__qualname__ + "." + name
        except Exception:
            return name
    return name


def _profile(frame, event, arg):
    if event != "call":
        return
    global _events, _stopped
    _events += 1
    if _events > _MAX_EVENTS:
        if not _stopped:
            _stopped = True
            sys.setprofile(None)  # bound overhead on pathological suites
        return
    code = frame.f_code
    if code.co_name.startswith("<"):
        return  # <lambda>, <genexpr>, <listcomp>, <module> — not replayable
    module = frame.f_globals.get("__name__")
    if not _module_matches(module):
        return
    try:
        values = [frame.f_locals[v] for v in code.co_varnames[:code.co_argcount]]
    except Exception:
        return
    qn = _qualname(code, values)
    if "<" in qn:
        return  # methods of test-local classes (<locals>) — not replayable
    if _FUNCS and qn not in _FUNCS and code.co_name not in _FUNCS:
        return
    key = module + "::" + qn  # so replay knows which module to import
    with _lock:
        bucket = _records.setdefault(key, [])
        if len(bucket) >= _CAP_PER_FUNC:
            return
        try:
            blob = pickle.dumps(values)
        except Exception:
            return
        h = hash(blob)
        seen = _seen.setdefault(key, set())
        if h in seen:
            return
        seen.add(h)
        bucket.append(blob)


def _flush():
    if not _DIR or not _records:
        return
    path = os.path.join(_DIR, "cap-%d.pkl" % os.getpid())
    try:
        with open(path, "wb") as f:
            pickle.dump(_records, f)
    except Exception:
        pass


def install():
    if not _DIR or not _MODULES:
        return
    sys.setprofile(_profile)
    threading.setprofile(_profile)  # cover threads started after us
    atexit.register(_flush)


install()
