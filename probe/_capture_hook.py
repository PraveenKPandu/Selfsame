"""Targeted-wrapping capture hook, installed into every Python process a test or
app command spawns (via a generated sitecustomize on PYTHONPATH).

Rather than a global ``sys.setprofile`` (which fires on EVERY call in the process
— pytest internals included — and needs an event budget to stay bounded), this
installs an import hook that wraps ONLY the target modules' functions and methods
as they are imported. Overhead lands solely on calls into the code under test.

Configured by env vars:
  PROBE_CAPTURE_DIR      directory to write per-process capture files into
  PROBE_CAPTURE_MODULES  comma-separated module names (prefix-matched: a package
                         name captures its submodules too)
  PROBE_CAPTURE_FUNCS    optional comma-separated allow-list of names/qualnames
  PROBE_CAPTURE_FLUSH_SECS  periodic flush interval (default 5s) so a long-running
                         process killed by SIGTERM still leaves a capture

Each recorded call is stored as a pickled ``(args, kwargs)`` keyed by
"module::qualname" (qualname distinguishes methods across classes; the receiver
``self``/``cls`` is captured as the first positional arg). Stdlib-only and
defensive: any failure to record is swallowed so it can never break the run.
"""

import atexit
import functools
import importlib.abc
import inspect
import os
import pickle
import sys
import threading

_DIR = os.environ.get("PROBE_CAPTURE_DIR")
_MODULES = tuple(m for m in os.environ.get("PROBE_CAPTURE_MODULES", "").split(",") if m)
_FUNCS = set(f for f in os.environ.get("PROBE_CAPTURE_FUNCS", "").split(",") if f)
_FLUSH_SECS = float(os.environ.get("PROBE_CAPTURE_FLUSH_SECS", "5"))
_CAP_PER_FUNC = 300

# Dunders that are unsafe or pointless to wrap (called constantly / recursion).
_SKIP = {"__getattribute__", "__setattr__", "__getattr__", "__delattr__",
         "__new__", "__init_subclass__", "__set_name__", "__class_getitem__",
         "__subclasshook__", "__instancecheck__", "__subclasscheck__"}

_records = {}   # "module::qualname" -> list[pickled values]
_seen = {}      # key -> set[hash]
_full = set()   # keys that hit the per-func cap (fast path: stop recording)
_lock = threading.Lock()


def _is_test_module(name):
    for part in name.split("."):
        if part in ("tests", "test", "conftest") or part.startswith("test_") \
                or part.endswith("_test"):
            return True
    return False


def _module_matches(name):
    if not name or _is_test_module(name):
        return False
    for m in _MODULES:
        if name == m or name.startswith(m + "."):
            return True
    return False


# --------------------------------------------------------------------------- #
# Recording
# --------------------------------------------------------------------------- #
def _has_varargs(sig):
    for p in sig.parameters.values():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            return True
    return False


def _record(key, sig, args, kwargs):
    # Bind to a positional values list (defaults applied) so replay can call
    # fn(*values); this keeps the capture format identical to before. Functions
    # with *args/**kwargs fall back to raw positional args.
    try:
        if sig is not None and not _has_varargs(sig):
            ba = sig.bind(*args, **kwargs)
            ba.apply_defaults()
            values = list(ba.arguments.values())
        else:
            values = list(args)
        blob = pickle.dumps(values)
    except Exception:
        return
    with _lock:
        bucket = _records.setdefault(key, [])
        if len(bucket) >= _CAP_PER_FUNC:
            _full.add(key)
            return
        h = hash(blob)
        seen = _seen.setdefault(key, set())
        if h in seen:
            return
        seen.add(h)
        bucket.append(blob)
        if len(bucket) >= _CAP_PER_FUNC:
            _full.add(key)


def _wrap(fn, key):
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        sig = None

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if key not in _full:  # fast path once we have enough samples
            _record(key, sig, args, kwargs)
        return fn(*args, **kwargs)

    wrapper.__probe_wrapped__ = True
    return wrapper


