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
  PROBE_CAPTURE_FLUSH_SIGNAL  signal that triggers an on-demand flush of the
                         current captures without stopping the process (default
                         SIGUSR1). Set to a signal name ("SIGUSR2") or number, or
                         to "0"/"none" to disable. `probe attach <pid>` sends it.

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
_FLUSH_SIGNAL_NAME = os.environ.get("PROBE_CAPTURE_FLUSH_SIGNAL", "SIGUSR1")
_CAP_PER_FUNC = 300

# Set by the on-demand signal handler; a dedicated daemon thread does the actual
# flush. Doing the flush in the handler itself is unsafe: _flush() takes _lock,
# and if the signal fires in the main thread while it already holds _lock (inside
# _record), re-acquiring the non-reentrant lock would deadlock. The handler is
# kept trivial (set an Event) so it is re-entrancy-safe and never blocks.
_flush_event = threading.Event()

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


def _store(key, blob):
    """Dedup + cap a single pickled values blob under `key`. Shared by the
    import-hook path and the scoped-profile (__main__) path so both produce the
    identical on-disk format."""
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
    _store(key, blob)


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
# Scoped profile for the entry-point script (`__main__`)
# --------------------------------------------------------------------------- #
# The import hook can only wrap modules that are IMPORTED. The script run
# directly (e.g. `python myscript.py`) executes as module `__main__`, so its
# top-level functions are never wrapped. When a target module names the entry
# script's module (normally `__main__`), we install a `sys.setprofile` callback
# that records ONLY calls whose defining module matches a target. This is
# deliberately scoped:
#   * it is enabled ONLY when `__main__` (or another target) is the running
#     entry module — never on a generic test-runner invocation, where the import
#     hook already covers imported targets and a global profile would be costly;
#   * the callback filters on `frame.f_globals['__name__']` before doing any
#     work, so calls into pytest/stdlib/etc. cost just one dict lookup + a
#     membership test and are dropped immediately.

_profile_installed = False
# code-object -> __qualname__ map for the entry module(s). Built lazily so we get
# exact qualnames (incl. Class.method) even on Pythons without code.co_qualname.
_qualname_cache = {}


def _index_qualnames(module):
    """Map every plain-function code object defined in `module` to its qualname
    (top-level functions, static/class methods, and methods up to a small depth).
    Exact and stdlib-only — the source of truth for the profile path's keys."""
    out = {}
    func_t = type(_wrap)

    def add(fn):
        if isinstance(fn, func_t) and getattr(fn, "__module__", None) == module.__name__:
            code = getattr(fn, "__code__", None)
            if code is not None:
                out[code] = fn.__qualname__

    def walk_class(cls, depth=0):
        if depth > 5:
            return
        for raw in list(vars(cls).values()):
            if isinstance(raw, (staticmethod, classmethod)):
                add(raw.__func__)
            elif isinstance(raw, func_t):
                add(raw)
            elif isinstance(raw, type) and getattr(raw, "__module__", None) == module.__name__:
                walk_class(raw, depth + 1)

    for obj in list(vars(module).values()):
        if isinstance(obj, func_t):
            add(obj)
        elif isinstance(obj, type) and getattr(obj, "__module__", None) == module.__name__:
            walk_class(obj)
    return out


def _qualname_for(code, modname):
    """Resolve `code` -> qualname using the entry module's namespace. Returns the
    bare function name only as a last resort (top-level funcs are unambiguous)."""
    if hasattr(code, "co_qualname"):  # Python 3.11+: authoritative
        return code.co_qualname
    qn = _qualname_cache.get(code)
    if qn is not None:
        return qn
    mod = sys.modules.get(modname)
    if mod is not None:
        try:
            fresh = _index_qualnames(mod)
        except Exception:
            fresh = {}
        _qualname_cache.update(fresh)
        qn = _qualname_cache.get(code)
        if qn is not None:
            return qn
    return code.co_name  # top-level function defined before namespace settled


def _frame_values(frame):
    """Reconstruct the positional values list for a call frame, matching the
    format `_record` produces (positional+keyword params in declaration order
    with defaults already applied; *args contents appended; **kwargs dropped)."""
    code = frame.f_code
    nargs = code.co_argcount
    nkw = code.co_kwonlyargcount
    flags = code.co_flags
    has_varargs = bool(flags & inspect.CO_VARARGS)
    has_varkw = bool(flags & inspect.CO_VARKEYWORDS)
    loc = frame.f_locals
    names = code.co_varnames

    if not has_varargs and not has_varkw:
        # Plain function: positional-or-keyword params then keyword-only params,
        # in declaration order — exactly bind()+apply_defaults() ordering.
        return [loc[n] for n in names[:nargs + nkw]]

    # Varargs fallback mirrors _record: keep only the positionally-passed values
    # (the fixed positional params plus whatever *args absorbed), drop kw-only
    # and **kwargs. This keeps replay's fn(*values) call shape valid.
    values = [loc[n] for n in names[:nargs]]
    if has_varargs:
        star = loc.get(names[nargs + nkw])
        if isinstance(star, tuple):
            values.extend(star)
    return values


