"""`probe` command-line entry point.

Subcommands:
  probe verify   verify a refactor using the repo's own tests (the main path)
  probe snapshot freeze the current build's behavior to a baseline file
  probe drift    measure how much current code deviates from the snapshot baseline
  probe check    check a refactor by generating inputs (two files or git refs)
  probe capture  record real call arguments from a test command
  probe attach   snapshot a running hook-enabled process's captures (no stop)
  probe replay   replay captured arguments across two refs
  probe fuzz     capture-seeded differential fuzzing (find divergences beyond tests)
  probe demo     run the built-in corpus demo
"""

import sys

_USAGE = __doc__


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    from . import _procs
    _procs.install()  # reap child subprocesses if the probe is killed/interrupted
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(_USAGE)
        return 0 if argv else 2
    cmd, rest = argv[0], argv[1:]

    if cmd == "verify":
        from .verify import main as run
        return run(rest)
    if cmd == "snapshot":
        from .snapshot import record_main as run
        return run(rest)
    if cmd == "drift":
        from .snapshot import drift_main as run
        return run(rest)
    if cmd == "check":
        from .check import main as run
        return run(rest)
    if cmd == "capture":
        from .capture import main as run
        return run(rest)
    if cmd == "attach":
        from .attach import main as run
        return run(rest)
    if cmd == "replay":
        from .replay import main as run
        return run(rest)
    if cmd == "fuzz":
        from .fuzz import main as run
        return run(rest)
    if cmd == "demo":
        from .runner import main as run
        return run()

    print("unknown command: %s\n" % cmd)
    print(_USAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