def _should_wrap(fn, modname):
    if not isinstance(fn, type(_wrap)):  # only plain Python functions
        return False
    if getattr(fn, "__probe_wrapped__", False):
        return False
    if getattr(fn, "__module__", None) != modname:
        return False
    qn = getattr(fn, "__qualname__", "")
    if "<" in qn:  # <lambda>, <locals> closures
        return False
    if _FUNCS and fn.__name__ not in _FUNCS and qn not in _FUNCS:
        return False
    return True


def _wrap_class(cls, modname, depth=0):
    if depth > 5:
        return
    for name, raw in list(vars(cls).items()):
        if name in _SKIP:
            continue
        if isinstance(raw, staticmethod):
            inner = raw.__func__
            if _should_wrap(inner, modname):
                key = modname + "::" + inner.__qualname__
                setattr(cls, name, staticmethod(_wrap(inner, key)))
        elif isinstance(raw, classmethod):
            inner = raw.__func__
            if _should_wrap(inner, modname):
                key = modname + "::" + inner.__qualname__
                setattr(cls, name, classmethod(_wrap(inner, key)))
        elif isinstance(raw, type(_wrap)):
            if _should_wrap(raw, modname):
                setattr(cls, name, _wrap(raw, modname + "::" + raw.__qualname__))
        elif isinstance(raw, type):
            if getattr(raw, "__module__", None) == modname:
                _wrap_class(raw, modname, depth + 1)


def _wrap_module(module):
    modname = getattr(module, "__name__", None)
    if not modname:
        return
    for name, obj in list(vars(module).items()):
        if isinstance(obj, type(_wrap)):
            if _should_wrap(obj, modname):
                setattr(module, name, _wrap(obj, modname + "::" + obj.__qualname__))
        elif isinstance(obj, type) and getattr(obj, "__module__", None) == modname:
            _wrap_class(obj, modname)


# --------------------------------------------------------------------------- #
# Import hook
# --------------------------------------------------------------------------- #
class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if not _module_matches(fullname):
            return None
        # Delegate to the finders AFTER us to get the real spec (no recursion),
        # then wrap the loader so we post-process the module after it executes.
        try:
            idx = sys.meta_path.index(self)
        except ValueError:
            idx = 0
        for finder in sys.meta_path[idx + 1:]:
            try:
                spec = finder.find_spec(fullname, path, target)
            except Exception:
                spec = None
            if spec is not None and spec.loader is not None:
                self._wrap_loader(spec)
                return spec
        return None

    @staticmethod
    def _wrap_loader(spec):
        loader = spec.loader
        exec_module = getattr(loader, "exec_module", None)
        if exec_module is None:
            return

        def wrapped_exec(module, _orig=exec_module):
            _orig(module)
            try:
                _wrap_module(module)
            except Exception:
                pass

        loader.exec_module = wrapped_exec


# --------------------------------------------------------------------------- #
# Flushing
# --------------------------------------------------------------------------- #
def _flush():
    if not _DIR:
        return
    with _lock:
        if not _records:
            return
        snapshot = {k: list(v) for k, v in _records.items()}
    path = os.path.join(_DIR, "cap-%d.pkl" % os.getpid())
    try:
        with open(path, "wb") as f:
            pickle.dump(snapshot, f)
    except Exception:
        pass


def _periodic_flush():
    import time
    while True:
        time.sleep(_FLUSH_SECS)
        _flush()


def install():
    if not _DIR or not _MODULES:
        return
    sys.meta_path.insert(0, _Finder())
    # Wrap any target modules already imported before us.
    for name, mod in list(sys.modules.items()):
        if mod is not None and _module_matches(name):
            try:
                _wrap_module(mod)
            except Exception:
                pass
    atexit.register(_flush)
    if _FLUSH_SECS > 0:
        threading.Thread(target=_periodic_flush, daemon=True).start()


install()