def _profiler(frame, event, arg):
    # Fire only on Python-level call entry; everything else is ignored cheaply.
    if event != "call":
        return
    try:
        g = frame.f_globals
        modname = g.get("__name__")
        if not _module_matches(modname):
            return
        code = frame.f_code
        # Only real functions (fast-locals). Class and module bodies also raise
        # "call" events but lack CO_OPTIMIZED — skip them, mirroring the
        # import-hook which wraps functions only, never class objects.
        if not (code.co_flags & inspect.CO_OPTIMIZED):
            return
        qn = _qualname_for(code, modname)
        if "<" in qn:  # lambdas / <locals> closures, like _should_wrap
            return
        name = code.co_name
        if _FUNCS and name not in _FUNCS and qn not in _FUNCS:
            return
        key = modname + "::" + qn
        if key in _full:  # fast path once we have enough samples
            return
        values = _frame_values(frame)
        blob = pickle.dumps(values)
    except Exception:
        return
    _store(key, blob)


def _maybe_install_profile():
    """Install the scoped profile iff a target module is the entry script.

    Returns True if installed. We detect the entry module by its name (`__main__`
    is the default for any `python script.py` / `python -m`), so the profile is
    NEVER active when the targets are only imported library modules."""
    global _profile_installed
    main_mod = sys.modules.get("__main__")
    main_name = getattr(main_mod, "__name__", None) if main_mod else None
    if not _module_matches(main_name):
        return False
    sys.setprofile(_profiler)
    # Also profile threads spawned after install (the entry script may use them).
    try:
        threading.setprofile(_profiler)
    except Exception:
        pass
    _profile_installed = True
    return True


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
    # Write atomically (temp + replace) so a concurrent reader (e.g. `probe
    # attach` or a periodic dump) never sees a half-written file.
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(tmp, "wb") as f:
            pickle.dump(snapshot, f)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _periodic_flush():
    import time
    while True:
        time.sleep(_FLUSH_SECS)
        _flush()


# --------------------------------------------------------------------------- #
# On-demand flush (signal-triggered)
# --------------------------------------------------------------------------- #
def _resolve_flush_signal():
    """Resolve PROBE_CAPTURE_FLUSH_SIGNAL to an int signal number, or None if
    disabled / unavailable on this platform. Accepts a name ("SIGUSR1"), a bare
    number ("10"), or "0"/"none"/"" to disable."""
    import signal as _signal
    raw = (_FLUSH_SIGNAL_NAME or "").strip()
    if not raw or raw.lower() in ("none", "off", "0"):
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    sig = getattr(_signal, raw, None) or getattr(_signal, "SIG" + raw, None)
    if sig is None:
        return None
    return int(sig)


def _flush_waiter():
    """Daemon thread: blocks until the signal handler sets the event, then
    flushes. Keeps all flush work (and the lock) off the signal handler."""
    while True:
        _flush_event.wait()
        _flush_event.clear()
        _flush()


def _install_flush_signal():
    """Install the on-demand flush signal handler. Best-effort and conservative:
    only from the main thread (Python requires it), chained to any pre-existing
    handler so we never silently swallow the app's own, and fully guarded so a
    failure here can never break the target process."""
    import signal as _signal
    try:
        signum = _resolve_flush_signal()
        if signum is None:
            return None
        if threading.current_thread() is not threading.main_thread():
            return None  # signal.signal() only works in the main thread
        prev = _signal.getsignal(signum)

        def _handler(sig, frame, _prev=prev):
            # Re-entrancy-safe: just wake the waiter thread; no lock, no I/O.
            _flush_event.set()
            # Be a good citizen: chain to a real pre-existing handler if any.
            if callable(_prev) and _prev not in (_signal.SIG_DFL, _signal.SIG_IGN):
                try:
                    _prev(sig, frame)
                except Exception:
                    pass

        _signal.signal(signum, _handler)
        threading.Thread(target=_flush_waiter, daemon=True).start()
        return signum
    except Exception:
        return None


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
    # If the entry-point script itself is a target, add a scoped profile so its
    # own top-level functions (module __main__, which is executed not imported)
    # get captured too.
    try:
        _maybe_install_profile()
    except Exception:
        pass
    atexit.register(_flush)
    if _FLUSH_SECS > 0:
        threading.Thread(target=_periodic_flush, daemon=True).start()
    # On-demand flush so a long-running hook-enabled process can be snapshotted
    # without being stopped (see `probe attach`).
    _install_flush_signal()


install()
