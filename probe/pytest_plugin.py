"""pytest plugin: run a Selfsame behavioral-drift check at the end of a test run.

The point is discoverability — drift gets checked every time you run your tests,
no separate command. It is **compare-only**: it replays the accepted baseline's
stored inputs against the current code and reports deviation, and it NEVER
re-baselines on its own. You bless a new accepted build explicitly with
`selfsame snapshot ... -- pytest -q` — so a regression can never silently become
the new "correct" behavior.

Enable per-run with --selfsame, or always via pytest ini:

    [pytest]
    selfsame = true

Options:
  --selfsame                run the drift check at session end
  --selfsame-snapshot PATH  snapshot file (default .selfsame/snapshot.json)
  --selfsame-no-fail        report only; don't fail the pytest session on drift
"""

import os
import sys

_DEFAULT_SNAPSHOT = os.path.join(".selfsame", "snapshot.json")


def pytest_addoption(parser):
    group = parser.getgroup("selfsame", "Selfsame behavioral drift")
    group.addoption("--selfsame", action="store_true", default=False,
                    help="check behavioral drift vs the snapshot at session end")
    group.addoption("--selfsame-snapshot", default=None,
                    help="snapshot file to compare against (default %s)"
                         % _DEFAULT_SNAPSHOT)
    group.addoption("--selfsame-no-fail", action="store_true", default=False,
                    help="report drift but do not fail the pytest session")
    parser.addini("selfsame", "run a Selfsame drift check at session end",
                  type="bool", default=False)


def _enabled(config):
    try:
        if config.getoption("--selfsame"):
            return True
        return bool(config.getini("selfsame"))
    except (ValueError, KeyError):
        return False


def _session_drift(repo, snapshot_path, no_fail=False):
    """Run a compare-only drift check. Returns an exitstatus override (1 if drift
    should fail the session) or None to leave pytest's status unchanged."""
    if not os.path.isfile(snapshot_path):
        print("\n[selfsame] no baseline at %s — create one with "
              "`selfsame snapshot --modules <pkg> -- pytest -q`" % snapshot_path)
        return None
    from .snapshot import check_drift
    print("\n[selfsame] checking behavioral drift vs %s (compare-only) ..."
          % snapshot_path)
    code = check_drift(repo, snapshot_path, python_exe=sys.executable)
    if code == 1 and not no_fail:
        print("[selfsame] behavior deviated from the accepted baseline — "
              "failing the session (--selfsame-no-fail to report only).")
        return 1
    return None


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    if not _enabled(config):
        return
    repo = str(getattr(config, "rootpath", None) or config.rootdir)
    snap = config.getoption("--selfsame-snapshot")
    if not snap:
        snap = os.path.join(repo, _DEFAULT_SNAPSHOT)
    elif not os.path.isabs(snap):
        snap = os.path.join(repo, snap)
    override = _session_drift(repo, snap, config.getoption("--selfsame-no-fail"))
    if override is not None:
        session.exitstatus = override
