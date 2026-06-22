"""`probe attach <pid>` — snapshot the captures of an ALREADY-RUNNING process
that was started under the capture hook, without stopping it.

How it works (and its honest limits):

  A process started with `probe capture -- <command>` (or any process that ran
  `import probe._capture_hook` with PROBE_CAPTURE_DIR/PROBE_CAPTURE_MODULES set)
  installs a signal handler (default SIGUSR1, see PROBE_CAPTURE_FLUSH_SIGNAL).
  `probe attach` simply sends that signal, which triggers the hook to flush its
  current captures to ``cap-<pid>.pkl`` in its PROBE_CAPTURE_DIR — the process
  keeps running. This is the robust, in-scope path: snapshot a long-running
  server on demand and keep it alive.

  It does NOT inject instrumentation into a process that is *not* already running
  the hook. Doing that to an arbitrary unmodified process requires a debugger /
  code injection (ptrace, gdb, pyrasite/madbg) and is heavily platform-restricted
  — on macOS, SIP and code-signing usually block ptrace of the system/signed
  Python entirely. The reliable way to capture from a running process is to start
  it under `probe capture` in the first place.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys


def _resolve_signal(name: str) -> int:
    """Resolve a signal name ("SIGUSR1"), bare number, or short name ("USR1")
    to an int. Raises ValueError if it can't be resolved on this platform."""
    raw = (name or "").strip()
    try:
        return int(raw)
    except ValueError:
        pass
    sig = getattr(signal, raw, None) or getattr(signal, "SIG" + raw, None)
    if sig is None:
        raise ValueError("unknown signal %r on this platform" % name)
    return int(sig)


def attach(pid: int, signal_name: str = "SIGUSR1") -> None:
    """Send the on-demand-flush signal to `pid`. Raises on failure (no such
    process, no permission, unknown signal)."""
    signum = _resolve_signal(signal_name)
    os.kill(pid, signum)  # propagates ProcessLookupError / PermissionError


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="probe attach",
        description="Snapshot the captures of a running hook-enabled process "
                    "(without stopping it) by sending its on-demand-flush signal.")
    ap.add_argument("pid", type=int, help="PID of the running process")
    ap.add_argument(
        "--signal", default=os.environ.get("PROBE_CAPTURE_FLUSH_SIGNAL", "SIGUSR1"),
        help="flush signal the target listens on (default: SIGUSR1, or "
             "$PROBE_CAPTURE_FLUSH_SIGNAL); must match how the target was started")
    ap.add_argument(
        "--capture-dir", default=os.environ.get("PROBE_CAPTURE_DIR"),
        help="the target's PROBE_CAPTURE_DIR, to report where the dump lands "
             "(optional; informational only)")
    ns = ap.parse_args(list(sys.argv[1:] if argv is None else argv))

    if sys.platform == "win32":
        print("probe attach is not supported on Windows (no POSIX signals).",
              file=sys.stderr)
        return 2

    try:
        attach(ns.pid, ns.signal)
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    except ProcessLookupError:
        print("error: no process with PID %d" % ns.pid, file=sys.stderr)
        return 1
    except PermissionError:
        print("error: not permitted to signal PID %d (different user?)" % ns.pid,
              file=sys.stderr)
        return 1
    except OSError as e:
        print("error: failed to signal PID %d: %s" % (ns.pid, e), file=sys.stderr)
        return 1

    print("sent %s to PID %d — it should flush its captures now." %
          (ns.signal, ns.pid))
    if ns.capture_dir:
        print("look for cap-%d.pkl in %s" % (ns.pid, ns.capture_dir))
    else:
        print("the dump lands as cap-%d.pkl in the target's PROBE_CAPTURE_DIR." %
              ns.pid)
    print("note: this only works if the target was started under the capture "
          "hook (e.g. `probe capture -- <command>`). It does NOT instrument an "
          "unmodified process; see `probe attach --help`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
