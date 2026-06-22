"""Child-process tracking so the probe never leaves orphans.

`probe verify` spawns a test command (pytest) and many replay workers via
subprocess. If the orchestrator is killed with SIGTERM (e.g. `pkill -f
probe.verify`) or Ctrl-C'd, those children would reparent to init and keep
running — saturating the machine. This module runs each child in its own session
(process group) and installs a SIGTERM/SIGINT/atexit reaper that kills the whole
child subtree before the orchestrator exits.
"""

import atexit
import os
import signal
import subprocess
import threading

_live = set()
_lock = threading.Lock()
_atexit_done = False
_signals_done = False


def _terminate_all():
    with _lock:
        procs = list(_live)
        _live.clear()
    for p in procs:
        if p.poll() is not None:
            continue
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)  # whole subtree
        except (ProcessLookupError, OSError):
            try:
                p.kill()
            except Exception:
                pass


def install():
    """Install reaper hooks. atexit is always registered; signal handlers are
    installed only from the main thread (a worker-thread caller still leaves them
    pending so a later main-thread call installs them). Idempotent."""
    global _atexit_done, _signals_done
    if not _atexit_done:
        atexit.register(_terminate_all)
        _atexit_done = True
    if not _signals_done and threading.current_thread() is threading.main_thread():
        _signals_done = True
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                prev = signal.getsignal(sig)

                def handler(signum, frame, _prev=prev):
                    _terminate_all()
                    signal.signal(signum, _prev if callable(_prev) else signal.SIG_DFL)
                    os.kill(os.getpid(), signum)  # re-raise default disposition

                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass  # platform without these signals


def _kill_tree(p, term_grace=None):
    """Kill a child's process group. If term_grace is set, send SIGTERM first and
    give the subtree that many seconds to exit cleanly (so e.g. the capture hook
    can flush) before SIGKILL."""
    try:
        pgid = os.getpgid(p.pid)
    except (ProcessLookupError, OSError):
        pgid = None
    if term_grace and pgid is not None:
        try:
            os.killpg(pgid, signal.SIGTERM)
            p.wait(timeout=term_grace)
            return
        except subprocess.TimeoutExpired:
            pass
        except (ProcessLookupError, OSError):
            return
    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGKILL)
        else:
            p.kill()
    except (ProcessLookupError, OSError):
        try:
            p.kill()
        except Exception:
            pass


def run(cmd, env=None, cwd=None, input=None, capture_output=False,
        text=False, timeout=None, term_grace=None):
    """A subprocess.run-alike that tracks the child (own session) and kills its
    subtree on timeout or orchestrator termination. On timeout, term_grace (if
    set) requests a graceful SIGTERM-then-SIGKILL so the child can flush."""
    install()
    stdout = subprocess.PIPE if capture_output else None
    stderr = subprocess.PIPE if capture_output else None
    start_new_session = hasattr(os, "setsid")
    p = subprocess.Popen(cmd, env=env, cwd=cwd, text=text,
                         stdin=subprocess.PIPE if input is not None else None,
                         stdout=stdout, stderr=stderr,
                         start_new_session=start_new_session)
    with _lock:
        _live.add(p)
    try:
        out, err = p.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(p, term_grace)
        p.communicate()
        raise
    finally:
        with _lock:
            _live.discard(p)
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)
